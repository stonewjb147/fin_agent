"""Phase 6 report pipeline: evidence -> LLM (or template) -> gates -> files.

The LLM is never trusted: its output is scored against the same metrics used by
`finagent.evals`. A rejected answer is retried once with the failure list, then
the deterministic template takes over. Both paths write the same artefacts, so
a missing API key degrades rather than skips the daily report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from finagent import config
from finagent.agent.evidence import (
    EvidenceBundle,
    ReportFacts,
    build_evidence,
    build_facts,
)
from finagent.agent.llm import DeepSeekClient, LLMClient, LLMError, config_from_env
from finagent.agent.prompts import (
    FORBIDDEN,
    MIN_CITATIONS,
    MUST_INCLUDE,
    REQUIRED_SECTIONS,
    SYSTEM_PROMPT,
    repair_prompt,
    user_prompt,
)
from finagent.agent.template import render_template
from finagent.evals.metrics import score_case, strict_untraceable


class ReportError(RuntimeError):
    """The report could not be produced with grounded numbers."""


def verify_report(text: str, bundle: EvidenceBundle) -> dict:
    """Run the report through the same gates as the evaluation harness."""
    case = {
        "id": f"report:{bundle.as_of}",
        "required_sections": REQUIRED_SECTIONS,
        "must_include": MUST_INCLUDE,
        "forbidden": FORBIDDEN,
        "required_citations": True,
        "min_citations": MIN_CITATIONS,
        "allowed_values": bundle.allowed_values,
        "ignore_values": bundle.ignore_values,
        "ignore_terms": list(bundle.ignore_terms),
    }
    score = score_case(case, text, bundle.ids)
    details = dict(score.details)
    failures = list(details.pop("failures", []))
    passed = score.passed
    # The generic eval allows 5% untraceable numbers and 1% tolerance; a daily
    # report must allow none, and may not add precision the evidence lacks.
    strict = strict_untraceable(
        text,
        bundle.allowed_values,
        ignore_values=bundle.ignore_values,
        ignore_terms=list(bundle.ignore_terms),
    )
    details["numeric_strict"] = strict
    if strict["untraceable"]:
        passed = False
        failures.append(f"untraceable numbers: {strict['untraceable'][:5]}")
    return {
        "passed": passed,
        "failures": failures,
        "sections": REQUIRED_SECTIONS,
        "min_citations": MIN_CITATIONS,
        **details,
    }


@dataclass
class ReportResult:
    as_of: str
    text: str
    mode: str
    checks: dict
    attempts: int = 0
    model: str | None = None
    fallback_reason: str | None = None
    prompt_sha256: str | None = None
    evidence: EvidenceBundle | None = None
    files: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "mode": self.mode,
            "model": self.model,
            "attempts": self.attempts,
            "fallback_reason": self.fallback_reason,
            "prompt_sha256": self.prompt_sha256,
            "checks": self.checks,
            "evidence": self.evidence.as_dict() if self.evidence else None,
            "files": self.files,
            "text": self.text,
        }


def _prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()


def _generate_llm(
    bundle: EvidenceBundle, facts: ReportFacts, client: LLMClient
) -> tuple[str | None, int, str | None, str | None]:
    """Return (text, attempts, prompt hash, fallback reason). text=None means fallback."""
    system = SYSTEM_PROMPT
    user = user_prompt(bundle, facts)
    digest = _prompt_hash(system, user)
    attempts = 0
    try:
        attempts = 1
        answer = client.complete(system, user)
        checks = verify_report(answer, bundle)
        if not checks["passed"]:
            repair = repair_prompt(bundle, answer, checks["failures"])
            attempts = 2
            answer = client.complete(system, repair)
            checks = verify_report(answer, bundle)
    except LLMError as exc:
        return None, attempts, digest, f"LLM unavailable: {exc}"
    if checks["passed"]:
        return answer, attempts, digest, None
    failures = "; ".join(checks["failures"])[:300] or "unknown gate failure"
    return None, attempts, digest, f"LLM output rejected after {attempts} attempt(s): {failures}"


def generate_report(
    as_of: str,
    *,
    client: LLMClient | None = None,
    use_llm: bool = True,
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    write: bool = True,
    model: str | None = None,
) -> ReportResult:
    facts = build_facts(as_of, data_dir=data_dir)
    bundle = build_evidence(facts)

    text: str | None = None
    mode = "template"
    attempts = 0
    result_model: str | None = None
    digest: str | None = None
    fallback_reason: str | None = None

    if use_llm:
        active = client
        if active is None:
            cfg = config_from_env()
            if model:
                cfg.model = model
            if cfg.configured:
                active = DeepSeekClient(cfg)
            else:
                fallback_reason = "DEEPSEEK_API_KEY not configured"
        if active is not None:
            result_model = getattr(active, "model", None)
            text, attempts, digest, fallback_reason = _generate_llm(bundle, facts, active)

    if text is None:
        text = render_template(bundle, facts)
        checks = verify_report(text, bundle)
        if not checks["passed"]:
            raise ReportError(
                "deterministic template failed its own gates: "
                + "; ".join(checks["failures"])
            )
        mode = "template"
    else:
        mode = "llm"
        checks = verify_report(text, bundle)

    result = ReportResult(
        as_of=as_of,
        text=text,
        mode=mode,
        checks=checks,
        attempts=attempts,
        model=result_model if mode == "llm" else None,
        fallback_reason=fallback_reason,
        prompt_sha256=digest,
        evidence=bundle,
    )

    if write:
        target = Path(out_dir or config.REPORT_DIR)
        target.mkdir(parents=True, exist_ok=True)
        md_path = target / f"report_{as_of}.md"
        json_path = target / f"report_{as_of}.json"
        md_path.write_text(text, encoding="utf-8")
        result.files = {"markdown": str(md_path), "json": str(json_path)}
        payload = result.as_dict()
        payload["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        payload["sources"] = bundle.sources
        payload["missing"] = bundle.missing
        payload["text_path"] = str(md_path)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def format_report(result: ReportResult) -> str:
    checks = result.checks
    citation = checks.get("citation") or {}
    numeric = checks.get("numeric_strict") or checks.get("numeric") or {}
    lines = [
        f"Report for {result.as_of}",
        f"Mode        : {result.mode}"
        + (f" (model {result.model}, {result.attempts} attempt(s))" if result.mode == "llm" else ""),
        f"Gate        : {'PASS' if checks.get('passed') else 'FAIL'}",
        f"Citations   : {citation.get('valid', 0)}/{citation.get('cited', 0)} valid",
        f"Numbers     : {numeric.get('checked', 0)} checked, "
        f"{len(numeric.get('untraceable', []))} untraceable",
    ]
    if result.fallback_reason:
        lines.append(f"Fallback    : {result.fallback_reason}")
    if result.files:
        lines.append(f"Markdown    : {result.files.get('markdown')}")
        lines.append(f"JSON        : {result.files.get('json')}")
    return "\n".join(lines)
