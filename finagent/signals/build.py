"""Turn one day's composite scores into structured, falsifiable signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd

from finagent import config
from finagent.data.panel import as_date
from finagent.factors import get_factor
from finagent.signals.models import Evidence, InvalidationRule, QuantSignal
from finagent.signals.score import DEFAULT_WEIGHTS

# Below these thresholds a ranking is too weak to write down as a view.
MIN_COMPOSITE = 0.25
MIN_CONFIDENCE = 0.50


def _evidence_for(
    factors: pd.DataFrame,
    as_of: pd.Timestamp,
    symbol: str,
    weights: Mapping[str, float],
) -> tuple[Evidence, ...]:
    rows = factors[(factors["date"] == as_of) & (factors["symbol"] == symbol)]
    evidence = []
    for row in rows.itertuples(index=False):
        spec = get_factor(row.factor)
        weight = float(weights.get(row.factor, 0.0))
        if weight == 0:
            continue
        aligned = float(row.z_cs) * spec.direction
        evidence.append(
            Evidence(
                factor=row.factor,
                value=float(row.value),
                z=float(row.z_cs),
                direction=spec.direction,
                contribution=aligned * weight,
            )
        )
    return tuple(sorted(evidence, key=lambda e: -abs(e.contribution)))


def _thesis(
    direction: int,
    composite: float,
    confidence: float,
    horizon: int,
    evidence: Sequence[Evidence],
) -> str:
    parts = "、".join(f"{e.factor} {e.contribution:+.2f}" for e in evidence)
    stance = "相对看好" if direction > 0 else "相对看淡"
    return (
        f"{horizon} 日窗口内{stance}：{parts}（方向已对齐）；"
        f"合成得分 {composite:+.2f}，因子同向度 {confidence:.0%}"
    )


def _invalidation(direction: int, composite: float, horizon: int, evidence: Sequence[Evidence]) -> tuple[InvalidationRule, ...]:
    rules = [
        InvalidationRule(
            kind="score_flip",
            condition=(
                "合成得分 <= 0（多空观点翻转）" if direction > 0 else "合成得分 >= 0（多空观点翻转）"
            ),
            params={"composite": composite, "direction": direction},
        ),
        InvalidationRule(
            kind="horizon_elapsed",
            condition=f"持有到期：{horizon} 个交易日后自动结算",
            params={"horizon": horizon},
        ),
    ]
    if evidence:
        dominant = max(evidence, key=lambda e: abs(e.contribution))
        rules.append(
            InvalidationRule(
                kind="factor_flip",
                condition=f"主贡献因子 {dominant.factor} 按方向对齐后翻转到与信号相反一侧",
                params={
                    "factor": dominant.factor,
                    "direction": dominant.direction * direction,
                    "contribution": dominant.contribution,
                },
            )
        )
    return tuple(rules)


def build_signals(
    scores: pd.DataFrame,
    universe,
    as_of: date | str,
    *,
    factors: pd.DataFrame | None = None,
    weights: Mapping[str, float] | None = None,
    horizon: int = 20,
    n_long: int = 10,
    n_short: int = 5,
    min_composite: float = MIN_COMPOSITE,
    min_confidence: float = MIN_CONFIDENCE,
    max_per_category: int = 3,
    execution_lag: int = config.EXECUTION_LAG_DAYS,
) -> list[QuantSignal]:
    """Select the strongest views for one date, long side and short side.

    A symbol must clear both the score and the agreement threshold. If nothing
    clears it, the correct output is an empty list — not a weaker signal.

    `max_per_category` keeps one risk bucket from filling the whole list. The
    raw score is dominated by structural volatility differences (bonds always
    score well on the volatility factor), so without the cap the table would
    be four bond ETFs and little else.
    """
    as_of = as_date(as_of)
    day = pd.Timestamp(as_of)
    weights = dict(weights or DEFAULT_WEIGHTS)
    meta = universe.by_symbol()
    row = scores[scores["date"] == day]
    if row.empty:
        raise ValueError(f"no composite scores on {as_of}")
    row = row.set_index("symbol")

    def _make(symbol: str, direction: int) -> QuantSignal:
        rec = row.loc[symbol]
        evidence = (
            _evidence_for(factors, day, symbol, weights) if factors is not None else ()
        )
        composite = float(rec["composite"])
        confidence = float(rec["confidence"])
        etf = meta.get(symbol)
        return QuantSignal(
            as_of=as_of,
            symbol=symbol,
            name=etf.name if etf else symbol,
            category=etf.category if etf else "unknown",
            direction=direction,
            composite=composite,
            confidence=confidence,
            horizon=horizon,
            execution_lag=execution_lag,
            evidence=evidence,
            invalidation=_invalidation(direction, composite, horizon, evidence),
            thesis=_thesis(direction, composite, confidence, horizon, evidence),
        )

    eligible = row[row["confidence"] >= min_confidence]

    def _pick(frame: pd.DataFrame, limit: int) -> list[str]:
        seen: dict[str, int] = {}
        picked: list[str] = []
        for symbol in frame.index:
            etf = meta.get(symbol)
            category = etf.category if etf else "unknown"
            if max_per_category and seen.get(category, 0) >= max_per_category:
                continue
            seen[category] = seen.get(category, 0) + 1
            picked.append(symbol)
            if len(picked) >= limit:
                break
        return picked

    long_symbols = _pick(
        eligible[eligible["composite"] >= min_composite].sort_values("composite", ascending=False),
        n_long,
    )
    short_symbols = _pick(
        eligible[eligible["composite"] <= -min_composite].sort_values("composite"), n_short
    )

    signals = [_make(s, 1) for s in long_symbols]
    signals += [_make(s, -1) for s in short_symbols]
    return signals
