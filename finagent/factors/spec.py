"""Factor specification and registry.

A factor is a pure function of a date x symbol matrix of prices. It must only
look backwards: `compute` receives data already sliced to `as_of`, and every
implementation uses shifts with non-positive offsets. Direction is metadata,
not a transformation — values stay raw so that IC keeps its natural sign; the
report multiplies by `direction` when it needs "higher is better".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FactorSpec:
    name: str
    group: str
    lookback: int
    direction: int  # +1: high value is attractive; -1: low value is attractive
    description: str
    compute: Callable[[pd.DataFrame], pd.DataFrame]

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError(f"{self.name}: direction must be +1 or -1")
        if self.lookback < 1:
            raise ValueError(f"{self.name}: lookback must be positive")
