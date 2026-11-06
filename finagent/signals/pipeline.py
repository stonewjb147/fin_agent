"""End-to-end daily signal run: scores -> signals -> ledger -> settlements."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.data.panel import as_date
from finagent.factors import DEFAULT_FACTORS, load_close_panel
from finagent.predictions.ledger import PredictionLedger, record_settlement
from finagent.research.report import MIN_SYMBOLS, factor_snapshot
from finagent.signals.build import MIN_COMPOSITE, MIN_CONFIDENCE, build_signals
from finagent.signals.score import DEFAULT_WEIGHTS, composite_scores


def run_signal_pipeline(
    universe,
    *,
    as_of: date | str,
    cache_dir: str | Path | None = None,
    factor_names=None,
    weights: dict[str, float] | None = None,
    horizon: int = 20,
    n_long: int = 10,
    n_short: int = 5,
    min_composite: float = MIN_COMPOSITE,
    min_confidence: float = MIN_CONFIDENCE,
    execution_lag: int = config.EXECUTION_LAG_DAYS,
    write: bool = True,
    out_dir: str | Path | None = None,
    ledger: PredictionLedger | None = None,
) -> dict:
    """Generate one day's signals and settle whatever has matured."""
    as_of = as_date(as_of)
    names = list(factor_names or DEFAULT_FACTORS)
    weights = dict(weights or DEFAULT_WEIGHTS)
    cache_dir = Path(cache_dir or config.CACHE_DIR)

    close = load_close_panel(cache_dir, universe.symbols(as_of), as_of)
    factors = factor_snapshot(close, names, min_obs=MIN_SYMBOLS)
    if factors.empty:
        raise ValueError(f"no factor values could be computed as of {as_of}")
    scores = composite_scores(factors, weights)
    signals = build_signals(
        scores,
        universe,
        as_of,
        factors=factors,
        weights=weights,
        horizon=horizon,
        n_long=n_long,
        n_short=n_short,
        min_composite=min_composite,
        min_confidence=min_confidence,
        execution_lag=execution_lag,
    )

    ledger = ledger or PredictionLedger()
    n_appended = ledger.append(signal.to_record() for signal in signals) if write else 0
    new_settlements = (
        ledger.settle(close, as_of, symbols=universe.symbols(as_of)) if write else None
    )
    summary = ledger.summary(as_of) if write else {}

    result = {
        "as_of": as_of.isoformat(),
        "universe_version": universe.version,
        "n_symbols": int(close.shape[1]),
        "n_scored": int(len(scores[scores["date"] == pd.Timestamp(as_of)])),
        "horizon": horizon,
        "execution_lag": execution_lag,
        "weights": weights,
        "n_signals": len(signals),
        "n_ledger_appended": n_appended,
        "settlement": record_settlement(new_settlements) if new_settlements is not None else {},
        "ledger_summary": summary,
        "signals": [s.to_dict() for s in signals],
    }

    if write:
        out_dir = Path(out_dir or config.SIGNAL_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{as_of.isoformat()}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["signal_file"] = str(path)
    return result


def format_signals(result: dict) -> str:
    """Terminal table: direction, score, agreement, and the top evidence."""
    lines = [
        f"Signals {result['as_of']}  symbols={result['n_symbols']}  "
        f"scored={result['n_scored']}  horizon={result['horizon']}d  "
        f"universe={result['universe_version']}",
        "",
        f"{'SIDE':4s} {'SYMBOL':8s} {'NAME':16s} {'CATEGORY':12s} "
        f"{'SCORE':>6s} {'CONF':>5s}  EVIDENCE",
    ]
    for sig in result["signals"]:
        evidence = ", ".join(f"{e['factor']} {e['contribution']:+.2f}" for e in sig["evidence"])
        lines.append(
            f"{'LONG' if sig['direction'] > 0 else 'SHORT':4s} {sig['symbol']:8s} "
            f"{sig['name'][:16]:16s} {sig['category']:12s} "
            f"{sig['composite']:6.2f} {sig['confidence']:5.2f}  {evidence}"
        )
    settlement = result.get("settlement") or {}
    if settlement.get("n_new"):
        hit = settlement.get("hit_rate_excess")
        hit_text = f"{hit:.1%}" if hit is not None else "n/a"
        lines.append(f"\nsettled {settlement['n_new']} matured prediction(s), excess hit rate {hit_text}")
    lines.append(
        "\nNote: signals are research output only. No factor passed BH-FDR in Phase 2, "
        "so every signal is marked validated=false."
    )
    return "\n".join(lines)
