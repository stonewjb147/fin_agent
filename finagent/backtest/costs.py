"""Trading cost model.

One number per side of a trade: commission + slippage (+ stamp duty, zero for
ETFs in A-shares). No market-impact term — with a 50-ETF pool trading small
notional, impact is not the binding friction, and inventing a coefficient would
make the cost look precise without being so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from finagent import config


@dataclass(frozen=True)
class CostModel:
    commission: float = config.COMMISSION_RATE
    slippage: float = config.SLIPPAGE_RATE
    stamp_duty: float = config.STAMP_DUTY_RATE

    def __post_init__(self) -> None:
        for name in ("commission", "slippage", "stamp_duty"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def one_way(self) -> float:
        """Cost of trading one unit of notional, as a fraction."""
        return self.commission + self.slippage + self.stamp_duty

    def cost(self, traded_notional: float) -> float:
        return abs(float(traded_notional)) * self.one_way

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["one_way_bps"] = round(self.one_way * 1e4, 4)
        return payload

    def fingerprint(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def cost_from_bps(total_bps: float, *, stamp_duty: float = config.STAMP_DUTY_RATE) -> CostModel:
    """Convenience for sensitivity runs: a single per-side cost in basis points."""
    if total_bps < 0:
        raise ValueError("total_bps cannot be negative")
    return CostModel(commission=total_bps / 1e4, slippage=0.0, stamp_duty=stamp_duty)


def zero_cost() -> CostModel:
    return CostModel(commission=0.0, slippage=0.0, stamp_duty=0.0)


DEFAULT_COST = CostModel()
