"""Regression harness for LLM-facing outputs.

Two modes:

    python -m finagent.evals.run_evals --smoke
        Offline self-test: validates the golden set and the metrics themselves.
        No model calls, no network. This is the CI gate.

    python -m finagent.evals.run_evals --answers answers.jsonl
        Scores real answers (one JSON object per line: id, answer, evidence_ids)
        and fails if citation accuracy or numeric traceability drop below the
        thresholds. Run this after any prompt/model change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finagent.evals.metrics import citation_accuracy, numeric_traceability, score_case

DEFAULT_GOLDEN = Path(__file__).resolve().parent.parent.parent / "evals" / "golden_set.jsonl"

REQUIRED_FIELDS = {
    "concept": ("id", "type", "question"),
    "report": ("id", "type", "question", "required_sections"),
    "numeric": ("id", "type", "question", "allowed_values"),
}


def load_cases(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} invalid JSON: {exc}") from exc
        case["_line"] = lineno
        cases.append(case)
    return cases


def validate_cases(cases: list[dict]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for case in cases:
        cid = case.get("id")
        if not cid:
            problems.append(f"line {case.get('_line')}: missing id")
            continue
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        kind = case.get("type")
        if kind not in REQUIRED_FIELDS:
            problems.append(f"{cid}: unknown type {kind!r}")
            continue
        for field in REQUIRED_FIELDS[kind]:
            if not case.get(field):
                problems.append(f"{cid}: missing {field}")
        if kind == "report" and len(case.get("required_sections", [])) < 2:
            problems.append(f"{cid}: report needs at least 2 sections")
        if kind == "numeric" and len(case.get("allowed_values", [])) < 1:
            problems.append(f"{cid}: numeric case needs allowed_values")
    return problems


def _smoke_self_test() -> list[str]:
    """Check that the metrics accept a good answer and reject a bad one."""
    failures: list[str] = []
    evidence = ["val:000300:pe_pct", "macro:cn10y"]

    good = "## 结论\nPE 分位 15.43% [snap:val:000300:pe_pct]，十年期国债 1.61% [snap:macro:cn10y]。"
    got = citation_accuracy(good, evidence)
    if got["score"] != 1.0:
        failures.append(f"citation_accuracy should be 1.0, got {got}")
    if numeric_traceability(good, [15.43, 1.61])["score"] != 1.0:
        failures.append("numeric_traceability should be 1.0 for traceable numbers")

    bad = "结论：PE 分位 42.0% [snap:not-in-evidence]。"
    got = citation_accuracy(bad, evidence)
    if got["invalid"] != ["not-in-evidence"]:
        failures.append(f"invalid citation not detected: {got}")
    trace = numeric_traceability(bad, [15.43, 1.61])
    if trace["score"] >= 1.0:
        failures.append("untraceable number 42.0 not flagged")

    case = {"id": "smoke", "type": "report", "required_sections": ["结论"], "forbidden": ["稳赚"]}
    if score_case(case, "结论：稳赚").passed:
        failures.append("forbidden term not flagged")
    if not score_case(case, "结论：中性").passed:
        failures.append("clean answer wrongly failed")
    return failures


def run_smoke(path: Path) -> int:
    if not path.exists():
        print(f"golden set not found: {path}", file=sys.stderr)
        return 1
    cases = load_cases(path)
    problems = validate_cases(cases) + _smoke_self_test()
    if problems:
        print("SMOKE FAILED")
        for p in problems:
            print(f"  - {p}")
        return 1
    kinds: dict[str, int] = {}
    for c in cases:
        kinds[c["type"]] = kinds.get(c["type"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    print(f"SMOKE OK: {len(cases)} cases ({summary}); metrics self-test passed")
    return 0


def run_answers(path: Path, golden: Path, *, min_citation: float, min_trace: float) -> int:
    cases = {c["id"]: c for c in load_cases(golden)}
    answers: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        answers[row["id"]] = row

    total = passed = 0
    citation_scores: list[float] = []
    trace_scores: list[float] = []
    for cid, case in cases.items():
        row = answers.get(cid)
        if row is None:
            print(f"MISSING  {cid}")
            total += 1
            continue
        score = score_case(case, row.get("answer", ""), row.get("evidence_ids", []))
        total += 1
        passed += int(score.passed)
        if "citation" in score.details:
            citation_scores.append(score.details["citation"]["score"])
        if "numeric" in score.details:
            trace_scores.append(score.details["numeric"]["score"])
        status = "PASS" if score.passed else "FAIL"
        print(f"{status:5} {cid}")
        for reason in score.details.get("failures", []):
            print(f"      - {reason}")

    mean_citation = sum(citation_scores) / len(citation_scores) if citation_scores else 1.0
    mean_trace = sum(trace_scores) / len(trace_scores) if trace_scores else 1.0
    print(
        f"\ncases {passed}/{total} passed; citation={mean_citation:.2%} "
        f"(min {min_citation:.0%}); traceability={mean_trace:.2%} (min {min_trace:.0%})"
    )
    ok = passed == total and mean_citation >= min_citation and mean_trace >= min_trace
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LLM report quality")
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--answers", type=Path, help="JSONL with id/answer/evidence_ids")
    parser.add_argument("--smoke", action="store_true", help="offline validation only")
    parser.add_argument("--min-citation", type=float, default=0.90)
    parser.add_argument("--min-trace", type=float, default=0.95)
    args = parser.parse_args(argv)

    if args.answers:
        return run_answers(
            args.answers, args.golden_set, min_citation=args.min_citation, min_trace=args.min_trace
        )
    return run_smoke(args.golden_set)


if __name__ == "__main__":
    raise SystemExit(main())
