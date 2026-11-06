"""Phase 6: grounded report generation, gates and deterministic fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finagent.agent.evidence import EvidenceError, build_evidence, build_facts
from finagent.agent.llm import LLMConfig, LLMError
from finagent.agent.prompts import FORBIDDEN, MUST_INCLUDE, REQUIRED_SECTIONS
from finagent.agent.report import generate_report, verify_report
from finagent.agent.template import render_template

AS_OF = "2024-06-28"


def _payloads() -> dict[str, dict]:
    signals = {
        "as_of": AS_OF,
        "universe_version": "u-test",
        "n_symbols": 3,
        "n_scored": 3,
        "n_signals": 2,
        "horizon": 20,
        "execution_lag": 1,
        "overlays": {"news": {"available": False, "reason": "no news file"}},
        "ledger_summary": {"n_predictions": 2, "n_pending": 2, "n_settled": 0},
        "signals": [
            {
                "symbol": "510300",
                "name": "沪深300ETF",
                "category": "broad",
                "direction": 1,
                "composite": 0.9,
                "confidence": 0.8,
            },
            {
                "symbol": "512880",
                "name": "证券ETF",
                "category": "sector",
                "direction": -1,
                "composite": -0.7,
                "confidence": 0.6,
            },
        ],
    }
    portfolio = {
        "n_symbols": 3,
        "n_holdings": 2,
        "portfolio_vol": 0.15,
        "weighted_vol": 0.2,
        "policy": {"asset_cap": 0.12, "category_budget": {"broad": 0.5, "sector": 0.5}},
        "category_exposure": {"broad": 0.5, "sector": 0.5},
        "holdings": [
            {"symbol": "510300", "name": "沪深300ETF", "weight": 0.5},
            {"symbol": "512880", "name": "证券ETF", "weight": 0.5},
        ],
    }
    factor = {
        "meta": {"n_factors": 1, "fdr_q": 0.1},
        "tests": [
            {
                "factor": "momentum_20",
                "horizon": 20,
                "ic_mean_neutral": 0.01,
                "q_value_neutral": 0.6,
                "significant_neutral": False,
            }
        ],
    }
    health = {"errors": 0, "warnings": 0}
    phase_eval = {
        "value": {
            "breadth": {"n_eff": 2.5, "avg_corr": 0.4},
            "strategies": {
                "equal_weight": {"metrics": {"cagr": 0.08, "max_drawdown": -0.2}}
            },
            "benchmarks": {
                "hs300_buyhold": {"metrics": {"cagr": 0.03, "max_drawdown": -0.19}}
            },
            "ledger": {"required_settled_5pct": 385},
        }
    }
    return {
        "signals": signals,
        "portfolio": portfolio,
        "factor": factor,
        "health": health,
        "phase_eval": phase_eval,
    }


def _write_artifacts(root: Path, payloads: dict[str, dict] | None = None) -> Path:
    payloads = payloads or _payloads()
    data = root / "data"
    files = {
        "signals": data / "signals" / f"{AS_OF}.json",
        "portfolio": data / "portfolio" / f"{AS_OF}.json",
        "factor": data / "quality" / f"factor_report_{AS_OF}.json",
        "health": data / "quality" / f"health_{AS_OF}.json",
        "phase_eval": data / "quality" / f"phase_eval_{AS_OF}.json",
    }
    for kind, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payloads[kind], ensure_ascii=False), encoding="utf-8")
    return data


def _good_text(root: Path) -> str:
    data = _write_artifacts(root)
    facts = build_facts(AS_OF, data_dir=data)
    return render_template(build_evidence(facts), facts)


class FakeClient:
    model = "fake-model"

    def __init__(self, answers: list[str]):
        self.answers = answers
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def test_evidence_ids_are_unique_and_values_finite(tmp_path):
    data = _write_artifacts(tmp_path)
    bundle = build_evidence(build_facts(AS_OF, data_dir=data))

    ids = bundle.ids
    assert len(ids) == len(set(ids))
    assert all(isinstance(item.value, float) for item in bundle.items)
    assert "signals:2024-06-28:n_signals" in ids
    assert "portfolio:2024-06-28:portfolio_vol_pct" in ids
    assert bundle.by_id("portfolio:2024-06-28:portfolio_vol_pct").value == pytest.approx(15.0)
    assert 510300.0 in bundle.ignore_values
    assert "hs300_buyhold" in bundle.ignore_terms


def test_missing_signals_raise_a_clear_error(tmp_path):
    with pytest.raises(EvidenceError, match="run `finagent signals"):
        build_facts(AS_OF, data_dir=tmp_path / "data")


def test_template_passes_the_same_gates_as_the_llm(tmp_path):
    data = _write_artifacts(tmp_path)
    facts = build_facts(AS_OF, data_dir=data)
    bundle = build_evidence(facts)
    text = render_template(bundle, facts)

    checks = verify_report(text, bundle)
    assert checks["passed"], checks["failures"]
    for section in REQUIRED_SECTIONS:
        assert section in text
    for term in MUST_INCLUDE:
        assert term in text
    for term in FORBIDDEN:
        assert term not in text


def test_extra_precision_the_evidence_never_had_is_rejected(tmp_path):
    data = _write_artifacts(tmp_path)
    facts = build_facts(AS_OF, data_dir=data)
    bundle = build_evidence(facts)
    text = render_template(bundle, facts)
    tampered = text.replace("0.90 [snap:signal:510300:composite]", "0.90341 [snap:signal:510300:composite]")

    checks = verify_report(tampered, bundle)
    assert not checks["passed"]
    assert any("untraceable numbers" in failure for failure in checks["failures"])


def test_template_still_works_when_optional_artifacts_are_missing(tmp_path):
    payloads = _payloads()
    data = tmp_path / "data"
    path = data / "signals" / f"{AS_OF}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payloads["signals"], ensure_ascii=False), encoding="utf-8")

    result = generate_report(AS_OF, use_llm=False, data_dir=data, write=False)
    assert result.mode == "template"
    assert result.checks["passed"]
    assert "组合文件" in result.text


def test_good_llm_answer_is_used_and_written(tmp_path):
    root = tmp_path / "case"
    good = _good_text(root)
    data = root / "data"
    client = FakeClient([good])

    result = generate_report(
        AS_OF,
        client=client,
        data_dir=data,
        out_dir=tmp_path / "out",
        write=True,
    )

    assert result.mode == "llm"
    assert result.attempts == 1
    assert client.calls == 1
    assert result.checks["passed"]
    assert (tmp_path / "out" / f"report_{AS_OF}.md").read_text(encoding="utf-8") == good
    payload = json.loads((tmp_path / "out" / f"report_{AS_OF}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "llm"
    assert payload["model"] == "fake-model"
    assert payload["prompt_sha256"]
    assert payload["files"]["markdown"].endswith(f"report_{AS_OF}.md")


def test_hallucinated_number_is_rejected_then_falls_back(tmp_path):
    root = tmp_path / "case"
    good = _good_text(root)
    bad = good + "\n组合未来收益 999.99%。\n"
    client = FakeClient([bad, bad])

    result = generate_report(
        AS_OF,
        client=client,
        data_dir=root / "data",
        out_dir=tmp_path / "out",
    )

    assert client.calls == 2  # one repair attempt
    assert result.mode == "template"
    assert result.attempts == 2
    assert "rejected" in result.fallback_reason
    assert "999.99" not in result.text
    assert result.checks["passed"]


def test_missing_api_key_degrades_to_template(tmp_path, monkeypatch):
    root = tmp_path / "case"
    _good_text(root)
    monkeypatch.setattr(
        "finagent.agent.report.config_from_env",
        lambda: LLMConfig(api_key=""),
    )

    result = generate_report(AS_OF, data_dir=root / "data", out_dir=tmp_path / "out")

    assert result.mode == "template"
    assert "DEEPSEEK_API_KEY" in result.fallback_reason


def test_llm_error_degrades_to_template(tmp_path):
    root = tmp_path / "case"
    _good_text(root)

    class Broken:
        model = "broken"

        def complete(self, system: str, user: str) -> str:
            raise LLMError("request failed: ConnectionError")

    result = generate_report(
        AS_OF,
        client=Broken(),
        data_dir=root / "data",
        out_dir=tmp_path / "out",
    )

    assert result.mode == "template"
    assert "ConnectionError" in result.fallback_reason


def test_written_metadata_never_contains_the_api_key(tmp_path, monkeypatch):
    root = tmp_path / "case"
    good = _good_text(root)
    secret = "sk-test-do-not-write"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    result = generate_report(
        AS_OF,
        client=FakeClient([good]),
        data_dir=root / "data",
        out_dir=tmp_path / "out",
    )

    assert result.mode == "llm"
    blob = (tmp_path / "out" / f"report_{AS_OF}.json").read_text(encoding="utf-8")
    assert secret not in blob
    assert secret not in result.text
