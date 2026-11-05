from __future__ import annotations

import json

from finagent.evals.metrics import (
    citation_accuracy,
    extract_citations,
    format_pass,
    numeric_traceability,
    score_case,
)
from finagent.evals.run_evals import load_cases, validate_cases

EVIDENCE = ["val:000300:pe_pct", "macro:cn10y"]


def test_extract_citations_variants():
    text = "见 [snap:val:000300:pe_pct] 与 [chunk:cfa-l2-eq-1]，忽略 [note:whatever]。"
    assert extract_citations(text) == ["val:000300:pe_pct", "cfa-l2-eq-1"]


def test_citation_accuracy_counts_invalid():
    text = "[snap:val:000300:pe_pct] [snap:made-up]"
    result = citation_accuracy(text, EVIDENCE)
    assert result["cited"] == 2
    assert result["score"] == 0.5
    assert result["invalid"] == ["made-up"]


def test_missing_citation_fails_when_required():
    assert citation_accuracy("no refs", EVIDENCE)["score"] == 0.0
    assert citation_accuracy("no refs", EVIDENCE, required=False)["score"] == 1.0


def test_format_pass_reports_missing_sections():
    result = format_pass("## 结论\n看多", ["结论", "证伪条件"])
    assert result["score"] == 0.5
    assert result["missing"] == ["证伪条件"]


def test_numeric_traceability_ignores_years():
    result = numeric_traceability("2024 年 PE 分位为 15.43%", [15.43])
    assert result["checked"] == 1
    assert result["score"] == 1.0


def test_numeric_traceability_flags_invented_numbers():
    result = numeric_traceability("PE 分位 42.0%", [15.43])
    assert result["score"] == 0.0
    assert result["untraceable"] == [42.0]


def test_numbers_inside_citation_ids_are_not_claims():
    text = "PE 分位 15.43% [snap:val:000300:pe_pct]"
    result = numeric_traceability(text, [15.43])
    assert result["checked"] == 1
    assert result["score"] == 1.0


def test_score_case_end_to_end():
    case = {
        "id": "c1",
        "type": "report",
        "required_sections": ["结论"],
        "forbidden": ["稳赚"],
        "required_citations": True,
    }
    good = score_case(case, "## 结论\n中性 [snap:val:000300:pe_pct]", EVIDENCE)
    assert good.passed, good.details

    bad = score_case(case, "稳赚", EVIDENCE)
    assert not bad.passed
    assert any("forbidden" in f for f in bad.details["failures"])


def test_golden_set_is_valid():
    from finagent.evals.run_evals import DEFAULT_GOLDEN

    cases = load_cases(DEFAULT_GOLDEN)
    assert len(cases) >= 10
    assert validate_cases(cases) == []


def test_loader_rejects_bad_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    try:
        load_cases(path)
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_validate_cases_flags_duplicates():
    cases = [
        {"id": "x", "type": "concept", "question": "q"},
        {"id": "x", "type": "concept", "question": "q"},
    ]
    assert any("duplicate id" in p for p in validate_cases(cases))
    assert json.dumps(cases[0])  # keep import used
