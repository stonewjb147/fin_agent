"""Command-line entry point.

Phase 1 implements `collect`, `data-check` and `snapshot`. Later phases add
factor-report / valuation / portfolio / attribution / backtest / daily; they
are registered now so the interface is stable, but exit with a clear message
instead of pretending to work.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from finagent import config
from finagent.backtest.costs import DEFAULT_COST, cost_from_bps
from finagent.backtest.report import format_backtest, run_backtest_suite
from finagent.data.akshare_provider import default_provider
from finagent.data.collect import collect
from finagent.data.health import check_health
from finagent.data.lineage import SnapshotStore
from finagent.data.universe import load_universe
from finagent.factors import load_close_panel
from finagent.flows import build_flows_report, format_flows
from finagent.portfolio.construct import format_portfolio
from finagent.portfolio.pipeline import run_portfolio
from finagent.predictions.ledger import PredictionLedger
from finagent.predictions.ledger import format_summary as format_ledger
from finagent.research.report import NoDataError, format_summary, run_factor_report
from finagent.signals.pipeline import format_signals, run_signal_pipeline
from finagent.signals.score import NoScoresError


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _resolve_as_of(provider, value: str | None) -> date:
    """The requested date, snapped back to the last trading day at or before it.

    Every downstream artefact is named after its as_of, so a request for a
    Saturday must not silently produce a file labelled with that Saturday while
    holding Friday's data (nor crash); we snap and say so on stderr.
    """
    if not value:
        return provider.last_trading_day()
    requested = _parse_date(value)
    if provider.is_trading_day(requested):
        return requested
    fallback = provider.last_trading_day(requested)
    print(f"{requested} is not a trading day; using {fallback}", file=sys.stderr)
    return fallback


def _universe(path: str | None):
    universe = load_universe(path or config.CONFIG_DIR / "universe.yaml")
    problems = universe.validate()
    if problems:
        print("Universe validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(2)
    return universe


def cmd_collect(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    start = _parse_date(args.start)
    end = _parse_date(args.end) if args.end else provider.last_trading_day()
    if start > end:
        print("start must be <= end", file=sys.stderr)
        return 2

    print(f"Collecting {start} .. {end}  universe={universe.version} ({len(universe.for_date(end))} ETFs)")
    result = collect(
        provider,
        universe,
        start,
        end,
        snapshots=args.snapshots,
        force=args.force,
    )

    print(f"\nDatasets written : {len(result.datasets)}")
    print(f"Failures         : {len(result.failures)}")
    if result.snapshot_id:
        print(f"Snapshot         : {result.snapshot_id}")
    if result.quality_path:
        print(f"Quality report   : {result.quality_path}")

    errors = [f for f in result.failures if f["kind"] == "error"]
    coverage = [f for f in result.failures if f["kind"] == "coverage"]
    if coverage:
        print("\nCoverage gaps (expected for some indices):")
        for f in coverage[:10]:
            print(f"  - {f['dataset']}/{f['key']}: {f['message'][:110]}")
    if errors:
        print("\nErrors:")
        for f in errors:
            print(f"  - {f['dataset']}/{f['key']}: {f['message'][:160]}")
        return 1
    return 0


def cmd_data_check(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    report = check_health(provider, provider.cache, universe, as_of)

    print(f"Data check for {report['as_of']} (last trading day {report['last_trading_day']})")
    print(f"{'LEVEL':8s} {'DATASET':18s} {'KEY':10s} {'LAST':12s} {'LAG':>5s} {'ROWS':>7s}  MESSAGE")
    for c in report["checks"]:
        print(
            f"{c['level']:8s} {c['dataset']:18s} {c['key']:10s} "
            f"{str(c['last_date']):12s} {str(c['lag_days']):>5s} {str(c['rows']):>7s}  {c['message']}"
        )
    print(f"\nOK={report['ok']} errors={report['errors']} warnings={report['warnings']}")

    out = config.QUALITY_DIR / f"health_{report['as_of']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out}")
    return 0 if report["ok"] else 1


def cmd_snapshot(args: argparse.Namespace) -> int:
    provider = default_provider()
    store = SnapshotStore(config.SNAPSHOT_DIR)
    if args.id:
        snap = store.load(args.id)
        print(f"snapshot {snap.snapshot_id}  as_of={snap.as_of}  entries={len(snap.entries)}")
        for e in snap.entries:
            print(f"  {e.dataset:22s} {e.key:12s} rows={e.rows:<6d} last={e.last_date} sha={e.checksum[:12]}")
        verification = store.verify(args.id, provider.cache)
        print(f"\nchecksum verification: {'OK' if verification['ok'] else 'FAILED'}")
        return 0 if verification["ok"] else 1
    files = sorted(Path(config.SNAPSHOT_DIR).glob("snap-*.json"))
    print(f"{len(files)} snapshots in {config.SNAPSHOT_DIR}")
    for f in files[-10:]:
        print(f"  {f.stem}")
    return 0


def cmd_factor_report(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]

    try:
        report = run_factor_report(
            universe,
            as_of=as_of,
            factor_names=args.factors.split(",") if args.factors else None,
            horizons=horizons,
            execution_lag=args.execution_lag,
        )
    except NoDataError as exc:
        print(f"factor-report: {exc}", file=sys.stderr)
        return 1
    print(format_summary(report))
    print(f"\nFactors : {report['factor_file']}")
    print(f"Report  : {report['report_file']}")
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    try:
        result = run_signal_pipeline(
            universe,
            as_of=as_of,
            horizon=args.horizon,
            n_long=args.n_long,
            n_short=args.n_short,
            min_composite=args.min_composite,
            min_confidence=args.min_confidence,
            execution_lag=args.execution_lag,
            news_path=args.news,
            news_weight=args.news_weight,
        )
    except NoScoresError as exc:
        print(f"signals: {exc}", file=sys.stderr)
        print("Run `collect` first, or pass --date with a date that has price data.", file=sys.stderr)
        return 1
    print(format_signals(result))
    if result.get("signal_file"):
        print(f"\nSignals : {result['signal_file']}")
    print(f"Ledger  : {config.PREDICTION_DIR}")
    return 0


def cmd_flows(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    report = build_flows_report(
        universe,
        as_of,
        cache_dir=provider.cache.root,
        news_path=args.news,
        window=args.window,
    )
    print(format_flows(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_portfolio(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    try:
        result = run_portfolio(universe, as_of=as_of)
    except (NoDataError, NoScoresError) as exc:
        print(f"portfolio: {exc}", file=sys.stderr)
        return 1
    print(format_portfolio(result))
    print(f"\nPortfolio : {result.get('portfolio_file')}")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    as_of = _resolve_as_of(provider, args.date)
    ledger = PredictionLedger()

    if args.settle:
        close = load_close_panel(config.CACHE_DIR, universe.symbols(as_of), as_of)
        settled = ledger.settle(close, as_of, symbols=universe.symbols(as_of))
        print(f"settled {len(settled)} prediction(s) as of {as_of}")

    summary = ledger.summary(as_of)
    print(format_ledger(summary))
    out = config.QUALITY_DIR / f"ledger_summary_{as_of.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary : {out}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    universe = _universe(args.universe)
    provider = default_provider()
    end = _resolve_as_of(provider, args.end)
    start = _parse_date(args.start)
    if start >= end:
        print(f"backtest: --start {start} must be before --end {end}", file=sys.stderr)
        return 1

    cost = DEFAULT_COST
    if args.cost_bps is not None:
        if args.cost_bps < 0:
            print("backtest: --cost-bps cannot be negative", file=sys.stderr)
            return 1
        cost = cost_from_bps(args.cost_bps)

    try:
        payload = run_backtest_suite(
            universe,
            start=start,
            end=end,
            cost=cost,
            rebalance_days=args.rebalance_days,
            execution_price=args.exec_price,
            execution_lag=args.execution_lag,
            top_n=args.top_n,
            trials=args.trials,
        )
    except ValueError as exc:
        print(f"backtest: {exc}", file=sys.stderr)
        return 1

    print(format_backtest(payload["report"]))
    print(f"\nReport : {payload['report'].get('report_file')}")
    print(f"NAV    : {payload['report'].get('daily_file')}")
    return 0


def _planned(phase: str):
    def run(_: argparse.Namespace) -> int:
        print(f"This command belongs to {phase} and is not implemented yet.", file=sys.stderr)
        return 2

    return run


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="finagent", description="A-share ETF research assistant")
    ap.add_argument("--version", action="version", version="finagent 0.1.0")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="fetch data into the Parquet cache and build a snapshot")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument("--snapshots", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--force", action="store_true", help="ignore today's cache")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("data-check", help="freshness / completeness checks over the cache")
    p.add_argument("--date", default=None)
    p.add_argument("--universe", default=None)
    p.set_defaults(func=cmd_data_check)

    p = sub.add_parser("snapshot", help="inspect or verify a lineage snapshot")
    p.add_argument("--id", default=None)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("factor-report", help="compute factors and evaluate IC / ICIR / HAC t")
    p.add_argument("--date", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument("--factors", default=None, help="comma separated, defaults to all price factors")
    p.add_argument("--horizons", default="1,5,20", help="forward-return horizons in trading days")
    p.add_argument(
        "--execution-lag",
        type=int,
        default=config.EXECUTION_LAG_DAYS,
        help="days between signal and execution (default: T+1)",
    )
    p.set_defaults(func=cmd_factor_report)

    p = sub.add_parser("signals", help="structured signals + prediction ledger")
    p.add_argument("--date", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument("--horizon", type=int, default=20, help="holding period in trading days")
    p.add_argument("--n-long", type=int, default=10)
    p.add_argument("--n-short", type=int, default=5)
    p.add_argument("--min-composite", type=float, default=0.25)
    p.add_argument("--min-confidence", type=float, default=0.5)
    p.add_argument("--execution-lag", type=int, default=config.EXECUTION_LAG_DAYS)
    p.add_argument(
        "--news",
        default=None,
        help="news JSON for the overlay (default: data/news/<date>.json; missing file is skipped)",
    )
    p.add_argument("--news-weight", type=float, default=0.20, help="composite units per unit of news score")
    p.set_defaults(func=cmd_signals)

    p = sub.add_parser("flows", help="Phase 5 flow / share / premium / news data status")
    p.add_argument("--date", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument("--window", type=int, default=5, help="sector-flow snapshots to accumulate")
    p.add_argument("--news", default=None, help="news JSON (default: data/news/<date>.json)")
    p.add_argument("--json", action="store_true", help="also print the full JSON payload")
    p.set_defaults(func=cmd_flows)

    p = sub.add_parser("portfolio", help="long-only target weights from the composite score")
    p.add_argument("--date", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.set_defaults(func=cmd_portfolio)

    p = sub.add_parser("ledger", help="inspect or settle the prediction ledger")
    p.add_argument("--date", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument("--settle", action="store_true", help="settle matured predictions first")
    p.set_defaults(func=cmd_ledger)

    p = sub.add_parser("backtest", help="daily backtest with costs, CPCV / PBO / DSR")
    p.add_argument("--start", required=True, help="first date of the backtest window")
    p.add_argument("--end", default=None, help="defaults to the latest trading day")
    p.add_argument("--universe", default=None)
    p.add_argument(
        "--rebalance-days",
        type=int,
        default=config.BACKTEST_REBALANCE_DAYS,
        help="trading days between rebalances (default: 5)",
    )
    p.add_argument(
        "--exec-price",
        choices=("close", "open"),
        default="close",
        help="price used to fill (default: close, matching the ledger's T+1 close convention)",
    )
    p.add_argument("--execution-lag", type=int, default=config.EXECUTION_LAG_DAYS)
    p.add_argument(
        "--cost-bps",
        type=float,
        default=None,
        help="override one-way cost in basis points (default: 2bp commission + 5bp slippage)",
    )
    p.add_argument("--top-n", type=int, default=10, help="holdings in the top-N strategy")
    p.add_argument(
        "--trials",
        type=int,
        default=None,
        help="how many configurations were tried, for the deflated Sharpe (default: the variants run here)",
    )
    p.set_defaults(func=cmd_backtest)

    for name, phase, help_text in (
        ("valuation", "Phase K1", "index valuation dashboard"),
        ("attribution", "Phase K4", "Brinson / factor attribution"),
        ("daily", "Phase 6", "end-to-end daily research report"),
    ):
        p = sub.add_parser(name, help=f"{help_text} ({phase}, planned)")
        p.set_defaults(func=_planned(phase))

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config.ensure_dirs()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
