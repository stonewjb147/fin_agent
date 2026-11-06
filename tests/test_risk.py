"""Phase 7: risk limits, compliance terms and validation criteria."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from finagent.agent.evidence import build_evidence, build_facts
from finagent.agent.report import verify_report
from finagent.agent.template import render_template
from finagent.risk import (
    FORBIDDEN_TERMS,
    REQUIRED_TERMS,
    RiskPolicy,
    evaluate_risk,
    evaluate_validation,
    load_risk_policy,
    required_terms,
    run_risk,
)
from finagent.risk.pipeline import RiskError

AS_OF = "2024-06-28"


def _portfolio(weight: float = 1 / 15) -> dict:
    categories = ["broad"] * 8 + ["sector"] * 6 + ["bond"]
    holdings = [
        {"symbol": f"{510300 + i:06d}", "weight": weight, "category": category}
        for i, category in enumerate(categories)
    ]
    w = 1 / 15
    return {
        "n_symbols": 15,
        "n_holdings": len(holdings),
        "portfolio_vol": 0.15,
        "weighted_vol": 0.20,
        "policy": {
            "asset_cap": 0.12,
            "category_budget": {"broad": 8 * w, "sector": 6 * w, "bond": w},
        },
        "category_exposure": {"broad": 8 * w, "sector": 6 * w, "bond": w},
        "holdings": holdings,
    }


def _prices(amount: float = 1e8) -> pd.DataFrame:
    dates = pd.date_range(end=AS_OF, periods=60, freq="B")
    rows = []
    for i in range(15):
        for day in dates:
            rows.append(
                {"date": day, "symbol": f"{510300 + i:06d}", "amount": amount}
            )
    return pd.DataFrame(rows)


def _phase_eval(drawdown: float = -0.10) -> dict:
    return {
        "value": {
            "breadth": {"n_eff": 5.0, "avg_corr": 0.3},
            "strategies": {"policy_tilt": {"metrics": {"max_drawdown": drawdown}}},
        }
    }


def _factor(significant: bool = True) -> dict:
    return {"tests": [{"significant_neutral": significant}]}


def _evaluate(**overrides):
    payload = {
        "as_of": AS_OF,
        "portfolio": _portfolio(),
        "policy": RiskPolicy(),
        "prices": _prices(),
        "health": {"errors": 0, "warnings": 0},
        "phase_eval": _phase_eval(),
        "ledger": {"n_settled": 0},
        "factor": _factor(),
    }
    payload.update(overrides)
    return evaluate_risk(**payload)


def test_good_portfolio_passes_hard_and_soft_checks():
    result = _evaluate()

    assert result["status"] == "pass"
    assert result["counts"]["hard_failed"] == 0
    assert result["counts"]["soft_failed"] == 0
    assert result["policy_fingerprint"]


def test_asset_cap_breach_blocks_the_report():
    result = _evaluate(portfolio=_portfolio(weight=0.15))

    assert result["status"] == "blocked"
    assert "weights.asset_cap" in result["failed"]
    check = next(c for c in result["checks"] if c["id"] == "weights.asset_cap")
    assert check["passed"] is False


def test_missing_portfolio_is_a_hard_failure():
    result = _evaluate(portfolio=None)

    assert result["status"] == "blocked"
    assert "portfolio.present" in result["failed"]


def test_liquidity_breach_blocks_the_report():
    result = _evaluate(prices=_prices(amount=1e7))

    assert result["status"] == "blocked"
    assert "liquidity.min_adv" in result["failed"]


def test_health_errors_block_and_warnings_warn():
    errors = _evaluate(health={"errors": 1, "warnings": 0})
    warnings = _evaluate(health={"errors": 0, "warnings": 2})

    assert errors["status"] == "blocked"
    assert "data.health_errors" in errors["failed"]
    assert warnings["status"] == "warn"
    assert "data.health_warnings" in warnings["failed"]


def test_optional_artifacts_missing_do_not_block():
    result = _evaluate(phase_eval=None, health=None, prices=None)

    assert result["status"] == "pass"
    levels = {check["id"]: check["level"] for check in result["checks"]}
    assert levels["data.health_errors"] == "info"
    assert levels["liquidity.min_adv"] == "info"
    assert levels["portfolio.drawdown_budget"] == "info"


def test_soft_n_eff_breach_warns_but_does_not_block():
    result = _evaluate(phase_eval=_phase_eval() | {"value": {"breadth": {"n_eff": 2.0, "avg_corr": 0.3}}})

    assert result["status"] == "warn"
    assert "concentration.n_eff" in result["failed"]


def test_validation_lists_exactly_what_is_missing():
    result = _evaluate()
    validation = result["validation"]

    assert validation["validated"] is False
    assert validation["eligible"] is False
    assert "settled_samples" in validation["remaining"]
    assert "hit_rate_excess" in validation["remaining"]
    assert "mean_directional_excess" in validation["remaining"]
    assert "factor_significant" not in validation["remaining"]


def test_validation_is_eligible_only_when_every_criterion_passes():
    validation = evaluate_validation(
        policy=RiskPolicy(),
        ledger={
            "n_settled": 400,
            "hit_rate_excess": 0.6,
            "mean_directional_excess": 0.01,
        },
        factor=_factor(significant=True),
        phase_eval=_phase_eval(),
        risk_status="pass",
    )

    assert validation["eligible"] is True
    assert validation["remaining"] == []
    assert validation["validated"] is False  # a human still decides


def test_risk_policy_rejects_unknown_keys(tmp_path):
    path = tmp_path / "risk.yaml"
    path.write_text("name: x\nnot_a_limit: 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown risk policy keys"):
        load_risk_policy(path)


def test_compliance_terms_have_one_source():
    assert required_terms() == list(REQUIRED_TERMS)
    assert "风控阻断" in required_terms("blocked")
    assert "风控阻断" not in required_terms("warn")

    from finagent.agent.prompts import FORBIDDEN, MUST_INCLUDE

    assert tuple(FORBIDDEN) == FORBIDDEN_TERMS
    assert tuple(MUST_INCLUDE) == REQUIRED_TERMS


def test_run_risk_writes_json_and_requires_portfolio(tmp_path):
    data = tmp_path / "data"
    (data / "portfolio").mkdir(parents=True)
    (data / "portfolio" / f"{AS_OF}.json").write_text(
        json.dumps(_portfolio()), encoding="utf-8"
    )

    result = run_risk(AS_OF, data_dir=data)

    path = data / "quality" / f"risk_{AS_OF}.json"
    assert path.exists()
    assert result["risk_file"] == str(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] in {"pass", "warn", "blocked"}
    assert saved["validation"]["validated"] is False

    empty = tmp_path / "empty"
    with pytest.raises(RiskError, match="run `finagent portfolio"):
        run_risk(AS_OF, data_dir=empty)


def test_blocked_risk_requires_the_block_term_in_reports(tmp_path):
    data = tmp_path / "data"
    (data / "signals").mkdir(parents=True)
    (data / "portfolio").mkdir(parents=True)
    (data / "quality").mkdir(parents=True)
    signals = {
        "as_of": AS_OF,
        "n_symbols": 1,
        "n_scored": 1,
        "n_signals": 1,
        "horizon": 20,
        "execution_lag": 1,
        "overlays": {"news": {"available": False}},
        "ledger_summary": {"n_predictions": 1, "n_pending": 1, "n_settled": 0},
        "signals": [
            {
                "symbol": "510300",
                "name": "沪深300ETF",
                "category": "broad",
                "direction": 1,
                "composite": 0.9,
                "confidence": 0.8,
            }
        ],
    }
    (data / "signals" / f"{AS_OF}.json").write_text(
        json.dumps(signals), encoding="utf-8"
    )
    (data / "portfolio" / f"{AS_OF}.json").write_text(
        json.dumps(_portfolio()), encoding="utf-8"
    )
    blocked = _evaluate(portfolio=_portfolio(weight=0.15))
    (data / "quality" / f"risk_{AS_OF}.json").write_text(
        json.dumps(blocked), encoding="utf-8"
    )

    facts = build_facts(AS_OF, data_dir=data)
    bundle = build_evidence(facts)
    text = render_template(bundle, facts)

    assert bundle.risk_status == "blocked"
    assert "风控阻断" in text
    assert verify_report(text, bundle)["passed"]

    without = text.replace("风控阻断", "风控提示")
    assert not verify_report(without, bundle)["passed"]
