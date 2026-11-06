"""Central configuration: paths, thresholds, trading conventions.

Everything that another module might need to agree on lives here, so that a
data snapshot and a backtest run can be reproduced from the same config hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FINAGENT_DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
QUALITY_DIR = DATA_DIR / "quality"
FACTOR_DIR = DATA_DIR / "factors"
SIGNAL_DIR = DATA_DIR / "signals"
PREDICTION_DIR = DATA_DIR / "predictions"
REPORT_DIR = DATA_DIR / "reports"
PORTFOLIO_DIR = DATA_DIR / "portfolio"
CONFIG_DIR = PROJECT_ROOT / "configs"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

# A-share conventions
TRADING_DAYS_PER_YEAR = 252
CURRENCY = "CNY"
TIMEZONE = "Asia/Shanghai"

# Risk-free proxy used in Sharpe-style metrics (annualised).
DEFAULT_RISK_FREE_RATE = 0.03

# Trading frictions (per side, as a fraction of notional).
COMMISSION_RATE = 0.0002  # ETF commission, 2bp
SLIPPAGE_RATE = 0.0005  # 5bp
STAMP_DUTY_RATE = 0.0  # ETFs are exempt

# Signals are generated after close on day T and executed on T+1.
EXECUTION_LAG_DAYS = 1

# Data-quality gates.
MIN_DAYS_LISTED = 250
MIN_AVG_AMOUNT_60D = 50_000_000  # 5000万元
MAX_MISSING_RATIO = 0.05

# Publication lags for macro releases, in calendar days after the reference
# period ends. Overridable through configs/.
# Days between the end of the reference period and public availability.
MACRO_PUBLICATION_LAG_DAYS = {
    "pmi": 1,
    "cpi": 10,
    "ppi": 10,
    "m2": 15,
    "lpr": 0,  # LPR is published on the quote date itself
    "gdp": 20,
}


def ensure_dirs() -> None:
    for d in (
        CACHE_DIR,
        SNAPSHOT_DIR,
        QUALITY_DIR,
        FACTOR_DIR,
        SIGNAL_DIR,
        PREDICTION_DIR,
        REPORT_DIR,
        PORTFOLIO_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def today() -> date:
    return date.today()


@dataclass(frozen=True)
class RunConfig:
    """Immutable description of one run; hashed into snapshot lineage."""

    as_of: date
    universe_version: str = "u1"
    factor_config: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "as_of": self.as_of.isoformat(),
            "universe_version": self.universe_version,
            "factor_config": self.factor_config,
            "extras": self.extras,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
