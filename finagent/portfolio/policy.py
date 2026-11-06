"""Portfolio policy: category budgets, caps and tilt strength.

This is the Phase 3 stand-in for an IPS. Everything that shapes the weights
lives in one frozen object with a fingerprint, so a weight file can always be
traced back to the rules that produced it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Strategic budgets. They sum to 1.0 and sit inside the category guardrails in
# finagent.data.universe.DEFAULT_CATEGORY_CAPS.
DEFAULT_CATEGORY_BUDGET: dict[str, float] = {
    "broad": 0.35,
    "sector": 0.25,
    "thematic": 0.10,
    "cross_border": 0.15,
    "commodity": 0.05,
    "bond": 0.10,
}


@dataclass(frozen=True)
class PortfolioPolicy:
    name: str = "rp-tilt-v1"
    category_budget: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_BUDGET)
    )
    asset_cap: float = 0.12
    min_weight: float = 0.002
    tilt_strength: float = 0.15
    tilt_floor: float = 0.5
    tilt_ceiling: float = 1.5
    vol_window: int = 60
    cov_window: int = 120

    def __post_init__(self) -> None:
        total = sum(self.category_budget.values())
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"category budgets must sum to 1.0, got {total:.4f}")
        if not 0.0 < self.asset_cap <= 1.0:
            raise ValueError("asset_cap must be in (0, 1]")
        if self.tilt_floor > 1.0 or self.tilt_ceiling < 1.0:
            raise ValueError("tilt bounds must straddle 1.0")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        blob = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def load_policy(path: str | Path | None = None) -> PortfolioPolicy:
    """Defaults, with optional overrides from a YAML file."""
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / "configs" / "policy.yaml"
    path = Path(path)
    if not path.exists():
        return PortfolioPolicy()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    payload.pop("comment", None)
    return PortfolioPolicy(**payload)
