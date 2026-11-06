"""Phase 6: grounded narrative reports with deterministic fallback."""

from finagent.agent.evidence import (
    Evidence,
    EvidenceBundle,
    ReportFacts,
    build_evidence,
    build_facts,
)
from finagent.agent.llm import DeepSeekClient, LLMConfig, LLMError, config_from_env
from finagent.agent.report import ReportError, ReportResult, generate_report, verify_report
from finagent.agent.template import render_template

__all__ = [
    "DeepSeekClient",
    "Evidence",
    "EvidenceBundle",
    "LLMConfig",
    "LLMError",
    "ReportError",
    "ReportFacts",
    "ReportResult",
    "build_evidence",
    "build_facts",
    "config_from_env",
    "generate_report",
    "render_template",
    "verify_report",
]
