"""ETF universe: categories, tracked indices, effective periods.

Tracking-index mapping has no authoritative free field, so it is maintained by
hand in configs/universe.yaml and validated against price correlation. The
`effective_from/effective_to` fields let historical queries drop ETFs that did
not exist yet, which limits (but cannot remove) survivorship bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

CATEGORIES = ("broad", "sector", "thematic", "bond", "cross_border", "commodity")

# Category-level guardrails used by scoring and portfolio construction.
DEFAULT_CATEGORY_CAPS = {
    "broad": 1.0,
    "sector": 0.40,
    "thematic": 0.30,
    "bond": 0.60,
    "cross_border": 0.30,
    "commodity": 0.20,
}


@dataclass(frozen=True)
class ETF:
    symbol: str
    name: str
    category: str
    tracked_index: str | None = None
    sector: str | None = None
    eastmoney_sector: str | None = None
    flow_sectors: tuple[str, ...] = ()
    index_data: bool = True  # free sources publish no usable daily series for some indices
    effective_from: date | None = None
    effective_to: date | None = None
    benchmark: bool = False

    def active_on(self, as_of: date) -> bool:
        if self.effective_from and as_of < self.effective_from:
            return False
        if self.effective_to and as_of > self.effective_to:
            return False
        return True


@dataclass
class Universe:
    version: str
    etfs: list[ETF]
    path: Path | None = None
    metadata: dict = field(default_factory=dict)

    def for_date(self, as_of: date) -> list[ETF]:
        return [e for e in self.etfs if e.active_on(as_of)]

    def symbols(self, as_of: date | None = None) -> list[str]:
        entries = self.etfs if as_of is None else self.for_date(as_of)
        return [e.symbol for e in entries]

    def by_symbol(self) -> dict[str, ETF]:
        return {e.symbol: e for e in self.etfs}

    def groups(self, as_of: date | None = None) -> pd.Series:
        entries = self.etfs if as_of is None else self.for_date(as_of)
        return pd.Series({e.symbol: e.category for e in entries}, name="category")

    def benchmark_symbols(self) -> list[str]:
        return [e.symbol for e in self.etfs if e.benchmark]

    def validate(self) -> list[str]:
        """Structural checks; returns a list of problems (empty = OK)."""
        problems: list[str] = []
        seen: set[str] = set()
        for e in self.etfs:
            if e.category not in CATEGORIES:
                problems.append(f"{e.symbol}: unknown category {e.category!r}")
            if e.symbol in seen:
                problems.append(f"duplicate symbol {e.symbol}")
            seen.add(e.symbol)
            # Cross-border and theme ETFs often have no index code we can
            # source reliably; they set index_data: false and are exempt.
            if e.index_data and not e.tracked_index:
                problems.append(f"{e.symbol}: missing tracked_index")
        if not any(e.benchmark for e in self.etfs):
            problems.append("no benchmark ETF declared")
        return problems


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_universe(path: str | Path) -> Universe:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    etfs = []
    for row in payload.get("etfs", []):
        missing = {"symbol", "name", "category"} - set(row)
        if missing:
            raise ValueError(f"universe entry missing {sorted(missing)}: {row}")
        etfs.append(
            ETF(
                symbol=str(row["symbol"]).zfill(6),
                name=row["name"],
                category=row["category"],
                tracked_index=str(row["tracked_index"]).zfill(6) if row.get("tracked_index") else None,
                sector=row.get("sector"),
                eastmoney_sector=row.get("eastmoney_sector"),
                flow_sectors=tuple(row.get("flow_sectors") or ()),
                index_data=bool(row.get("index_data", True)),
                effective_from=_parse_date(row.get("effective_from")),
                effective_to=_parse_date(row.get("effective_to")),
                benchmark=bool(row.get("benchmark", False)),
            )
        )
    return Universe(
        version=str(payload.get("version", "u1")),
        etfs=etfs,
        path=path,
        metadata={k: v for k, v in payload.items() if k not in ("etfs",)},
    )
