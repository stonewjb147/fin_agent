"""Long-only target weights: strategic budgets, inverse-vol base, score tilt.

The construction is deliberately transparent:

1. each category gets its strategic budget;
2. inside a category, weight is proportional to 1/volatility;
3. the composite score multiplies that weight by a bounded factor;
4. per-asset and per-category caps are enforced by water-filling.

No optimiser is involved, so every weight can be explained in one sentence.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from finagent import config
from finagent.data.panel import as_date, to_returns
from finagent.data.universe import DEFAULT_CATEGORY_CAPS
from finagent.portfolio.covariance import ledoit_wolf, portfolio_vol
from finagent.portfolio.policy import PortfolioPolicy


def trailing_vols(close: pd.DataFrame, window: int = 60) -> pd.Series:
    """Annualised volatility from the last `window` daily returns."""
    returns = to_returns(close)
    if len(returns) < 2:
        return pd.Series(dtype=float)
    return returns.tail(window).std(ddof=1) * np.sqrt(config.TRADING_DAYS_PER_YEAR)


def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    vols = vols.replace(0.0, np.nan).dropna()
    if vols.empty:
        return pd.Series(dtype=float)
    inverse = 1.0 / vols
    return inverse / inverse.sum()


def tilt_multipliers(
    scores: pd.Series,
    *,
    strength: float,
    floor: float,
    ceiling: float,
) -> pd.Series:
    adjusted = 1.0 + strength * scores.fillna(0.0)
    return adjusted.clip(lower=floor, upper=ceiling)


def apply_asset_cap(weights: pd.Series, cap: float, max_iter: int = 100) -> pd.Series:
    """Cap single weights and redistribute the excess proportionally."""
    w = weights.astype(float).copy()
    if w.empty:
        return w
    if len(w) * cap < 1.0 - 1e-9:
        raise ValueError(f"asset cap {cap} is infeasible for {len(w)} holdings")
    for _ in range(max_iter):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = ~over
        if not free.any():
            break
        w[free] += excess * w[free] / float(w[free].sum())
    return w


def apply_category_caps(
    weights: pd.Series,
    categories: pd.Series,
    caps: dict[str, float] = DEFAULT_CATEGORY_CAPS,
    max_iter: int = 50,
) -> pd.Series:
    groups = categories.reindex(weights.index).fillna("unknown")
    w = weights.astype(float).copy()
    for _ in range(max_iter):
        exposure = w.groupby(groups).sum()
        limits = pd.Series(
            [float(caps.get(str(cat), 1.0)) + 1e-12 for cat in exposure.index],
            index=exposure.index,
        )
        over = exposure[exposure > limits] if len(exposure) else exposure
        if over.empty:
            break
        excess = 0.0
        for category, value in over.items():
            members = groups[groups == category].index
            w[members] *= float(caps.get(category, 1.0)) / float(value)
            excess += float(value) - float(caps.get(category, 1.0))
        remaining = w[~w.index.isin(groups[groups.isin(over.index)].index)]
        if remaining.empty or float(remaining.sum()) <= 0:
            break
        w[remaining.index] += excess * remaining / float(remaining.sum())
    return w


def target_weights(
    symbols: Iterable[str],
    categories: pd.Series,
    vols: pd.Series,
    scores: pd.Series,
    policy: PortfolioPolicy,
) -> pd.Series:
    """Strategic budgets + inverse vol + bounded score tilt, then caps."""
    symbols = [s for s in symbols if s in vols.index and pd.notna(vols.get(s)) and vols.get(s) > 0]
    if not symbols:
        raise ValueError("no symbol has a usable volatility estimate")
    categories = categories.reindex(symbols)
    vols = vols.reindex(symbols)

    present = [c for c in categories.unique() if policy.category_budget.get(c, 0.0) > 0]
    budget_total = sum(policy.category_budget[c] for c in present)
    if budget_total <= 0:
        raise ValueError("no category with a positive budget has any eligible symbol")

    parts = []
    for category in present:
        members = categories[categories == category].index
        if len(members) == 0:
            continue
        budget = policy.category_budget[category] / budget_total
        base = inverse_vol_weights(vols[members])
        multiplier = tilt_multipliers(
            scores.reindex(members),
            strength=policy.tilt_strength,
            floor=policy.tilt_floor,
            ceiling=policy.tilt_ceiling,
        )
        tilted = base * multiplier
        if float(tilted.sum()) <= 0:
            tilted = base
        parts.append(tilted / float(tilted.sum()) * budget)

    weights = pd.concat(parts) if parts else pd.Series(dtype=float)
    weights = apply_asset_cap(weights, policy.asset_cap)
    weights = weights[weights >= policy.min_weight]
    if weights.empty:
        raise ValueError("every weight fell below the minimum after capping")
    weights = weights / float(weights.sum())
    weights = apply_asset_cap(weights, policy.asset_cap)
    weights = apply_category_caps(weights, categories)
    return weights.sort_values(ascending=False)


def build_portfolio(
    close: pd.DataFrame,
    universe,
    as_of,
    scores: pd.DataFrame,
    policy: PortfolioPolicy | None = None,
) -> dict:
    """Weights plus the risk numbers needed to judge them."""
    as_of = as_date(as_of)
    policy = policy or PortfolioPolicy()
    names = {e.symbol: e for e in universe.for_date(as_of)}
    symbols = [s for s in universe.symbols(as_of) if s in close.columns]
    if not symbols:
        raise ValueError(f"no universe symbol has cached prices as of {as_of}")

    vols = trailing_vols(close[symbols], policy.vol_window).dropna()
    day = pd.Timestamp(as_of)
    if scores.empty:
        score_day = pd.Series(dtype=float)
    else:
        score_day = scores[scores["date"] == day].set_index("symbol")["composite"]

    categories = universe.groups(as_of)
    weights = target_weights(symbols, categories, vols, score_day, policy)

    returns = to_returns(close[list(weights.index)]).tail(policy.cov_window)
    cov = ledoit_wolf(returns)
    vol = portfolio_vol(weights, cov)
    weighted_vol = float((weights * vols.reindex(weights.index)).sum())
    n_eff = float(1.0 / (weights**2).sum())
    exposure = weights.groupby(categories.reindex(weights.index)).sum().sort_values(ascending=False)

    holdings = []
    for symbol, weight in weights.items():
        etf = names.get(symbol)
        holdings.append(
            {
                "symbol": symbol,
                "name": etf.name if etf else symbol,
                "category": etf.category if etf else "unknown",
                "weight": round(float(weight), 6),
                "vol": round(float(vols[symbol]), 6),
                "composite": round(float(score_day.get(symbol, float("nan"))), 4)
                if symbol in score_day.index
                else None,
                "tilt": round(
                    float(
                        tilt_multipliers(
                            score_day.reindex([symbol]),
                            strength=policy.tilt_strength,
                            floor=policy.tilt_floor,
                            ceiling=policy.tilt_ceiling,
                        ).iloc[0]
                    ),
                    4,
                ),
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "universe_version": universe.version,
        "policy": policy.as_dict(),
        "policy_fingerprint": policy.fingerprint(),
        "n_symbols": len(symbols),
        "n_holdings": int(len(weights)),
        "portfolio_vol": round(vol, 6),
        "weighted_vol": round(weighted_vol, 6),
        "diversification": round(n_eff, 3),
        "category_exposure": {str(k): round(float(v), 6) for k, v in exposure.items()},
        "holdings": holdings,
        "notes": (
            "Long-only. Strategic budgets are fixed; the factor tilt is bounded to "
            "[floor, ceiling] so an unvalidated score cannot dominate the portfolio. "
            "A name that falls below min_weight is dropped and its weight is spread "
            "pro rata across the book, so a category can close slightly under budget. "
            "Costs and execution are not modelled here — that is Phase 4."
        ),
    }


def format_portfolio(result: dict, top: int = 15) -> str:
    lines = [
        f"Portfolio {result['as_of']}  holdings={result['n_holdings']}/{result['n_symbols']}  "
        f"vol={result['portfolio_vol']:.1%} (weighted avg {result['weighted_vol']:.1%})  "
        f"n_eff={result['diversification']:.1f}  policy={result['policy']['name']}",
        "",
        f"{'SYMBOL':8s} {'NAME':16s} {'CATEGORY':12s} {'WEIGHT':>7s} {'VOL':>6s} {'SCORE':>6s}",
    ]
    for holding in result["holdings"][:top]:
        score = f"{holding['composite']:6.2f}" if holding["composite"] is not None else "   n/a"
        lines.append(
            f"{holding['symbol']:8s} {holding['name'][:16]:16s} {holding['category']:12s} "
            f"{holding['weight']:7.2%} {holding['vol']:6.1%} {score}"
        )
    exposure = "  ".join(f"{k} {v:.1%}" for k, v in result["category_exposure"].items())
    lines.append(f"\ncategory exposure: {exposure}")
    return "\n".join(lines)
