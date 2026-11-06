"""Assemble the Phase 1-4 evaluation: checks, value benchmarks, diagnostics."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.backtest.costs import DEFAULT_COST, CostModel
from finagent.backtest.data import load_price_panels
from finagent.backtest.engine import BacktestConfig
from finagent.backtest.report import run_backtest_suite
from finagent.backtest.strategies import default_strategies
from finagent.data.cache import ParquetCache
from finagent.data.panel import as_date
from finagent.evaluation.benchmarks import benchmark_specs, run_benchmarks
from finagent.evaluation.checks import (
    check_backtest,
    check_data_layer,
    check_factor_kernel,
    check_pit_rerun,
    check_signals_portfolio,
)
from finagent.evaluation.value import (
    break_even_bps,
    cost_sensitivity,
    extended_metrics,
    ic_by_year,
    ledger_state,
    yearly_returns,
)
from finagent.factors import DEFAULT_FACTORS
from finagent.portfolio.policy import load_policy
from finagent.research.report import MIN_SYMBOLS, factor_snapshot
from finagent.signals.score import composite_scores

COST_LEVELS = (0.0, 7.0, 20.0)


def run_phase_eval(
    universe,
    *,
    start,
    end,
    cache_dir: str | Path | None = None,
    cost: CostModel | None = None,
    quality_dir: str | Path | None = None,
    bond_symbol: str | None = None,
    write: bool = True,
    out_dir: str | Path | None = None,
) -> dict:
    start, end = as_date(start), as_date(end)
    as_of = end
    cost = cost or DEFAULT_COST
    cache_dir = Path(cache_dir or config.CACHE_DIR)
    quality_dir = Path(quality_dir or config.QUALITY_DIR)
    policy = load_policy()

    panels = load_price_panels(cache_dir, universe.symbols(as_of), as_of)
    close = panels["close"]
    cfg = BacktestConfig(start=start, end=end)

    suite = run_backtest_suite(
        universe,
        start=start,
        end=end,
        cache_dir=cache_dir,
        cost=cost,
        policy=policy,
        write=False,
    )
    results = suite["results"]
    specs = benchmark_specs(universe, close, start, end, bond_symbol=bond_symbol)
    benchmarks = run_benchmarks(panels, specs, cfg, cost)
    hs300 = benchmarks["hs300_buyhold"].daily["ret"].fillna(0.0)

    factors = factor_snapshot(close, list(DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
    strategies = default_strategies(universe, composite_scores(factors), policy, top_n=10)
    sensitivity = cost_sensitivity(panels, strategies, cfg, bps=COST_LEVELS)

    levels = [
        (
            float(level),
            sensitivity[f"{level:g}"]["top_10"]["cagr"],
            sensitivity[f"{level:g}"]["policy_no_tilt"]["cagr"],
        )
        for level in COST_LEVELS
    ]

    checks = []
    checks += check_data_layer(cache_dir, universe, as_of, quality_dir, close=close)
    checks += check_factor_kernel(cache_dir, universe, as_of)
    checks += check_signals_portfolio(universe, as_of)
    checks += check_backtest(results, panels)
    cutoff = _snap(close.index, pd.Timestamp(end) - pd.Timedelta(days=365))
    checks.append(check_pit_rerun(panels, strategies["policy_no_tilt"], cfg, cost, cutoff))

    calendar = _calendar(cache_dir)
    ledger = ledger_state(config.PREDICTION_DIR, as_of, calendar=calendar)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "n_days": int(len(close))},
        "universe_version": getattr(universe, "version", "unknown"),
        "n_symbols": int(close.shape[1]),
        "cost_model": cost.as_dict(),
        "backtest": cfg.as_dict(),
        "benchmarks": {
            "bond_symbol": _bond(specs),
            "specs": {
                name: {"weights": spec.strategy.weights, "rebalance_days": spec.rebalance_days}
                for name, spec in specs.items()
            },
        },
        "value": {
            "strategies": {
                name: {
                    "metrics": extended_metrics(result.daily["ret"].fillna(0.0), hs300),
                    "yearly": yearly_returns(result.daily["ret"]),
                }
                for name, result in results.items()
            },
            "benchmarks": {
                name: {
                    "metrics": extended_metrics(result.daily["ret"].fillna(0.0), hs300),
                    "yearly": yearly_returns(result.daily["ret"]),
                }
                for name, result in benchmarks.items()
            },
            "cost_sensitivity": sensitivity,
            "break_even_bps": {
                "top_10_vs_policy_no_tilt": break_even_bps(levels),
                "levels": [{"bps": b, "top_10_cagr": a, "policy_no_tilt_cagr": c} for b, a, c in levels],
            },
            "factor_ic_by_year": ic_by_year(close, factors, list(DEFAULT_FACTORS), (1, 5, 20)),
            "ledger": ledger,
        },
        "diagnostics": suite["report"].get("diagnostics", {}),
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "checks_total": len(checks),
            "checks_hard_total": sum(1 for c in checks if c.hard),
            "checks_soft_total": sum(1 for c in checks if not c.hard),
            "checks_hard_failed": [c.name for c in checks if c.hard and not c.ok],
            "checks_soft_failed": [c.name for c in checks if not c.hard and not c.ok],
        },
    }

    if write:
        out_dir = Path(out_dir or quality_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"phase_eval_{as_of.isoformat()}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        payload["report_file"] = str(path)
    return payload


def _bond(specs) -> str:
    weights = specs["sixty_forty"].strategy.weights
    return next(symbol for symbol in weights if symbol != "510300")


def _snap(index: pd.DatetimeIndex, target: pd.Timestamp) -> pd.Timestamp:
    candidate = index[index <= target]
    return candidate[-1] if len(candidate) else index[0]


def _calendar(cache_dir: Path) -> pd.DatetimeIndex | None:
    frame = ParquetCache(cache_dir).read("trade_calendar", "all")
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    return pd.DatetimeIndex(pd.to_datetime(frame["date"])).sort_values()


# ------------------------------------------------------------------- terminal
def format_eval(payload: dict) -> str:
    window = payload["window"]
    lines = [
        f"Phase 1-4 evaluation  {window['start']}..{window['end']}  "
        f"{payload['n_symbols']} symbols  cost={payload['cost_model']['one_way_bps']:.1f}bp/side",
        "",
        "VALUE",
        f"{'NAME':<18}{'CAGR':>8}{'VOL':>8}{'SHARPE':>8}{'SORTINO':>8}{'MDD':>8}"
        f"{'WORST12M':>10}{'UW%':>7}{'BETA':>7}{'CORR':>7}",
    ]
    for group in ("strategies", "benchmarks"):
        for name, block in payload["value"][group].items():
            m = block["metrics"]
            lines.append(
                f"{name:<18}{_pct(m['cagr']):>8}{_pct(m['ann_vol']):>8}{_num(m['sharpe']):>8}"
                f"{_num(m['sortino']):>8}{_pct(m['max_drawdown']):>8}{_pct(m['worst_12m']):>10}"
                f"{_pct(m['share_underwater']):>7}{_num(m['beta']):>7}{_num(m['corr']):>7}"
            )

    lines.append("")
    lines.append("COST SENSITIVITY (net CAGR)")
    header = f"{'':<18}" + "".join(f"{b:>8.0f}bp" for b in COST_LEVELS)
    lines.append(header)
    row = payload["value"]["cost_sensitivity"]
    for name in payload["value"]["strategies"]:
        lines.append(f"{name:<18}" + "".join(f"{_pct(row[f'{b:g}'][name]['cagr']):>10}" for b in COST_LEVELS))
    breakeven = payload["value"]["break_even_bps"]["top_10_vs_policy_no_tilt"]
    lines.append(f"break-even top_10 vs policy_no_tilt: {'none' if breakeven is None else f'{breakeven:.1f}bp/side'}")

    ic_rows = payload["value"]["factor_ic_by_year"]
    if ic_rows:
        lines.append("")
        lines.append("FACTOR IC BY YEAR (directional)")
        years = sorted({row["year"] for row in ic_rows})
        lines.append(f"{'FACTOR':<16}{'H':>4}" + "".join(f"{y:>9}" for y in years))
        by_key: dict[tuple[str, int], dict[int, float]] = {}
        for row in ic_rows:
            by_key.setdefault((row["factor"], row["horizon"]), {})[row["year"]] = row["ic_mean"]
        for (factor, horizon), values in sorted(by_key.items()):
            lines.append(
                f"{factor:<16}{horizon:>4}" + "".join(f"{values.get(y, float('nan')):>9.3f}" for y in years)
            )

    ledger = payload["value"]["ledger"]
    lines.append("")
    lines.append(
        f"LEDGER  predictions={ledger['n_predictions']} settled={ledger['n_settled']} "
        f"first settlement~{ledger.get('first_settlement_date')}  "
        f"need {ledger['required_settled_5pct']} independent calls for +-5%"
    )

    hard = [c for c in payload["checks"] if c["hard"]]
    soft = [c for c in payload["checks"] if not c["hard"]]
    lines.append("")
    lines.append(
        f"CHECKS  {sum(c['ok'] for c in hard)}/{len(hard)} hard passed, "
        f"{sum(c['ok'] for c in soft)}/{len(soft)} informational"
    )
    for check in payload["checks"]:
        if check["hard"] and not check["ok"]:
            lines.append(f"  FAIL {check['name']}: {check['detail']}")
    if payload.get("report_file"):
        lines.append(f"\nJSON: {payload['report_file']}")
    return "\n".join(lines)


def _pct(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"


def _num(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"
