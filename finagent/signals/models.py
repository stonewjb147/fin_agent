"""Structured research signals.

A signal is a falsifiable statement: what we expect, on what evidence, for how
long, and what would prove it wrong. The narrative (`thesis`) is generated from
the same numbers as the evidence — there is no separate text channel that can
drift away from the computation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Evidence:
    """One factor's contribution to a signal, with the sign already aligned."""

    factor: str
    value: float
    z: float
    direction: int
    contribution: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "value": round(self.value, 8),
            "z": round(self.z, 6),
            "direction": self.direction,
            "contribution": round(self.contribution, 6),
        }


@dataclass(frozen=True)
class InvalidationRule:
    """A machine-checkable condition that would retire the signal."""

    kind: str
    condition: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "condition": self.condition, "params": self.params}


@dataclass(frozen=True)
class QuantSignal:
    as_of: date
    symbol: str
    name: str
    category: str
    direction: int  # +1 relative attractiveness, -1 relative weakness
    composite: float
    confidence: float
    horizon: int
    execution_lag: int
    evidence: tuple[Evidence, ...]
    invalidation: tuple[InvalidationRule, ...]
    thesis: str
    # Phase 2 found no factor surviving BH-FDR, so nothing here is claimed as
    # validated. The flag stays False until the backtest (Phase 4) earns it.
    validated: bool = False

    def __post_init__(self) -> None:
        if self.direction not in (-1, 1):
            raise ValueError(f"direction must be +1 or -1, got {self.direction}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.horizon < 1:
            raise ValueError(f"horizon must be >= 1, got {self.horizon}")

    @property
    def signal_id(self) -> str:
        """Stable id: identical inputs produce the identical id (ledger dedupe)."""
        payload = f"{self.as_of.isoformat()}|{self.symbol}|{self.horizon}|{self.direction}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "as_of": self.as_of.isoformat(),
            "symbol": self.symbol,
            "name": self.name,
            "category": self.category,
            "direction": self.direction,
            "composite": round(self.composite, 6),
            "confidence": round(self.confidence, 6),
            "horizon": self.horizon,
            "execution_lag": self.execution_lag,
            "validated": self.validated,
            "thesis": self.thesis,
            "evidence": [e.to_dict() for e in self.evidence],
            "invalidation": [r.to_dict() for r in self.invalidation],
        }

    def to_record(self) -> dict[str, Any]:
        """Flat form for the prediction ledger (JSONL friendly)."""
        return {
            "signal_id": self.signal_id,
            "as_of": self.as_of.isoformat(),
            "symbol": self.symbol,
            "name": self.name,
            "category": self.category,
            "direction": self.direction,
            "horizon": self.horizon,
            "execution_lag": self.execution_lag,
            "composite": round(self.composite, 6),
            "confidence": round(self.confidence, 6),
            "n_factors": len(self.evidence),
            "evidence_json": json.dumps(
                [e.to_dict() for e in self.evidence], ensure_ascii=False, sort_keys=True
            ),
            "thesis": self.thesis,
        }
