"""One source of truth for report language rules.

Phase 6 and Phase 7 must not drift apart: a word forbidden in the narrative
report is forbidden because it is a compliance rule, not because a particular
prompt happened to list it. The prompt module imports these tuples instead of
defining its own.
"""

from __future__ import annotations

# Words that turn a research record into advice or a promise.
FORBIDDEN_TERMS: tuple[str, ...] = (
    "稳赚",
    "必涨",
    "保证收益",
    "推荐买入",
    "建议买入",
    "满仓",
    "抄底",
)

# Disclosures every report must contain verbatim.
REQUIRED_TERMS: tuple[str, ...] = (
    "validated=false",
    "存续偏差",
    "不构成投资建议",
)

# Extra term required only when the risk layer blocks the conclusion.
BLOCKED_TERM = "风控阻断"


def required_terms(risk_status: str | None = None) -> list[str]:
    """Disclosures for a normal report, plus the block marker when needed."""
    terms = list(REQUIRED_TERMS)
    if risk_status == "blocked":
        terms.append(BLOCKED_TERM)
    return terms
