"""Hard acceptance checks on the real cache, not on synthetic fixtures.

Each check answers one question with evidence. `hard=False` marks a finding that
is worth reporting but does not invalidate the run (for example "no factor is
significant" is a result, not a bug).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from finagent import config
from finagent.backtest.costs import CostModel
from finagent.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from finagent.data.cache import ParquetCache
from finagent.data.lineage import SnapshotStore
from finagent.factors import DEFAULT_FACTORS, load_close_panel
from finagent.research.report import MIN_SYMBOLS, factor_snapshot

MIN_HISTORY_DAYS = 250


@dataclass
class Check:
    phase: str
    name: str
    ok: bool
    detail: str
    hard: bool = True
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "name": self.name,
            "ok": bool(self.ok),
            "hard": bool(self.hard),
            "detail": self.detail,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------- Phase 1
def check_data_layer(
    cache_dir: str | Path,
    universe,
    as_of,
    quality_dir: str | Path | None = None,
    close: pd.DataFrame | None = None,
) -> list[Check]:
    cache = ParquetCache(cache_dir)
    quality_dir = Path(quality_dir or config.QUALITY_DIR)
    symbols = universe.symbols(as_of)
    rows: dict[str, int] = {}
    for symbol in symbols:
        frame = cache.read("etf_daily_hfq", symbol)
        if frame is None or frame.empty:
            continue
        rows[symbol] = int(len(frame))

    enough = [s for s, n in rows.items() if n >= MIN_HISTORY_DAYS]
    checks = [
        Check(
            "Phase 1",
            "universe_history",
            len(enough) == len(symbols),
            f"{len(enough)}/{len(symbols)} ETFs have >= {MIN_HISTORY_DAYS} sessions",
            evidence={"min_rows": min(rows.values()) if rows else 0},
        )
    ]
    if close is not None and len(close):
        panel_end = pd.Timestamp(close.index.max()).date()
        checks.append(
            Check(
                "Phase 1",
                "panel_truncated",
                panel_end <= pd.Timestamp(as_of).date(),
                f"evaluation panel ends {panel_end} (as_of {pd.Timestamp(as_of).date()}); "
                "the cache may hold later rows, the panel must not",
            )
        )

    health_path = quality_dir / f"health_{pd.Timestamp(as_of).date().isoformat()}.json"
    if health_path.exists():
        health = json.loads(health_path.read_text(encoding="utf-8"))
        checks.append(
            Check(
                "Phase 1",
                "health_report",
                bool(health.get("ok")) and int(health.get("errors", 0)) == 0,
                f"ok={health.get('ok')} errors={health.get('errors')} warnings={health.get('warnings')}",
                evidence={"path": str(health_path)},
            )
        )
    else:
        checks.append(Check("Phase 1", "health_report", False, f"missing {health_path}", hard=False))

    collect_path = quality_dir / f"collect_{pd.Timestamp(as_of).date().isoformat()}.json"
    if collect_path.exists():
        collect = json.loads(collect_path.read_text(encoding="utf-8"))
        failures = collect.get("failures", [])
        checks.append(
            Check(
                "Phase 1",
                "collect_report",
                bool(collect.get("ok")),
                f"datasets={collect.get('dataset_count')} failures={len(failures)} "
                f"snapshot={collect.get('snapshot_id')}",
                hard=False,
                evidence={"known_failures": [f"{f.get('dataset')}/{f.get('key')}" for f in failures]},
            )
        )

    snapshots = sorted(Path(config.SNAPSHOT_DIR).glob("snap-*.json"), key=lambda p: p.stat().st_mtime)
    if snapshots:
        latest = snapshots[-1].stem
        verification = SnapshotStore().verify(latest, cache)
        checks.append(
            Check(
                "Phase 1",
                "lineage_checksum",
                bool(verification["ok"]),
                f"{latest}: {sum(1 for e in verification['entries'] if e['checksum_match'])}/"
                f"{len(verification['entries'])} checksums match",
                evidence={"snapshot_id": latest},
            )
        )
    else:
        checks.append(Check("Phase 1", "lineage_checksum", False, "no snapshot found", hard=False))
    return checks


# --------------------------------------------------------------------- Phase 2
def check_factor_kernel(
    cache_dir: str | Path,
    universe,
    as_of,
    *,
    factors_path: str | Path | None = None,
    report_path: str | Path | None = None,
) -> list[Check]:
    as_of_date = pd.Timestamp(as_of).date()
    symbols = universe.symbols(as_of_date)
    close = load_close_panel(cache_dir, symbols, as_of_date)
    recomputed = factor_snapshot(close, list(DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
    factors_path = Path(factors_path or config.DATA_DIR / "factors" / f"{as_of_date.isoformat()}.parquet")
    checks: list[Check] = []

    if factors_path.exists():
        stored = pd.read_parquet(factors_path)
        keys = ["date", "symbol", "factor", "value"]
        merged = stored[keys].merge(recomputed[keys], on=["date", "symbol", "factor"], suffixes=("_stored", "_new"))
        diff = float(np.nanmax(np.abs(merged["value_stored"] - merged["value_new"]))) if len(merged) else np.inf
        checks.append(
            Check(
                "Phase 2",
                "factor_panel_reproducible",
                len(merged) == len(stored) and diff < 1e-9,
                f"{len(merged)}/{len(stored)} rows match, max |diff|={diff:.2e}",
                evidence={"max_abs_diff": diff},
            )
        )
    else:
        checks.append(Check("Phase 2", "factor_panel_reproducible", False, f"missing {factors_path}"))

    cutoff = close.index[max(0, len(close) - 60)]
    partial = factor_snapshot(close.loc[:cutoff], list(DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
    shared = recomputed.merge(partial, on=["date", "symbol", "factor"], suffixes=("_full", "_cut"))
    pit_diff = float(np.nanmax(np.abs(shared["value_full"] - shared["value_cut"]))) if len(shared) else np.inf
    checks.append(
        Check(
            "Phase 2",
            "no_lookahead",
            len(shared) > 0 and pit_diff < 1e-12,
            f"truncating at {cutoff.date()} leaves {len(shared)} shared values unchanged "
            f"(max |diff|={pit_diff:.2e})",
            evidence={"cutoff": cutoff.date().isoformat(), "max_abs_diff": pit_diff},
        )
    )

    report_path = Path(report_path or config.QUALITY_DIR / f"factor_report_{as_of_date.isoformat()}.json")
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        tests = report.get("tests", [])
        neutral = any("significant_neutral" in test for test in tests)
        flag = "significant_neutral" if neutral else "significant"
        dsr_key = "dsr_neutral" if neutral else "dsr"
        significant = [f"{t['factor']} h={t['horizon']}" for t in tests if t.get(flag)]
        dsrs = [t.get(dsr_key) for t in tests if t.get(dsr_key) is not None]
        checks.append(
            Check(
                "Phase 2",
                "factor_significance",
                True,
                f"{len(significant)}/{len(tests)} {'category-neutral ' if neutral else ''}tests "
                f"significant at BH q={report.get('meta', {}).get('fdr_q')}",
                hard=False,
                evidence={
                    "m_tests": len(tests),
                    "metric": "neutral" if neutral else "raw",
                    "significant": significant,
                    "max_dsr": max(dsrs) if dsrs else None,
                },
            )
        )
    return checks


# --------------------------------------------------------------------- Phase 3
def check_signals_portfolio(
    universe,
    as_of,
    *,
    portfolio_path: str | Path | None = None,
    signals_path: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> list[Check]:
    as_of_s = pd.Timestamp(as_of).date().isoformat()
    portfolio_path = Path(portfolio_path or config.DATA_DIR / "portfolio" / f"{as_of_s}.json")
    signals_path = Path(signals_path or config.DATA_DIR / "signals" / f"{as_of_s}.json")
    checks: list[Check] = []

    if portfolio_path.exists():
        payload = json.loads(portfolio_path.read_text(encoding="utf-8"))
        holdings = payload.get("holdings", [])
        weights = pd.Series({h["symbol"]: float(h["weight"]) for h in holdings})
        breach = float(weights.max() - payload["policy"]["asset_cap"])
        checks.append(
            Check(
                "Phase 3",
                "portfolio_invariants",
                bool((weights >= 0).all()) and float(weights.sum()) <= 1.0 + 1e-6 and breach <= 1e-9,
                f"{len(weights)} holdings, sum={weights.sum():.6f}, max={weights.max():.4f}",
                evidence={"asset_cap": payload["policy"]["asset_cap"]},
            )
        )
        budget = payload["policy"]["category_budget"]
        exposure = payload.get("category_exposure", {})
        deviation = max((abs(float(exposure.get(k, 0.0)) - float(v)) for k, v in budget.items()), default=0.0)
        checks.append(
            Check(
                "Phase 3",
                "category_budget",
                deviation <= 0.005,
                f"max deviation from policy budget {deviation:.4f}",
                evidence={"exposure": exposure, "budget": budget},
            )
        )
        portfolio_vol = payload.get("portfolio_vol")
        weighted_vol = payload.get("weighted_vol")
        vol_ratio = weighted_vol / portfolio_vol if portfolio_vol else None
        checks.append(
            Check(
                "Phase 3",
                "diversification",
                True,
                f"portfolio vol {portfolio_vol:.2%} vs weighted {weighted_vol:.2%} "
                f"(diversification benefit {vol_ratio:.2f}x), n_eff={payload.get('diversification')}",
                hard=False,
                evidence={
                    "portfolio_vol": portfolio_vol,
                    "weighted_vol": weighted_vol,
                    "vol_ratio": round(vol_ratio, 4) if vol_ratio else None,
                    "n_eff": payload.get("diversification"),
                },
            )
        )
    else:
        checks.append(Check("Phase 3", "portfolio_invariants", False, f"missing {portfolio_path}"))

    if signals_path.exists():
        payload = json.loads(signals_path.read_text(encoding="utf-8"))
        signals = payload.get("signals", [])
        ids = [s["signal_id"] for s in signals]
        checks.append(
            Check(
                "Phase 3",
                "signal_schema",
                len(ids) == len(set(ids)) and all(not s.get("validated") for s in signals),
                f"{len(signals)} signals, {len(set(ids))} unique ids, all validated=false",
                evidence={"n_signals": len(signals)},
            )
        )
    else:
        checks.append(Check("Phase 3", "signal_schema", False, f"missing {signals_path}", hard=False))

    from finagent.predictions.ledger import PredictionLedger

    ledger = PredictionLedger(ledger_root)
    frame = ledger.load()
    settled = ledger.settlements()
    checks.append(
        Check(
            "Phase 3",
            "ledger_append_only",
            frame["signal_id"].is_unique if not frame.empty else True,
            f"{len(frame)} predictions, {len(settled)} settlements, "
            f"{frame['signal_id'].nunique() if not frame.empty else 0} unique ids",
            hard=False,
            evidence={"n_predictions": int(len(frame)), "n_settled": int(len(settled))},
        )
    )
    return checks


# --------------------------------------------------------------------- Phase 4
def check_backtest(results: dict[str, BacktestResult], panels: dict[str, pd.DataFrame]) -> list[Check]:
    close = panels["close"]
    valuation = close.ffill()
    checks: list[Check] = []
    for name, result in results.items():
        daily, fills = result.daily, result.fills
        filled = fills[fills["status"] == "filled"] if not fills.empty else fills
        cost_sum = float(filled["cost"].sum()) if not filled.empty else 0.0
        cost_metric = float(result.metrics.get("total_cost") or 0.0)
        checks.append(
            Check(
                "Phase 4",
                f"cost_identity[{name}]",
                abs(cost_sum - cost_metric) <= 1e-6,
                f"fills {cost_sum:.6f} vs metrics {cost_metric:.6f}",
            )
        )

        nav = daily["nav"]
        rets = nav.pct_change().dropna()
        consistent = np.allclose(rets.to_numpy(), daily["ret"].iloc[1:].to_numpy(), rtol=1e-9, atol=1e-12)
        checks.append(
            Check(
                "Phase 4",
                f"nav_returns[{name}]",
                consistent and abs(float(nav.iloc[0]) - 1.0) < 1e-12,
                f"first nav {nav.iloc[0]:.6f}, daily ret matches pct_change={consistent}",
            )
        )

        replayed = _replay_nav(fills, valuation, close.columns, daily.index)
        max_diff = float(np.nanmax(np.abs(replayed.to_numpy() - nav.to_numpy()))) if len(nav) else np.inf
        checks.append(
            Check(
                "Phase 4",
                f"nav_reconstruction[{name}]",
                max_diff <= 1e-9,
                f"cash + shares x close replays NAV, max |diff|={max_diff:.2e}",
                evidence={"max_abs_diff": max_diff},
            )
        )
    return checks


def check_pit_rerun(
    panels: dict[str, pd.DataFrame],
    strategy,
    cfg: BacktestConfig,
    cost: CostModel,
    cutoff,
) -> Check:
    """The full run and a run that stops at `cutoff` must agree up to `cutoff`."""
    if pd.Timestamp(cutoff) <= pd.Timestamp(cfg.start):
        return Check(
            "Phase 4",
            f"point_in_time[{strategy.name}]",
            True,
            "window too short for a point-in-time re-run",
            hard=False,
        )
    full = run_backtest(panels, strategy, cfg, cost)
    truncated = run_backtest(panels, strategy, replace(cfg, end=cutoff), cost)
    left = full.daily["nav"].loc[: pd.Timestamp(cutoff)]
    right = truncated.daily["nav"].reindex(left.index)
    diff = float(np.nanmax(np.abs(left.to_numpy() - right.to_numpy()))) if len(left) else np.inf
    return Check(
        "Phase 4",
        f"point_in_time[{strategy.name}]",
        len(left) > 0 and diff <= 1e-9,
        f"{len(left)} shared days to {pd.Timestamp(cutoff).date()}, max |NAV diff|={diff:.2e}",
        evidence={"cutoff": pd.Timestamp(cutoff).date().isoformat(), "max_abs_diff": diff},
    )


def _replay_nav(fills: pd.DataFrame, valuation: pd.DataFrame, symbols, dates) -> pd.Series:
    """Rebuild NAV from fills alone: cash plus shares marked at the close."""
    shares = pd.Series(0.0, index=symbols)
    cash = 1.0
    out = {}
    if fills is None or fills.empty:
        return pd.Series(1.0, index=dates)
    filled = fills[fills["status"] == "filled"].copy()
    if not filled.empty:
        filled["date"] = pd.to_datetime(filled["date"])
    grouped = {day: rows for day, rows in filled.groupby("date")} if not filled.empty else {}
    for day in dates:
        for row in grouped.get(day, pd.DataFrame()).itertuples(index=False):
            price = valuation.loc[day, row.symbol]
            if not np.isfinite(price) or price <= 0:
                continue
            quantity = float(row.notional) / float(price)
            if row.side == "buy":
                shares[row.symbol] += quantity
                cash -= float(row.notional) + float(row.cost)
            else:
                shares[row.symbol] -= quantity
                cash += float(row.notional) - float(row.cost)
        marks = valuation.loc[day].reindex(symbols).fillna(0.0)
        out[day] = cash + float((shares * marks).sum())
    return pd.Series(out, dtype=float)
