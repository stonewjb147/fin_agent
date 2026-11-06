"""Risk limits: the machine-readable part of an IPS.

A limit is either hard, soft or informational:

- hard: a breach blocks the report from presenting a normal conclusion;
- soft: a breach is a warning, recorded but not blocking;
- info: context only, never changes the status.

The defaults are deliberately conservative for a long-only ETF book. Override
them in `configs/risk.yaml`; the policy fingerprint is written next to every
risk report so a verdict can be traced back to the limits that produced it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from finagent.data.universe import DEFAULT_CATEGORY_CAPS


@dataclass(frozen=True)
class RiskPolicy:
    name: str = "risk-v1"

    # Position and concentration limits.
    max_asset_weight: float = 0.12
    max_top5_weight: float = 0.40
    min_n_eff: float = 3.0
    max_avg_corr: float = 0.60

    # Portfolio-level risk budget.
    max_portfolio_vol: float = 0.18
    max_drawdown: float = 0.20  # magnitude, compared with abs(max_drawdown)

    # Liquidity and data quality.
    min_avg_amount_60d: float = 50_000_000  # 5000万元
    max_health_errors: int = 0
    max_health_warnings: int = 0
    max_category_budget_drift: float = 0.03

    # Conditions for ever flipping validated=false. See validation.py.
    min_settled_samples: int = 385
    min_hit_rate_excess: float = 0.55
    min_factor_significant: int = 1

    category_caps: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_CAPS)
    )

    def __post_init__(self) -> None:
        for name in (
            "max_asset_weight",
            "max_top5_weight",
            "max_portfolio_vol",
            "max_drawdown",
            "max_category_budget_drift",
        ):
            value = float(getattr(self, name))
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")
        if self.min_avg_amount_60d < 0:
            raise ValueError("min_avg_amount_60d must be non-negative")
        if not 0.0 <= self.min_hit_rate_excess <= 1.0:
            raise ValueError("min_hit_rate_excess must be in [0, 1]")
        if self.min_settled_samples < 1:
            raise ValueError("min_settled_samples must be positive")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        blob = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def load_risk_policy(path: str | Path | None = None) -> RiskPolicy:
    """Defaults with optional YAML overrides."""
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / "configs" / "risk.yaml"
    path = Path(path)
    if not path.exists():
        return RiskPolicy()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    payload.pop("comment", None)
    allowed = set(RiskPolicy.__dataclass_fields__)
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown risk policy keys: {sorted(unknown)}")
    return RiskPolicy(**payload)
