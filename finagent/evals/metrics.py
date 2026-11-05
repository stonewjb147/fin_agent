"""Metrics for report quality.

These are process metrics, not outcome metrics: they check that every claim is
grounded, every number is traceable, and the required structure is present.
Outcome calibration (hit rate, Brier) lives in the prediction-ledger phase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_RE = re.compile(r"\[(?:chunk|ref|snap):([^\]]+)\]")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?%?")


@dataclass
class CaseScore:
    case_id: str
    passed: bool = True
    details: dict = field(default_factory=dict)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.details.setdefault("failures", []).append(reason)


def extract_citations(text: str) -> list[str]:
    return [m.strip() for m in CITATION_RE.findall(text or "")]


def citation_accuracy(text: str, available_ids: list[str], *, required: bool = True) -> dict:
    cited = extract_citations(text)
    if not cited:
        return {"score": 0.0 if required else 1.0, "cited": 0, "valid": 0, "invalid": [], "missing": required}
    available = set(available_ids)
    valid = [c for c in cited if c in available]
    invalid = [c for c in cited if c not in available]
    return {
        "score": len(valid) / len(cited),
        "cited": len(cited),
        "valid": len(valid),
        "invalid": invalid,
        "missing": False,
    }


def format_pass(text: str, required_sections: list[str]) -> dict:
    text = text or ""
    missing = [s for s in required_sections if s not in text]
    return {"score": 1.0 if not missing else (len(required_sections) - len(missing)) / len(required_sections), "missing": missing}


def forbidden_hits(text: str, terms: list[str]) -> list[str]:
    text = text or ""
    return [t for t in terms if t in text]


def extract_numbers(text: str) -> list[float]:
    # Citation ids like [snap:val:000300:pe_pct] are references, not claims.
    values: list[float] = []
    for token in NUMBER_RE.findall(CITATION_RE.sub(" ", text or "")):
        raw = token.rstrip("%")
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def numeric_traceability(text: str, allowed_values: list[float], *, tol: float = 0.01, ignore_years: bool = True) -> dict:
    """Fraction of numbers in `text` that match an allowed evidence value.

    Years and small ordinal numbers are ignored; percentages are compared on
    their numeric token (3% -> 3.0), so reports must not silently mix 0.03 and
    3%.
    """
    numbers = extract_numbers(text)
    checked = []
    for value in numbers:
        if ignore_years and 1900 <= value <= 2100 and float(value).is_integer():
            continue
        checked.append(value)
    if not checked:
        return {"score": 1.0, "checked": 0, "untraceable": []}
    untraceable = [
        v for v in checked if not any(abs(v - a) <= tol * max(1.0, abs(a)) for a in allowed_values)
    ]
    return {
        "score": 1 - len(untraceable) / len(checked),
        "checked": len(checked),
        "untraceable": untraceable[:20],
    }


def score_case(case: dict, answer: str, evidence_ids: list[str] | None = None) -> CaseScore:
    score = CaseScore(case_id=case.get("id", "?"))
    evidence_ids = evidence_ids or []

    if case.get("required_sections"):
        fmt = format_pass(answer, case["required_sections"])
        score.details["format"] = fmt
        if fmt["score"] < 1.0:
            score.fail(f"missing sections: {fmt['missing']}")

    if case.get("required_citations") is not None:
        cit = citation_accuracy(answer, evidence_ids, required=bool(case["required_citations"]))
        score.details["citation"] = cit
        if cit["score"] < 0.9:
            score.fail(f"citation accuracy {cit['score']:.2f} < 0.90")
        if cit["invalid"]:
            score.fail(f"invalid citations: {cit['invalid'][:5]}")

    if case.get("must_include"):
        missing = [m for m in case["must_include"] if m not in (answer or "")]
        score.details["must_include_missing"] = missing
        if missing:
            score.fail(f"missing required terms: {missing}")

    if case.get("forbidden"):
        hits = forbidden_hits(answer, case["forbidden"])
        score.details["forbidden_hits"] = hits
        if hits:
            score.fail(f"forbidden terms: {hits}")

    if case.get("allowed_values"):
        trace = numeric_traceability(answer, case["allowed_values"])
        score.details["numeric"] = trace
        if trace["score"] < 0.95:
            score.fail(f"numeric traceability {trace['score']:.2f} < 0.95")

    return score
