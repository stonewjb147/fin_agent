"""Factor definitions and panel construction.

Adding a factor means writing a pure function of the close matrix, wrapping it
in a FactorSpec, and registering it here. Nothing else needs to change: the
report, the CLI and the tests all iterate over the registry.
"""

from __future__ import annotations

from finagent.factors.build import (
    assert_pit,
    build_factor_panel,
    factor_wide,
    load_close_panel,
    load_price_frame,
)
from finagent.factors.price import PRICE_FACTORS
from finagent.factors.spec import FactorSpec
from finagent.factors.transforms import neutralize_cs, rank_cs, winsorize_cs, zscore_cs

FACTORS: dict[str, FactorSpec] = {**PRICE_FACTORS}

# Factors evaluated by default, in report order.
DEFAULT_FACTORS: tuple[str, ...] = ("momentum_20", "reversal_5", "volatility_20")


def get_factor(name: str) -> FactorSpec:
    try:
        return FACTORS[name]
    except KeyError:
        available = ", ".join(sorted(FACTORS))
        raise KeyError(f"unknown factor {name!r}; available: {available}") from None


__all__ = [
    "DEFAULT_FACTORS",
    "FACTORS",
    "FactorSpec",
    "assert_pit",
    "build_factor_panel",
    "factor_wide",
    "get_factor",
    "load_close_panel",
    "load_price_frame",
    "neutralize_cs",
    "rank_cs",
    "winsorize_cs",
    "zscore_cs",
]
