"""Phase 8-10: growth state, decision journal and periodic review."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finagent.data.cache import ParquetCache
from finagent.growth import (
    DecisionJournal,
    JournalError,
    build_growth_review,
    build_growth_state,
    render_growth_review,
    run_growth,
    run_growth_review,
    run_journal_review,
)

AS_OF = "2024-06-28"
DATES = pd.bdate_range(end=AS_OF, periods=30)


def _write(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _data(tmp_path: Path, *, complete: bool = True, risk_status: str = "warn") -> Path:
    data = tmp_path / "data"
    risk = {
        "as_of": AS_OF,
        "status": risk_status,
        "counts": {"total": 3, "hard": 2, "soft": 1, "info": 0, "hard_failed": 1 if risk_status == "blocked" else 0, "soft_failed": 1 if risk_status == "warn" else 0},
        "failed": ["concentration.n_eff"] if risk_status == "warn" else ["weights.asset_cap"] if risk_status == "blocked" else [],
        "policy": {"min_settled_samples": 385},
        "policy_fingerprint": "abc123",
        "validation": {
            "validated": False,
            "eligible": False,
            "remaining": ["settled_samples"],
            "criteria": [
                {"id": "settled_samples", "actual": 0, "required": 385, "passed": False},
                {"id": "risk_not_blocked", "actual": risk_status, "required": "not blocked", "passed": risk_status != "blocked"},
            ],
        },
    }
    report = {
        "as_of": AS_OF,
        "mode": "template",
        "fallback_reason": "DEEPSEEK_API_KEY not configured",
        "checks": {"passed": True},
    }
    signals = {
        "as_of": AS_OF,
        "ledger_summary": {"n_predictions": 1, "n_pending": 1, "n_settled": 0},
    }
    if complete:
        _write(data / f"quality/collect_{AS_OF}.json", {"as_of": AS_OF})
        _write(data / f"quality/factor_report_{AS_OF}.json", {"tests": []})
        _write(data / f"quality/health_{AS_OF}.json", {"errors": 0, "warnings": 0})
    _write(data / f"signals/{AS_OF}.json", signals)
    if complete:
        _write(data / f"portfolio/{AS_OF}.json", {"holdings": []})
        _write(data / f"quality/risk_{AS_OF}.json", risk)
        _write(data / f"reports/report_{AS_OF}.json", report)
    return data


def _calendar(data: Path) -> None:
    path = data / "cache/trade_calendar/all.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": DATES}).to_parquet(path, index=False)


def test_complete_day_is_level_two_with_honest_zero_evidence(tmp_path):
    data = _data(tmp_path)
    _calendar(data)
    state = build_growth_state(AS_OF, data_dir=data)

    assert state["dimensions"]["process"]["score"] == 100
    assert state["dimensions"]["evidence"]["score"] == 0
    assert state["dimensions"]["risk"]["score"] == 70
    assert state["dimensions"]["data"]["score"] == 100
    assert state["level"]["id"] == "L2"
    assert state["level"]["score"] == 62
    assert state["validation"]["validated"] is False


def test_missing_artifacts_lower_process_and_create_actions(tmp_path):
    data = _data(tmp_path, complete=False)
    state = build_growth_state(AS_OF, data_dir=data)

    assert state["dimensions"]["process"]["passed"] == 1
    assert "collect" in state["dimensions"]["process"]["missing"]
    assert state["actions"][0]["id"] == "pipeline.missing"
    assert state["actions"][0]["priority"] == "high"


def test_blocked_risk_is_a_high_priority_action(tmp_path):
    data = _data(tmp_path, risk_status="blocked")
    state = build_growth_state(AS_OF, data_dir=data)

    assert state["dimensions"]["risk"]["score"] == 0
    assert state["dimensions"]["risk"]["status"] == "blocked"
    assert any(a["id"] == "risk.blocked" and a["priority"] == "high" for a in state["actions"])


def test_settled_samples_move_the_evidence_dimension(tmp_path):
    data = _data(tmp_path)
    signals = json.loads((data / f"signals/{AS_OF}.json").read_text(encoding="utf-8"))
    signals["ledger_summary"]["n_settled"] = 385
    _write(data / f"signals/{AS_OF}.json", signals)
    state = build_growth_state(AS_OF, data_dir=data)

    assert state["dimensions"]["evidence"]["score"] == 100
    assert state["level"]["id"] == "L4"


def test_activity_and_streak_count_complete_days(tmp_path):
    data = _data(tmp_path)
    _calendar(data)
    # Add the three preceding sessions as complete days.
    for day in DATES[-4:-1]:
        key = day.date().isoformat()
        _write(data / f"signals/{key}.json", {"ledger_summary": {"n_settled": 0}})
        _write(data / f"portfolio/{key}.json", {"holdings": []})
        _write(data / f"quality/risk_{key}.json", {"status": "pass"})
        _write(data / f"reports/report_{key}.json", {"checks": {"passed": True}})
    state = build_growth_state(AS_OF, data_dir=data)

    assert state["activity"]["complete_days"] == 4
    assert state["activity"]["streak_days"] == 4
    assert state["activity"]["counts"]["report"] == 4


def test_milestones_record_the_first_artifacts(tmp_path):
    data = _data(tmp_path)
    state = build_growth_state(AS_OF, data_dir=data)
    achieved = {item["id"]: item["achieved"] for item in state["milestones"]}

    assert achieved["first_signal"] is True
    assert achieved["first_report"] is True
    assert achieved["first_risk"] is True
    assert achieved["first_settled"] is False


def test_journal_requires_a_rationale(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    with pytest.raises(JournalError, match="rationale is required"):
        journal.add(as_of=AS_OF, action="watch", rationale="   ")


def test_journal_rejects_unknown_action_and_bad_confidence(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    with pytest.raises(JournalError, match="unknown action"):
        journal.add(as_of=AS_OF, action="buy", rationale="x")
    with pytest.raises(JournalError, match="confidence"):
        journal.add(as_of=AS_OF, action="watch", rationale="x", confidence=1.5)


def test_journal_ids_are_unique_and_append_only(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    first = journal.add(as_of=AS_OF, action="watch", rationale="first")
    second = journal.add(as_of=AS_OF, action="watch", rationale="second")

    assert first["decision_id"] != second["decision_id"]
    assert len(journal.load()) == 2
    with pytest.raises(JournalError, match="already exists"):
        journal.add(as_of=AS_OF, action="watch", rationale="third", decision_id=first["decision_id"])


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2024-06-03", periods=30)
    # 510300 rises 1% a day, 512880 rises 0.3%, 511010 is flat.
    return pd.DataFrame(
        {
            "510300": 3.0 * np.cumprod(np.full(len(dates), 1.01)),
            "512880": 2.0 * np.cumprod(np.full(len(dates), 1.003)),
            "511010": 100.0 * np.ones(len(dates)),
        },
        index=dates,
    )


def test_journal_review_bullish_hit_and_summary(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    journal.add(as_of="2024-06-03", action="add", rationale="momentum", symbol="510300", review_days=5)

    new = journal.review(_prices(), "2024-07-12", universe_symbols=["510300", "512880", "511010"])
    summary = journal.summary("2024-07-12")

    assert len(new) == 1
    assert new.iloc[0]["outcome"] == "hit"
    assert summary["n_reviewed"] == 1
    assert summary["hit_rate_excess"] == 1.0
    assert summary["mean_directional_excess"] > 0


def test_journal_review_bearish_on_a_rising_market_is_a_miss(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    journal.add(as_of="2024-06-03", action="exit", rationale="risk off", symbol="510300", review_days=5)

    new = journal.review(_prices(), "2024-07-12", universe_symbols=["510300", "512880", "511010"])

    assert new.iloc[0]["outcome"] == "miss"
    assert new.iloc[0]["direction"] == -1


def test_journal_review_neutral_decisions_are_observed_not_scored(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    journal.add(as_of="2024-06-03", action="watch", rationale="wait", symbol="510300", review_days=5)

    new = journal.review(_prices(), "2024-07-12", universe_symbols=["510300", "512880", "511010"])
    summary = journal.summary("2024-07-12")

    assert new.iloc[0]["outcome"] == "observed"
    assert summary["n_directional_reviewed"] == 0
    assert summary["hit_rate_excess"] is None


def test_journal_review_never_peeks_past_as_of(tmp_path):
    journal = DecisionJournal(tmp_path / "journal")
    journal.add(as_of="2024-06-03", action="add", rationale="early", symbol="510300", review_days=20)

    new = journal.review(_prices(), "2024-06-20", universe_symbols=["510300"])

    assert new.empty
    assert journal.summary("2024-06-20")["n_pending"] == 1


def test_growth_review_contains_actions_and_lessons(tmp_path):
    data = _data(tmp_path)
    _calendar(data)
    state = build_growth_state(AS_OF, data_dir=data)
    review = build_growth_review(state, window=30)
    markdown = render_growth_review(review)

    assert review["level"]["id"] == "L2"
    assert "## 一页结论" in markdown
    assert "## 下一周的行动" in markdown
    assert "## 学习卡" in markdown
    assert "validated=false" in markdown
    assert "没有结算样本" in markdown


def test_run_growth_and_review_write_artifacts(tmp_path):
    data = _data(tmp_path)
    state = run_growth(AS_OF, data_dir=data)
    review = run_growth_review(AS_OF, data_dir=data)

    assert Path(state["growth_file"]).exists()
    assert Path(review["files"]["markdown"]).exists()
    assert Path(review["files"]["json"]).exists()
    saved = json.loads(Path(review["files"]["json"]).read_text(encoding="utf-8"))
    assert saved["level"]["score"] == 62


def test_run_journal_review_uses_cache_and_writes_json(tmp_path):
    data = _data(tmp_path)
    journal = DecisionJournal(data / "journal")
    journal.add(as_of="2024-06-03", action="add", rationale="test", symbol="510300", review_days=5)

    cache = ParquetCache(data / "cache")
    dates = pd.bdate_range("2024-06-03", periods=30)
    for i, symbol in enumerate(["510300", "512880", "511010"]):
        frame = pd.DataFrame(
            {
                "date": dates,
                "close": 3.0 * np.cumprod(np.full(len(dates), 1.01 - i * 0.004)),
                "amount": 1e8,
            }
        )
        cache.write("etf_daily_hfq", symbol, frame, source="test")

    result = run_journal_review(
        "2024-07-12",
        data_dir=data,
        universe_symbols=["510300", "512880", "511010"],
    )

    assert result["n_new_reviews"] == 1
    assert Path(result["review_file"]).exists()
    assert result["summary"]["n_reviewed"] == 1
