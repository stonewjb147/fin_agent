"""Phase 5 terminal report: what flow/news data exists, and what it says."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.data.cache import ParquetCache
from finagent.factors import load_close_panel
from finagent.flows.etf import (
    load_nav_history,
    load_share_snapshots,
    premium_discount_scores,
    share_change_scores,
)
from finagent.flows.sector import (
    flow_factor_scores,
    load_sector_flow_history,
    market_flow_context,
)
from finagent.news import load_news


def build_flows_report(
    universe,
    as_of: date | str,
    *,
    cache_dir: str | Path | None = None,
    news_path: str | Path | None = None,
    window: int = 5,
    share_window_days: int = 20,
) -> dict:
    """Every Phase 5 source with its status, plus scores wherever defined."""
    cache = cache_dir if isinstance(cache_dir, ParquetCache) else ParquetCache(cache_dir or config.CACHE_DIR)
    symbols = universe.symbols(pd.Timestamp(as_of).date())

    history, sector_status = load_sector_flow_history(cache, as_of, window=window)
    sector_scores = (
        flow_factor_scores(history, universe, as_of, window=window)
        if sector_status.available
        else pd.DataFrame(columns=["date", "symbol", "flow_z", "n_sectors", "sectors"])
    )

    share_history, share_status = load_share_snapshots(cache, as_of)
    share_scores = pd.DataFrame(columns=["date", "symbol", "share_change", "share_z", "span_days"])
    if share_status.available:
        share_scores, share_status = share_change_scores(share_history, window_days=share_window_days)

    nav_history, nav_status = load_nav_history(cache, symbols, as_of)
    premium_scores = pd.DataFrame(columns=["date", "symbol", "premium", "premium_z", "nav_date"])
    if nav_status.available:
        close = load_close_panel(cache, symbols, as_of)
        premium_scores, nav_status = premium_discount_scores(close, nav_history)

    market, market_status = market_flow_context(cache, as_of)
    news_file = Path(news_path or config.NEWS_DIR / f"{pd.Timestamp(as_of).date().isoformat()}.json")
    news = load_news(news_file, as_of)

    statuses = [sector_status, share_status, nav_status, market_status, news.status]
    return {
        "as_of": pd.Timestamp(as_of).date().isoformat(),
        "window": window,
        "sources": {status.name: status.to_dict() for status in statuses if status is not None},
        "market_flow": market,
        "sector_flow": sector_scores.to_dict("records"),
        "share_change": share_scores.to_dict("records"),
        "premium_discount": premium_scores.to_dict("records"),
        "news": {
            "path": str(news_file),
            "n_usable_items": len(news.items),
            "dropped_future": news.dropped_future,
            "dropped_invalid": news.dropped_invalid,
        },
    }


def format_flows(report: dict) -> str:
    lines = [f"Phase 5 flows & news  {report['as_of']}", "", "SOURCES"]
    for name, status in report["sources"].items():
        flag = "OK     " if status["available"] else "MISSING"
        lines.append(f"{flag} {name:<18} {status['reason']}")
    market = report.get("market_flow") or {}
    if market:
        lines.append(
            f"\nMARKET FLOW  {market['date']}  main net inflow {market['main_net_inflow_pct']}% "
            f"(5d mean {market['mean_pct_5d']}%)"
        )

    for key, title, score_column in (
        ("sector_flow", "SECTOR FLOW (z, mapped ETFs)", "flow_z"),
        ("share_change", "SHARE CHANGE (z, mapped ETFs)", "share_z"),
        ("premium_discount", "PREMIUM / DISCOUNT (z, mapped ETFs)", "premium_z"),
    ):
        rows = report.get(key) or []
        lines.append("")
        if not rows:
            lines.append(f"{title}: no scores (source unavailable)")
            continue
        lines.append(title)
        for row in rows:
            extra = row.get("sectors") or row.get("span_days") or row.get("nav_date")
            lines.append(f"  {row['symbol']:<8} {row[score_column]:+.2f}  {extra}")
    return "\n".join(lines)
