"""Phase 5 flow factors: sector flow, ETF share change, premium/discount.

Every loader returns `(frame, SourceStatus)`. A caller must branch on the
status; an empty frame alone cannot distinguish "no signal" from "no data".
"""

from finagent.flows.etf import (
    load_nav_history,
    load_share_snapshots,
    premium_discount_scores,
    share_change_scores,
)
from finagent.flows.report import build_flows_report, format_flows
from finagent.flows.sector import (
    flow_factor_scores,
    load_sector_flow_history,
    market_flow_context,
    sector_flow_scores,
)

__all__ = [
    "build_flows_report",
    "format_flows",
    "flow_factor_scores",
    "load_nav_history",
    "load_sector_flow_history",
    "load_share_snapshots",
    "market_flow_context",
    "premium_discount_scores",
    "sector_flow_scores",
    "share_change_scores",
]
