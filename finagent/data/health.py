"""Health checks over the cache: freshness, row counts, null ratios.

Separate from `quality.py` (which validates a frame at collection time) because
health runs later and must answer: "is today's system allowed to publish?"
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from finagent.data.cache import ParquetCache
from finagent.data.provider import DataProvider
from finagent.data.universe import Universe

PRICE_GRACE_DAYS = 1  # allow yesterday before the close job finishes
MACRO_GRACE_DAYS = 60


def _row(
    checks: list[dict],
    dataset: str,
    key: str,
    *,
    last_date: str | None,
    expected: date,
    grace_days: int,
    rows: int | None = None,
    missing: float | None = None,
) -> None:
    lag = None if not last_date else (expected - pd.Timestamp(last_date).date()).days
    level = "ok"
    message = ""
    if last_date is None:
        level, message = "error", "no data"
    elif lag is not None and lag > grace_days:
        level = "error" if lag > grace_days * 2 else "warning"
        message = f"lag {lag}d > {grace_days}d"
    if missing is not None and missing > 0.1:
        level = "error" if missing > 0.3 else "warning"
        message = (message + "; " if message else "") + f"null ratio {missing:.1%}"
    checks.append(
        {
            "dataset": dataset,
            "key": key,
            "level": level,
            "last_date": last_date,
            "lag_days": lag,
            "rows": rows,
            "null_ratio": None if missing is None else round(missing, 4),
            "message": message,
        }
    )


def _read(cache: ParquetCache, dataset: str, key: str) -> pd.DataFrame | None:
    try:
        return cache.read(dataset, key)
    except Exception:  # noqa: BLE001 - corrupt parquet should surface as a failed check
        return None


def check_health(
    provider: DataProvider,
    cache: ParquetCache,
    universe: Universe,
    as_of: date,
) -> dict:
    last_td = provider.last_trading_day(as_of)
    checks: list[dict] = []

    for symbol in universe.symbols(as_of):
        manifest = cache.manifest("etf_daily_hfq", symbol)
        df = _read(cache, "etf_daily_hfq", symbol)
        missing = float(df["close"].isna().mean()) if df is not None and "close" in df else None
        _row(
            checks,
            "etf_daily_hfq",
            symbol,
            last_date=manifest.last_date if manifest else None,
            expected=last_td,
            grace_days=PRICE_GRACE_DAYS,
            rows=manifest.rows if manifest else None,
            missing=missing,
        )

    tracked = sorted(
        {
            e.tracked_index
            for e in universe.for_date(as_of)
            if e.index_data and e.tracked_index and str(e.tracked_index).isdigit()
        }
    )
    for code in tracked:
        manifest = cache.manifest("index_daily", code)
        _row(
            checks,
            "index_daily",
            code,
            last_date=manifest.last_date if manifest else None,
            expected=last_td,
            grace_days=PRICE_GRACE_DAYS,
            rows=manifest.rows if manifest else None,
        )

    for name in ("pmi", "cpi", "ppi", "m2", "lpr"):
        manifest = cache.manifest("macro", name)
        _row(
            checks,
            "macro",
            name,
            last_date=manifest.last_date if manifest else None,
            expected=as_of,
            grace_days=MACRO_GRACE_DAYS,
            rows=manifest.rows if manifest else None,
        )

    for dataset, key, grace in (
        ("bond_yield", "cn10y", PRICE_GRACE_DAYS),
        ("market_flow", "cn", PRICE_GRACE_DAYS),
        ("margin_sse", "sse", PRICE_GRACE_DAYS),
        ("trade_calendar", "all", 30),
    ):
        manifest = cache.manifest(dataset, key)
        _row(
            checks,
            dataset,
            key,
            last_date=manifest.last_date if manifest else None,
            expected=as_of,
            grace_days=grace,
            rows=manifest.rows if manifest else None,
        )

    errors = [c for c in checks if c["level"] == "error"]
    warnings = [c for c in checks if c["level"] == "warning"]
    return {
        "as_of": as_of.isoformat(),
        "last_trading_day": last_td.isoformat(),
        "ok": not errors,
        "errors": len(errors),
        "warnings": len(warnings),
        "checks": checks,
    }
