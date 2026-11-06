"""Phase 8-10: growth loop for the human researcher.

- Phase 8: daily state (process, evidence, risk, data)
- Phase 9: decision journal and outcome review
- Phase 10: periodic growth review with lessons and next actions
"""

from finagent.growth.journal import (
    ACTION_DIRECTION,
    ACTION_LABELS,
    DecisionJournal,
    JournalError,
    format_journal,
)
from finagent.growth.pipeline import (
    format_growth,
    format_growth_review,
    format_journal_review,
    run_growth,
    run_growth_review,
    run_journal_review,
)
from finagent.growth.review import build_growth_review, render_growth_review
from finagent.growth.state import build_growth_state

__all__ = [
    "ACTION_DIRECTION",
    "ACTION_LABELS",
    "DecisionJournal",
    "JournalError",
    "build_growth_review",
    "build_growth_state",
    "format_growth",
    "format_growth_review",
    "format_journal",
    "format_journal_review",
    "render_growth_review",
    "run_growth",
    "run_growth_review",
    "run_journal_review",
]
