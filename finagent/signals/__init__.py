"""Structured research signals with falsifiable invalidation rules."""

from __future__ import annotations

from finagent.signals.build import MIN_COMPOSITE, MIN_CONFIDENCE, build_signals
from finagent.signals.models import Evidence, InvalidationRule, QuantSignal
from finagent.signals.pipeline import format_signals, run_signal_pipeline
from finagent.signals.score import DEFAULT_WEIGHTS, composite_scores, score_row

__all__ = [
    "DEFAULT_WEIGHTS",
    "MIN_COMPOSITE",
    "MIN_CONFIDENCE",
    "Evidence",
    "InvalidationRule",
    "QuantSignal",
    "build_signals",
    "composite_scores",
    "format_signals",
    "run_signal_pipeline",
    "score_row",
]
