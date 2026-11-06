"""Cross-sectional composite score: weighted, direction-aligned factor z-scores.

The score is deliberately simple. With three price factors and no factor that
survives multiple-testing correction, anything fancier would be fitting noise.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from finagent.factors import DEFAULT_FACTORS, get_factor

# Equal weight until the backtest gives a reason to do otherwise.
DEFAULT_WEIGHTS: dict[str, float] = {name: 1.0 for name in DEFAULT_FACTORS}


def composite_scores(
    factors: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
    *,
    min_factors: int = 2,
) -> pd.DataFrame:
    """Collapse factor z-scores into one score per (date, symbol).

    `factors` is the long panel from `factor_snapshot` (date, symbol, factor,
    value, rank_cs, z_cs). Each factor's z is multiplied by its own direction so
    that "higher is more attractive" holds for all of them before averaging.

    Returns long frame: date, symbol, composite, confidence, n_factors.
    `confidence` is |weighted sum| / weighted sum of |z| — a measure of how much
    the factors agree, not a calibrated probability.
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    if factors.empty:
        return pd.DataFrame(columns=["date", "symbol", "composite", "confidence", "n_factors"])

    num: pd.DataFrame | None = None
    den: pd.DataFrame | None = None
    weight_sum: pd.DataFrame | None = None
    count: pd.DataFrame | None = None

    for name, weight in weights.items():
        if weight == 0:
            continue
        subset = factors[factors["factor"] == name]
        if subset.empty:
            continue
        spec = get_factor(name)
        z = subset.pivot(index="date", columns="symbol", values="z_cs").sort_index()
        aligned = z * spec.direction

        contrib = aligned * weight
        abs_contrib = aligned.abs() * weight
        present = z.notna()

        num = contrib if num is None else num.add(contrib, fill_value=0.0)
        den = abs_contrib if den is None else den.add(abs_contrib, fill_value=0.0)
        w = present.astype(float) * weight
        weight_sum = w if weight_sum is None else weight_sum.add(w, fill_value=0.0)
        c = present.astype(int)
        count = c if count is None else count.add(c, fill_value=0)

    if num is None or den is None or weight_sum is None or count is None:
        return pd.DataFrame(columns=["date", "symbol", "composite", "confidence", "n_factors"])

    index = num.index.intersection(den.index)
    columns = num.columns.intersection(den.columns)
    num, den = num.reindex(index=index, columns=columns), den.reindex(index=index, columns=columns)
    weight_sum = weight_sum.reindex(index=index, columns=columns)
    count = count.reindex(index=index, columns=columns)

    composite = (num / weight_sum.replace(0.0, np.nan)).astype(float)
    confidence = (num.abs() / den.replace(0.0, np.nan)).fillna(0.0).astype(float)
    n_factors = count.fillna(0).astype(int)

    out = pd.concat(
        {
            "composite": composite.stack(),
            "confidence": confidence.stack(),
            "n_factors": n_factors.stack(),
        },
        axis=1,
    ).reset_index()
    out.columns = ["date", "symbol", "composite", "confidence", "n_factors"]
    out = out.dropna(subset=["composite"])
    out = out[out["n_factors"] >= min_factors]
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def score_row(scores: pd.DataFrame, as_of) -> pd.DataFrame:
    """The cross-section for one date, indexed by symbol."""
    if scores.empty:
        raise ValueError("no composite scores available")
    day = pd.Timestamp(as_of)
    row = scores[scores["date"] == day]
    if row.empty:
        latest = pd.Timestamp(scores["date"].max()).date()
        raise ValueError(f"no composite scores on {pd.Timestamp(as_of).date()}; latest is {latest}")
    return row.set_index("symbol").sort_index()
