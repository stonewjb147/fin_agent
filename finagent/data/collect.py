"""One-shot daily collection: fetch, validate, snapshot, report.

The collector is deliberately boring: it walks a fixed list of datasets, logs
every success and failure, and builds a lineage snapshot from what actually
landed in the cache. Missing coverage (e.g. an index without CSIndex data) is
recorded as `coverage`, not hidden and not fatal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from finagent import config
from finagent.data.akshare_provider import AkshareProvider
from finagent.data.lineage import SnapshotStore
from finagent.data.provider import DataNotAvailable, ProviderError
from finagent.data.quality import QualityReport, check_frame, merge_reports
from finagent.data.universe import Universe

SnapshotMode = Literal["auto", "on", "off"]


@dataclass
class CollectResult:
    as_of: str
    start: str
    snapshot_id: str | None = None
    datasets: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    quality_path: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.datasets) and not any(f["kind"] == "error" for f in self.failures)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "start": self.start,
            "snapshot_id": self.snapshot_id,
            "ok": self.ok,
            "dataset_count": len(self.datasets),
            "datasets": self.datasets,
            "failures": self.failures,
            "quality": self.quality,
        }


def _is_numeric_index(code: str | None) -> bool:
    return bool(code) and str(code).isdigit()


def collect(
    provider: AkshareProvider,
    universe: Universe,
    start: date,
    end: date,
    *,
    snapshots: SnapshotMode = "auto",
    force: bool = False,
) -> CollectResult:
    config.ensure_dirs()
    result = CollectResult(as_of=end.isoformat(), start=start.isoformat())
    pairs: list[tuple[str, str]] = []
    reports: list[QualityReport] = []

    def record(
        dataset: str,
        key: str,
        frame: pd.DataFrame,
        *,
        price_cols: tuple[str, ...] = ("open", "close"),
        date_col: str = "date",
        allow_future: bool = False,
    ) -> None:
        if frame is None or frame.empty:
            result.failures.append({"dataset": dataset, "key": key, "kind": "error", "message": "empty frame"})
            return
        pairs.append((dataset, key))
        report = check_frame(
            frame,
            dataset,
            key,
            end,
            date_col=date_col,
            price_cols=price_cols,
            allow_future=allow_future,
        )
        if frame.attrs.get("stale"):
            report.add(
                "warning",
                "stale_cache",
                f"served cached data (last={frame.attrs.get('last_date')})",
            )
        reports.append(report)
        result.datasets.append(
            {
                "dataset": dataset,
                "key": key,
                "rows": int(len(frame)),
                "last_date": frame.attrs.get("last_date"),
                "stale": bool(frame.attrs.get("stale")),
                "source": provider._source_name(dataset),
            }
        )

    # 1) ETF daily -----------------------------------------------------
    symbols = universe.symbols(end)
    try:
        etf = provider.etf_daily(symbols, start, end, force=force)
        for sym in symbols:
            subset = etf[etf["symbol"] == sym]
            record("etf_daily_hfq", sym, subset)
    except ProviderError as exc:
        result.failures.append(
            {"dataset": "etf_daily_hfq", "key": "*", "kind": "error", "message": str(exc)[:500]}
        )

    # 2) indices -------------------------------------------------------
    tracked = sorted(
        {
            e.tracked_index
            for e in universe.for_date(end)
            if e.index_data and _is_numeric_index(e.tracked_index)
        }
    )
    valuation_covered: set[str] = set()
    for code in tracked:
        try:
            frame = provider.index_daily(code, start, end, force=force)
            record("index_daily", code, frame)
        except (ProviderError, DataNotAvailable) as exc:
            result.failures.append(
                {"dataset": "index_daily", "key": code, "kind": "coverage", "message": str(exc)[:300]}
            )
        try:
            frame = provider.index_valuation(code, start, end, force=force)
            record("index_valuation", code, frame)
            valuation_covered.add(code)
        except (ProviderError, DataNotAvailable) as exc:
            result.failures.append(
                {"dataset": "index_valuation", "key": code, "kind": "coverage", "message": str(exc)[:300]}
            )

    # 3) macro / rates / flows ----------------------------------------
    for name in ("pmi", "cpi", "ppi", "m2", "lpr"):
        try:
            frame = provider.macro(name, force=force)
            record("macro", name, frame, price_cols=())
        except (ProviderError, DataNotAvailable) as exc:
            result.failures.append(
                {"dataset": "macro", "key": name, "kind": "error", "message": str(exc)[:300]}
            )

    for dataset, key, fn in (
        ("bond_yield", "cn10y", lambda: provider.bond_yield(start, end, force=force)),
        ("market_flow", "cn", lambda: provider.market_flow(start, end, force=force)),
        ("margin_sse", "sse", lambda: provider.margin_sse(start, end, force=force)),
        ("trade_calendar", "all", lambda: provider.trade_calendar(force=force)),
    ):
        try:
            frame = fn()
            record(
                dataset,
                key,
                frame,
                price_cols=(),
                allow_future=dataset == "trade_calendar",
            )
        except (ProviderError, DataNotAvailable) as exc:
            result.failures.append(
                {"dataset": dataset, "key": key, "kind": "error", "message": str(exc)[:300]}
            )

    # 4) snapshot datasets --------------------------------------------
    # These are today-only cross-sections. Backfilling them with a past key
    # would silently mislabel today's data as history, so we only collect when
    # `end` is the latest trading day.
    include_snapshots = snapshots == "on"
    if snapshots == "auto":
        try:
            include_snapshots = end == provider.last_trading_day()
        except ProviderError:
            include_snapshots = False

    if include_snapshots:
        for dataset, key, fn in (
            ("sector_flow_rank", end.isoformat(), lambda: provider.sector_flow_rank(end)),
            ("etf_spot", end.isoformat(), lambda: provider.etf_snapshot(end)),
            ("etf_scale_sse", end.isoformat(), lambda: provider.etf_scale_sse(end)),
        ):
            try:
                frame = fn()
                # These are cross-sectional snapshots: no OHLC columns.
                record(dataset, key, frame, price_cols=())
            except (ProviderError, DataNotAvailable) as exc:
                # Snapshot feeds are ancillary: the ETF scale file is published
                # with a lag, so a same-evening miss is a coverage gap, not a
                # pipeline failure.
                kind = "coverage" if dataset == "etf_scale_sse" else "error"
                result.failures.append(
                    {"dataset": dataset, "key": key, "kind": kind, "message": str(exc)[:300]}
                )

        # Only indices with a working valuation history get a snapshot; avoids
        # hammering CSIndex for codes it does not publish (e.g. SSE bond indices).
        for code in sorted(valuation_covered):
            try:
                frame = provider.index_value_snapshot(code, end)
                record("index_value_snapshot", f"{code}_{end.isoformat()}", frame, price_cols=("pe",))
            except (ProviderError, DataNotAvailable) as exc:
                result.failures.append(
                    {
                        "dataset": "index_value_snapshot",
                        "key": code,
                        "kind": "coverage",
                        "message": str(exc)[:300],
                    }
                )

    # 5) quality + snapshot -------------------------------------------
    result.quality = merge_reports(reports)
    result.quality["failures"] = result.failures
    try:
        from finagent.data.catalog import coverage_notes, load_catalog

        result.quality["unavailable"] = coverage_notes(load_catalog())
    except (OSError, ValueError):
        result.quality["unavailable"] = {}
    quality_path = config.QUALITY_DIR / f"collect_{end.isoformat()}.json"
    quality_path.write_text(
        __import__("json").dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    result.quality_path = str(quality_path)

    if pairs:
        store = SnapshotStore(config.SNAPSHOT_DIR)
        snap = store.build(
            provider.cache,
            pairs,
            end,
            note=f"collect {start}..{end}",
            extras={"universe_version": universe.version, "failures": len(result.failures)},
        )
        result.snapshot_id = snap.snapshot_id

    return result
