"""The strategies Phase 4 compares.

They are deliberately few and nested, so that the backtest answers three
questions in order:

1. `equal_weight`  — what does the universe itself return?
2. `policy_no_tilt` — what do category budgets + inverse vol add?
3. `policy_tilt`   — does the factor score add anything on top of that?
4. `top_n`         — does the score work at all when used on its own?

Everybody sees exactly the same data: closes up to and including `as_of` and a
score panel computed only from those closes. No strategy gets a parameter tuned
on the period it is scored on; that is what the CPCV/PBO diagnostics are for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from finagent.data.panel import as_date
from finagent.portfolio.construct import target_weights, trailing_vols
from finagent.portfolio.policy import PortfolioPolicy


def score_as_of(scores: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Composite score for the latest date at or before `as_of`."""
    if scores.empty:
        return pd.Series(dtype=float)
    usable = scores[scores["date"] <= pd.Timestamp(as_of)]
    if usable.empty:
        return pd.Series(dtype=float)
    latest = usable["date"].max()
    return usable.loc[usable["date"] == latest].set_index("symbol")["composite"]


@dataclass
class PolicyStrategy:
    """The Phase 3 policy portfolio, optionally without the score tilt."""

    universe: object
    scores: pd.DataFrame
    policy: PortfolioPolicy
    tilt: bool = True
    name: str = "policy_tilt"

    def target_weights(self, as_of: pd.Timestamp, close_upto: pd.DataFrame) -> pd.Series:
        day = as_date(as_of)
        symbols = [s for s in self.universe.symbols(day) if s in close_upto.columns]
        if not symbols:
            return pd.Series(dtype=float)
        vols = trailing_vols(close_upto[symbols], self.policy.vol_window).dropna()
        scores = score_as_of(self.scores, as_of) if self.tilt else pd.Series(dtype=float)
        weights = target_weights(symbols, self.universe.groups(day), vols, scores, self.policy)
        return weights


@dataclass
class EqualWeightStrategy:
    """1/N over every universe member that has a price on the day."""

    universe: object
    name: str = "equal_weight"

    def target_weights(self, as_of: pd.Timestamp, close_upto: pd.DataFrame) -> pd.Series:
        day = as_date(as_of)
        last = close_upto.iloc[-1]
        symbols = [s for s in self.universe.symbols(day) if s in last.index and pd.notna(last.get(s))]
        if not symbols:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(symbols), index=symbols)


@dataclass
class TopNStrategy:
    """Equal weight the N best composite scores; a direct test of the signal."""

    universe: object
    scores: pd.DataFrame
    n: int = 10
    name: str = "top_n"

    def target_weights(self, as_of: pd.Timestamp, close_upto: pd.DataFrame) -> pd.Series:
        day = as_date(as_of)
        last = close_upto.iloc[-1]
        eligible = [s for s in self.universe.symbols(day) if s in last.index and pd.notna(last.get(s))]
        scores = score_as_of(self.scores, as_of).reindex(eligible).dropna()
        if scores.empty:
            return pd.Series(dtype=float)
        chosen = scores.sort_values(ascending=False).head(self.n)
        return pd.Series(1.0 / len(chosen), index=chosen.index)


def default_strategies(
    universe,
    scores: pd.DataFrame,
    policy: PortfolioPolicy | None = None,
    *,
    top_n: int = 10,
) -> dict:
    policy = policy or PortfolioPolicy()
    return {
        "equal_weight": EqualWeightStrategy(universe=universe),
        "policy_no_tilt": PolicyStrategy(
            universe=universe, scores=scores, policy=policy, tilt=False, name="policy_no_tilt"
        ),
        "policy_tilt": PolicyStrategy(universe=universe, scores=scores, policy=policy, tilt=True),
        f"top_{top_n}": TopNStrategy(universe=universe, scores=scores, n=top_n, name=f"top_{top_n}"),
    }


def weights_frame(result_weights: dict[str, pd.Series]) -> pd.DataFrame:
    """Stack per-date weight vectors into one frame (handy for tests and CSVs)."""
    if not result_weights:
        return pd.DataFrame()
    frame = pd.DataFrame(result_weights).T
    return frame.fillna(0.0).astype(float).where(np.abs(frame) > 0, 0.0)
