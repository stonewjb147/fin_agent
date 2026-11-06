"""News -> sector -> ETF overlay.

The news extractor lives outside this repo (week3: titles -> themes ->
`sentiment`). This module owns the part that must be reproducible: point-in-time
filtering, a keyword -> sector map maintained by hand, and a bounded adjustment
whose size is written next to every score it changes.

When the file is absent the overlay is skipped and says so. It never falls back
to yesterday's headlines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from finagent import config
from finagent.data.sources import SourceStatus

DEFAULT_WEIGHT = 0.20
DEFAULT_MAX_ABS = 0.30
MAX_TITLES = 3


@dataclass(frozen=True)
class NewsItem:
    title: str
    sentiment: float
    published_at: str | None = None
    sectors: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sentiment": self.sentiment,
            "published_at": self.published_at,
            "sectors": list(self.sectors),
            "themes": list(self.themes),
            "symbols": list(self.symbols),
            "source": self.source,
        }


@dataclass
class NewsLoad:
    items: list[NewsItem] = field(default_factory=list)
    status: SourceStatus | None = None
    dropped_future: int = 0
    dropped_invalid: int = 0

    @property
    def available(self) -> bool:
        return bool(self.status and self.status.available)


def load_news_map(path: str | Path | None = None) -> dict[str, dict]:
    """Theme keyword -> sectors / symbols / categories. Missing file = empty map."""
    path = Path(path or config.CONFIG_DIR / "news_map.yaml")
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    themes = payload.get("themes") or {}
    return {str(key): dict(value or {}) for key, value in themes.items()}


def _parse_published(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _as_item(row: dict) -> NewsItem | None:
    title = str(row.get("title") or "").strip()
    try:
        sentiment = float(row.get("sentiment"))
    except (TypeError, ValueError):
        return None
    if not title or not np.isfinite(sentiment):
        return None
    return NewsItem(
        title=title,
        sentiment=float(np.clip(sentiment, -1.0, 1.0)),
        published_at=str(row["published_at"]) if row.get("published_at") else None,
        sectors=tuple(str(s) for s in (row.get("sectors") or []) if s),
        themes=tuple(str(s) for s in (row.get("themes") or []) if s),
        symbols=tuple(str(s).zfill(6) for s in (row.get("symbols") or []) if s),
        source=str(row["source"]) if row.get("source") else None,
    )


def load_news(path: str | Path, as_of: date | str) -> NewsLoad:
    """Read one news file and keep only items published on or before `as_of`.

    `as_of` means end of that trading day: an item stamped 15:30 on `as_of` is
    usable for a signal formed after the close, one stamped tomorrow is not.
    """
    cutoff = pd.Timestamp(as_of).date()
    path = Path(path)
    if not path.exists():
        return NewsLoad(status=SourceStatus.missing("news", f"no news file at {path}"))

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return NewsLoad(status=SourceStatus.missing("news", f"unreadable {path}: {exc}"))

    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return NewsLoad(status=SourceStatus.missing("news", f"{path} has no items list"))

    items: list[NewsItem] = []
    future = invalid = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        item = _as_item(row)
        if item is None:
            invalid += 1
            continue
        published = _parse_published(item.published_at)
        if published is not None and published.date() > cutoff:
            future += 1
            continue
        items.append(item)

    if not items:
        reason = f"{path} has no usable item on or before {cutoff}"
        if future:
            reason += f" ({future} future item(s) dropped)"
        if invalid:
            reason += f" ({invalid} invalid item(s) dropped)"
        return NewsLoad(
            items=[], status=SourceStatus.missing("news", reason), dropped_future=future, dropped_invalid=invalid
        )
    return NewsLoad(
        items=items,
        status=SourceStatus.ok(
            "news",
            f"{len(items)} usable item(s) from {path.name}"
            + (f", {future} future dropped" if future else "")
            + (f", {invalid} invalid dropped" if invalid else ""),
            n_records=len(items),
            last_date=cutoff.isoformat(),
        ),
        dropped_future=future,
        dropped_invalid=invalid,
    )


def news_scores(
    items: list[NewsItem] | NewsLoad,
    universe,
    as_of: date | str,
    *,
    mapping: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Aggregate item sentiment into per-ETF scores with their evidence.

    Matching channels, all explicit: direct `symbols`, THS `sectors` against
    the ETF's `flow_sectors`, and free-text `themes` expanded through
    `configs/news_map.yaml`. An item that matches nothing is counted and
    dropped — it must not quietly influence a category average.
    """
    if isinstance(items, NewsLoad):
        items = items.items
    mapping = mapping if mapping is not None else load_news_map()
    day = pd.Timestamp(as_of).normalize()
    meta = universe.by_symbol()

    buckets: dict[str, list[tuple[float, str]]] = {}
    unmatched = 0
    for item in items:
        sectors = set(item.sectors)
        symbols: set[str] = set(item.symbols)
        for theme in item.themes:
            rule = mapping.get(theme)
            if not rule:
                continue
            sectors.update(str(s) for s in (rule.get("sectors") or []))
            symbols.update(str(s).zfill(6) for s in (rule.get("symbols") or []))
            for category in rule.get("categories") or []:
                symbols.update(
                    e.symbol for e in universe.etfs if e.category == str(category) and e.active_on(day.date())
                )

        matched: set[str] = {s for s in symbols if s in meta}
        if sectors:
            for etf in universe.etfs:
                if not etf.active_on(day.date()):
                    continue
                sector_names = set(etf.flow_sectors)
                if etf.sector:
                    sector_names.add(str(etf.sector))
                if etf.eastmoney_sector:
                    sector_names.add(str(etf.eastmoney_sector))
                if sector_names & sectors:
                    matched.add(etf.symbol)
        if not matched:
            unmatched += 1
            continue
        for symbol in matched:
            buckets.setdefault(symbol, []).append((item.sentiment, item.title))

    rows = []
    for symbol, entries in sorted(buckets.items()):
        sentiments = np.array([sentiment for sentiment, _ in entries], dtype=float)
        rows.append(
            {
                "date": day,
                "symbol": symbol,
                "news_score": float(np.clip(sentiments.mean(), -1.0, 1.0)),
                "n_items": len(entries),
                "titles": " | ".join(title for _, title in entries[:MAX_TITLES]),
            }
        )
    frame = pd.DataFrame(rows, columns=["date", "symbol", "news_score", "n_items", "titles"])
    diagnostics = {
        "n_items": len(items),
        "n_matched_items": len(items) - unmatched,
        "n_unmatched_items": unmatched,
        "n_symbols": int(len(frame)),
    }
    return frame, diagnostics


def apply_news_overlay(
    scores: pd.DataFrame,
    news: pd.DataFrame,
    *,
    weight: float = DEFAULT_WEIGHT,
    max_abs: float = DEFAULT_MAX_ABS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add `weight * news_score` to the latest day's composite, capped.

    Only the latest date is adjusted: historical scores must stay reproducible
    from the factors that produced them. The returned contributions frame is
    what gets reported, so every changed score has a stated cause and size.
    """
    columns = ["date", "symbol", "news_score", "n_items", "titles", "contribution", "composite_before", "composite_after"]
    if scores.empty or news.empty:
        return scores.copy(), pd.DataFrame(columns=columns)

    day = pd.Timestamp(scores["date"].max())
    adjusted = scores.copy()
    day_rows = adjusted["date"] == day
    base = adjusted.loc[day_rows, ["symbol", "composite"]].set_index("symbol")
    contributions = news.copy()
    contributions["contribution"] = np.clip(
        float(weight) * contributions["news_score"].astype(float), -abs(max_abs), abs(max_abs)
    )
    contributions = contributions[contributions["symbol"].isin(base.index)].copy()
    if contributions.empty:
        return scores.copy(), pd.DataFrame(columns=columns)

    contributions["composite_before"] = contributions["symbol"].map(base["composite"])
    contributions["composite_after"] = contributions["composite_before"] + contributions["contribution"]
    contributions["date"] = day

    shift = contributions.set_index("symbol")["contribution"]
    adjusted.loc[day_rows, "composite"] = (
        adjusted.loc[day_rows, "symbol"].map(shift).fillna(0.0).to_numpy()
        + adjusted.loc[day_rows, "composite"].to_numpy()
    )
    keep = ["date", "symbol", "news_score", "n_items", "titles", "contribution", "composite_before", "composite_after"]
    return adjusted, contributions[keep].reset_index(drop=True)
