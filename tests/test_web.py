"""Web front end: artefact accessors, table builders and command construction."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from finagent.growth import DecisionJournal
from finagent.web import data as D
from finagent.web.runner import build_command, display_command, run_step

AS_OF = "2024-06-28"


def _write(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    risk = {
        "as_of": AS_OF,
        "status": "warn",
        "counts": {
            "total": 2,
            "hard": 1,
            "soft": 1,
            "info": 0,
            "hard_failed": 0,
            "soft_failed": 1,
        },
        "failed": ["concentration.n_eff"],
        "policy_fingerprint": "abc123",
        "checks": [
            {
                "id": "portfolio.present",
                "level": "hard",
                "passed": True,
                "message": "49 个持仓",
                "value": 49,
                "limit": None,
                "source": "portfolio",
            },
            {
                "id": "concentration.n_eff",
                "level": "soft",
                "passed": False,
                "message": "有效标的 2.64",
                "value": 2.64,
                "limit": 3.0,
                "source": "prices",
            },
        ],
        "validation": {
            "validated": False,
            "eligible": False,
            "remaining": ["settled_samples"],
            "criteria": [
                {
                    "id": "settled_samples",
                    "description": "结算样本",
                    "actual": 0,
                    "required": 385,
                    "passed": False,
                },
                {
                    "id": "drawdown_budget",
                    "description": "最大回撤",
                    "actual": -0.180695,
                    "required": "-20%",
                    "passed": True,
                },
            ],
        },
    }
    signals = {
        "as_of": AS_OF,
        "n_signals": 2,
        "ledger_summary": {"n_predictions": 2, "n_settled": 0, "n_pending": 2},
        "signals": [
            {
                "signal_id": "s1",
                "symbol": "510300",
                "name": "沪深300ETF",
                "category": "broad",
                "direction": 1,
                "composite": 1.2,
                "confidence": 0.8,
                "horizon": 20,
                "thesis": "动量占优",
                "evidence": [{"factor": "momentum_20", "value": 0.1, "z": 1.5, "direction": 1, "contribution": 1.5}],
                "invalidation": [{"condition": "得分翻向"}],
            },
            {
                "signal_id": "s2",
                "symbol": "512880",
                "name": "证券ETF",
                "category": "sector",
                "direction": -1,
                "composite": -0.6,
                "confidence": 0.7,
                "horizon": 20,
                "thesis": "反转偏弱",
                "evidence": [],
                "invalidation": [],
            },
        ],
    }
    portfolio = {
        "as_of": AS_OF,
        "policy": {"name": "rp-tilt-v1", "category_budget": {"broad": 0.6, "sector": 0.4}},
        "category_exposure": {"broad": 0.55, "sector": 0.45},
        "portfolio_vol": 0.14,
        "weighted_vol": 0.2,
        "n_holdings": 2,
        "notes": "long only",
        "holdings": [
            {"symbol": "512880", "name": "证券ETF", "category": "sector", "weight": 0.2, "vol": 0.3, "composite": -0.6, "tilt": 0.8},
            {"symbol": "510300", "name": "沪深300ETF", "category": "broad", "weight": 0.7, "vol": 0.15, "composite": 1.2, "tilt": 1.2},
        ],
    }
    report = {
        "as_of": AS_OF,
        "mode": "llm",
        "model": "deepseek-chat",
        "attempts": 1,
        "checks": {
            "passed": True,
            "failures": [],
            "sections": [{"title": "结论"}],
            "citation": {"score": 1.0, "cited": 12, "valid": 12},
            "numeric_strict": {"score": 1.0, "checked": 9, "untraceable": []},
            "must_include_missing": [],
            "forbidden_hits": [],
        },
        "evidence": {
            "items": [
                {"id": "signals:n", "label": "标的数", "value": 50.0, "unit": "只", "note": ""}
            ]
        },
        "text": "结论 [snap:signals:n] 共 50 只。",
    }
    health = {
        "as_of": AS_OF,
        "last_trading_day": AS_OF,
        "ok": True,
        "errors": 0,
        "warnings": 0,
        "checks": [
            {
                "dataset": "etf_daily_hfq",
                "key": "510300",
                "level": "ok",
                "last_date": AS_OF,
                "lag_days": 0,
                "rows": 100,
                "null_ratio": 0.0,
                "message": "",
            }
        ],
    }
    factor = {
        "as_of": AS_OF,
        "n_symbols": 50,
        "meta": {"m_tests": 3, "fdr_q": 0.1},
        "tests": [
            {
                "factor": "momentum_20",
                "horizon": 20,
                "ic_mean_neutral": 0.02,
                "nw_t_neutral": 1.4,
                "icir_neutral": 0.6,
                "q_value_neutral": 0.3,
                "significant_neutral": False,
                "dsr_neutral": 0.4,
                "coverage": 0.99,
            }
        ],
    }
    backtest = {
        "window": {"start": "2023-01-01", "end": AS_OF},
        "cost_model": {"one_way_bps": 7},
        "policy_fingerprint": "p1",
        "strategies": {
            "policy_tilt": {
                "metrics": {
                    "cagr": 0.08,
                    "ann_vol": 0.15,
                    "sharpe": 0.4,
                    "max_drawdown": -0.18,
                    "annual_turnover": 1.8,
                    "annual_cost": 0.003,
                    "blocked_fills": 4,
                }
            }
        },
        "diagnostics": {
            "pbo": {"pbo": 0.86},
            "dsr": {"policy_tilt": 0.5},
            "dsr_trials": 4,
            "cpcv": {
                "groups": 8,
                "test_blocks": 2,
                "summary": {"policy_tilt": {"p05": -0.42}},
            },
        },
    }
    _write(data / f"signals/{AS_OF}.json", signals)
    _write(data / f"portfolio/{AS_OF}.json", portfolio)
    _write(data / f"quality/risk_{AS_OF}.json", risk)
    _write(data / f"reports/report_{AS_OF}.json", report)
    (data / f"reports/report_{AS_OF}.md").write_text("# 报告\n\n正文\n", encoding="utf-8")
    _write(data / f"quality/health_{AS_OF}.json", health)
    _write(data / f"quality/factor_report_{AS_OF}.json", factor)
    _write(data / f"reports/backtest_{AS_OF}.json", backtest)
    _write(data / f"quality/collect_{AS_OF}.json", {"dataset_count": 2, "ok": True, "failures": []})
    return data


def test_available_dates_unions_core_artifacts(tmp_path):
    data = _fixture(tmp_path)
    _write(data / "signals/2024-06-27.json", {"signals": []})
    _write(data / "growth/growth_2024-06-26.json", {"level": {"id": "L2"}})

    assert D.available_dates(data) == ["2024-06-28", "2024-06-27", "2024-06-26"]


def test_load_bundle_reads_artifacts_and_derives_growth(tmp_path):
    data = _fixture(tmp_path)
    DecisionJournal(data / "journal").add(
        as_of="2024-06-03", action="watch", rationale="wait", symbol="510300"
    )
    bundle = D.load_bundle(AS_OF, data)

    assert bundle["signals"]["n_signals"] == 2
    assert bundle["report_markdown"].startswith("# 报告")
    assert bundle["growth"]["dimensions"]["process"]["passed"] == 7
    assert bundle["journal"]["n_entries"] == 1
    assert bundle["paths"]["risk"].endswith(f"risk_{AS_OF}.json")
    assert bundle["report"]["checks"]["passed"] is True


def test_signals_and_holdings_frames(tmp_path):
    data = _fixture(tmp_path)
    bundle = D.load_bundle(AS_OF, data)

    signals = D.signals_frame(bundle["signals"])
    assert list(signals["方向"]) == ["看多", "看空"]
    assert signals.loc[0, "类别"] == "宽基"

    holdings = D.holdings_frame(bundle["portfolio"])
    assert list(holdings["代码"]) == ["510300", "512880"]
    assert holdings.loc[0, "权重"] == pytest.approx(0.7)

    exposure = D.category_exposure_frame(bundle["portfolio"])
    drift = exposure.set_index("类别").loc["行业", "偏离"]
    assert drift == pytest.approx(0.05)


def test_risk_frames_mark_pass_and_fail(tmp_path):
    data = _fixture(tmp_path)
    bundle = D.load_bundle(AS_OF, data)

    checks = D.risk_checks_frame(bundle["risk"])
    assert list(checks["结果"]) == ["✅", "❌"]

    validation = D.validation_frame(bundle["risk"])
    assert list(validation["结果"]) == ["❌", "✅"]
    assert validation.loc[0, "条件"] == "settled_samples"


def test_health_factor_and_strategy_frames(tmp_path):
    data = _fixture(tmp_path)
    bundle = D.load_bundle(AS_OF, data)

    health = D.health_frame(bundle["health"])
    assert health.loc[0, "级别"] == "正常"

    factor = D.factor_frame(bundle["factor_report"], horizon=20)
    assert len(factor) == 1
    assert factor.loc[0, "显著"] == "—"

    strategies = D.strategies_frame(bundle["backtest"])
    assert strategies.loc[0, "策略"] == "政策权重 + 倾斜"
    diagnostics = D.backtest_diagnostics(bundle["backtest"])
    assert diagnostics["pbo"] == pytest.approx(0.86)
    assert diagnostics["cpcv_p05"]["policy_tilt"] == pytest.approx(-0.42)


def test_journal_frames_and_labels(tmp_path):
    data = _fixture(tmp_path)
    journal = DecisionJournal(data / "journal")
    journal.add(as_of="2024-06-03", action="watch", rationale="wait", symbol="510300")

    entries = D.journal_entries_frame(journal.load())
    assert entries.loc[0, "动作"] == "观察"
    assert entries.loc[0, "范围"] == "标的"

    reviews = D.journal_reviews_frame(journal.reviews())
    assert reviews.empty
    assert list(reviews.columns)[-1] == "结果"


def test_text_and_number_formatters():
    assert D.strip_citations("共 50 只 [snap:a:b] 标的") == "共 50 只 标的"
    assert D.pct(0.1234) == "12.34%"
    assert D.pct(None) == "—"
    assert D.money_cn(157_000_000) == "1.57 亿"
    assert D.num(1.23456, 3) == "1.235"


def test_build_command_uses_the_requested_date_and_interpreter():
    command = build_command("signals", AS_OF)
    assert command[1:] == ["-m", "finagent.cli", "signals", "--date", AS_OF]

    report = build_command("report", AS_OF, no_llm=True)
    assert report[-1] == "--no-llm"
    assert AS_OF in display_command("report", AS_OF)


def test_run_step_passes_data_dir_and_combines_output(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="warn\n")

    monkeypatch.setattr("finagent.web.runner.subprocess.run", fake_run)
    result = run_step("health", AS_OF, data_dir=tmp_path)

    assert result["ok"] is True
    assert result["output"] == "ok\nwarn"
    assert captured["kwargs"]["env"]["FINAGENT_DATA_DIR"] == str(tmp_path)
    assert captured["kwargs"]["cwd"].name == "fin_agent_projects"


def test_unknown_step_is_a_key_error():
    with pytest.raises(KeyError):
        build_command("nope", AS_OF)


def test_streamlit_overview_renders_without_exceptions(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from finagent import config as runtime_config

    data = _fixture(tmp_path)
    monkeypatch.setattr(runtime_config, "DATA_DIR", data)
    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "finagent/web/app.py"
    app = AppTest.from_file(str(app_path), default_timeout=60)
    app.run()

    assert not list(app.exception)
    assert any(title.value == "今日总览" for title in app.title)


def test_frames_are_empty_without_payloads():
    assert D.signals_frame(None).empty
    assert D.holdings_frame(None).empty
    assert D.risk_checks_frame(None).empty
    assert D.factor_frame(None).empty
    assert D.strategies_frame(None).empty
    assert D.validation_frame(None).empty
