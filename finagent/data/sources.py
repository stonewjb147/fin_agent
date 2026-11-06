"""Explicit status for optional data sources.

Phase 5 adds sources that are allowed to be missing: sector money flow is
accumulated one snapshot at a time, NAV history and ETF share data are
published with gaps, and news arrives from outside this repo. A missing source
must degrade the pipeline and say so, never silently drop a factor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceStatus:
    """Whether one optional source can be used, and why not if it cannot."""

    name: str
    available: bool
    reason: str
    n_records: int = 0
    first_date: str | None = None
    last_date: str | None = None

    @classmethod
    def missing(cls, name: str, reason: str, **kwargs) -> "SourceStatus":
        return cls(name=name, available=False, reason=reason, **kwargs)

    @classmethod
    def ok(cls, name: str, reason: str = "", **kwargs) -> "SourceStatus":
        return cls(name=name, available=True, reason=reason, **kwargs)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": bool(self.available),
            "reason": self.reason,
            "n_records": int(self.n_records),
            "first_date": self.first_date,
            "last_date": self.last_date,
        }
