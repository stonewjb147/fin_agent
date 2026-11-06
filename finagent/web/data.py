"""Read-only accessors and table builders for the web front end.

No Streamlit imports here: the UI in ``app.py`` composes these functions and the
tests exercise them without a browser. Everything reads artefacts already
produced by the CLI; nothing here fetches data or calls a model.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from finagent import config
from finagent.growth import build_growth_state
from finagent.growth.journal import ACTION_LABELS, DecisionJournal

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CITATION = re.compile(r"\[snap:[^\]]+\]")

CATEGORY_LABELS = {
    "broad": "宽基",
    "sector": "行业",
    "thematic": "主题",
    "bond": "债券",
    "cross_border": "跨境",
    "commodity": "商品",
}

RISK_LABELS = {
    "pass": "通过",
    "warn": "警告",
    "blocked": "阻断",
    "not_run": "未运行",
}

HEALTH_LEVEL_LABELS = {"ok": "正常", "warning": "警告", "error": "错误"}

DIRECTION_LABELS = {1: "看多", -1: "看空", 0: "中性"}

STRATEGY_LABELS = {
    "equal_weight": "池内等权",
    "policy_no_tilt": "政策权重（无倾斜）",
    "policy_tilt": "政策权重 + 倾斜",
    "top_10": "因子 Top10",
}


def read_json(path: str | Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_text(path: str | Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _date_of(stem: str) -> str | None:
    match = _ISO_DATE.search(stem)
    return match.group(0) if match else None


def available_dates(data_dir: str | Path | None = None) -> list[str]:
    """Every date that produced at least one core artefact, newest first."""
    data_dir = Path(data_dir or config.DATA_DIR)
    dates: set[str] = set()
    patterns = (
        "signals/*.json",
        "portfolio/*.json",
        "reports/report_*.json",
        "quality/risk_*.json",
        "growth/growth_*.json",
    )
    for pattern in patterns:
        for path in data_dir.glob(pattern):
            day = _date_of(path.stem)
            if day:
                dates.add(day)
    return sorted(dates, reverse=True)


def artifact_paths(as_of: str, data_dir: str | Path | None = None) -> dict[str, Path]:
    data_dir = Path(data_dir or config.DATA_DIR)
    return {
        "collect": data_dir / "quality" / f"collect_{as_of}.json",
        "factor_report": data_dir / "quality" / f"factor_report_{as_of}.json",
        "signals": data_dir / "signals" / f"{as_of}.json",
        "portfolio": data_dir / "portfolio" / f"{as_of}.json",
        "risk": data_dir / "quality" / f"risk_{as_of}.json",
        "report": data_dir / "reports" / f"report_{as_of}.json",
        "report_markdown": data_dir / "reports" / f"report_{as_of}.md",
        "health": data_dir / "quality" / f"health_{as_of}.json",
        "growth": data_dir / "growth" / f"growth_{as_of}.json",
        "growth_review_markdown": data_dir / "growth" / f"review_{as_of}.md",
        "growth_review_json": data_dir / "growth" / f"review_{as_of}.json",
        "journal_review": data_dir / "journal" / f"review_{as_of}.json",
        "backtest": data_dir / "reports" / f"backtest_{as_of}.json",
    }


def load_bundle(as_of: str, data_dir: str | Path | None = None) -> dict[str, Any]:
    """Load every artefact for one date plus derived growth and journal state."""
    data_dir = Path(data_dir or config.DATA_DIR)
    paths = artifact_paths(as_of, data_dir)
    journal = DecisionJournal(data_dir / "journal")
    bundle: dict[str, Any] = {
        "as_of": as_of,
        "data_dir": str(data_dir),
        "paths": {key: str(path) for key, path in paths.items()},
        "collect": read_json(paths["collect"]),
        "factor_report": read_json(paths["factor_report"]),
        "signals": read_json(paths["signals"]),
        "portfolio": read_json(paths["portfolio"]),
        "risk": read_json(paths["risk"]),
        "report": read_json(paths["report"]),
        "report_markdown": read_text(paths["report_markdown"]),
        "health": read_json(paths["health"]),
        "backtest": read_json(paths["backtest"]),
        "growth": build_growth_state(as_of, data_dir=data_dir),
        "journal": journal.summary(as_of),
        "journal_entries": journal.load(),
        "journal_reviews": journal.reviews(),
        "growth_review_markdown": read_text(paths["growth_review_markdown"]),
        "journal_review": read_json(paths["journal_review"]),
    }
    return bundle


def signals_frame(signals: dict | None) -> pd.DataFrame:
    columns = ["代码", "名称", "类别", "方向", "合成得分", "置信度", "视界", "论点"]
    rows = []
    for item in (signals or {}).get("signals", []):
        rows.append(
            {
                "代码": item.get("symbol"),
                "名称": item.get("name"),
                "类别": CATEGORY_LABELS.get(item.get("category"), item.get("category")),
                "方向": DIRECTION_LABELS.get(int(item.get("direction") or 0), "中性"),
                "合成得分": item.get("composite"),
                "置信度": item.get("confidence"),
                "视界": item.get("horizon"),
                "论点": item.get("thesis"),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def holdings_frame(portfolio: dict | None) -> pd.DataFrame:
    columns = ["代码", "名称", "类别", "权重", "年化波动", "得分", "倾斜"]
    rows = []
    for item in (portfolio or {}).get("holdings", []):
        rows.append(
            {
                "代码": item.get("symbol"),
                "名称": item.get("name"),
                "类别": CATEGORY_LABELS.get(item.get("category"), item.get("category")),
                "权重": item.get("weight"),
                "年化波动": item.get("vol"),
                "得分": item.get("composite"),
                "倾斜": item.get("tilt"),
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values("权重", ascending=False).reset_index(drop=True)
    return frame


def category_exposure_frame(portfolio: dict | None) -> pd.DataFrame:
    columns = ["类别", "预算", "实际", "偏离"]
    if not portfolio:
        return pd.DataFrame(columns=columns)
    budget = (portfolio.get("policy") or {}).get("category_budget") or {}
    actual = portfolio.get("category_exposure") or {}
    rows = []
    for key, value in budget.items():
        exposed = actual.get(key)
        rows.append(
            {
                "类别": CATEGORY_LABELS.get(key, key),
                "预算": value,
                "实际": exposed,
                "偏离": (exposed - value) if exposed is not None else None,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def cell(value: Any) -> str:
    """One display-safe cell: mixed None/float/str columns break Arrow otherwise."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if math.isnan(value):
            return "—"
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"
    return str(value)


def risk_checks_frame(risk: dict | None) -> pd.DataFrame:
    columns = ["级别", "检查", "结果", "数值", "上限", "说明"]
    rows = []
    for item in (risk or {}).get("checks", []):
        rows.append(
            {
                "级别": item.get("level"),
                "检查": item.get("id"),
                "结果": "✅" if item.get("passed") else "❌",
                "数值": cell(item.get("value")),
                "上限": cell(item.get("limit")),
                "说明": item.get("message"),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def validation_frame(risk: dict | None) -> pd.DataFrame:
    columns = ["条件", "说明", "实际", "要求", "结果"]
    rows = []
    for item in ((risk or {}).get("validation") or {}).get("criteria", []):
        rows.append(
            {
                "条件": item.get("id"),
                "说明": item.get("description"),
                "实际": item.get("actual"),
                "要求": item.get("required"),
                "结果": "✅" if item.get("passed") else "❌",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def health_frame(health: dict | None) -> pd.DataFrame:
    columns = ["数据集", "标的", "级别", "最近日期", "滞后天数", "行数", "空值率", "说明"]
    rows = []
    for item in (health or {}).get("checks", []):
        rows.append(
            {
                "数据集": item.get("dataset"),
                "标的": item.get("key"),
                "级别": HEALTH_LEVEL_LABELS.get(item.get("level"), item.get("level")),
                "最近日期": item.get("last_date"),
                "滞后天数": item.get("lag_days"),
                "行数": item.get("rows"),
                "空值率": item.get("null_ratio"),
                "说明": item.get("message"),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def factor_frame(factor_report: dict | None, horizon: int | None = None) -> pd.DataFrame:
    columns = [
        "因子",
        "视界",
        "中性 IC",
        "NW t",
        "ICIR",
        "q 值",
        "显著",
        "DSR",
        "覆盖率",
    ]
    rows = []
    for item in (factor_report or {}).get("tests", []):
        if horizon is not None and int(item.get("horizon") or 0) != int(horizon):
            continue
        rows.append(
            {
                "因子": item.get("factor"),
                "视界": item.get("horizon"),
                "中性 IC": item.get("ic_mean_neutral"),
                "NW t": item.get("nw_t_neutral"),
                "ICIR": item.get("icir_neutral"),
                "q 值": item.get("q_value_neutral"),
                "显著": "✅" if item.get("significant_neutral") else "—",
                "DSR": item.get("dsr_neutral"),
                "覆盖率": item.get("coverage"),
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["视界", "q 值"]).reset_index(drop=True)
    return frame


def strategies_frame(backtest: dict | None) -> pd.DataFrame:
    columns = ["策略", "CAGR", "年化波动", "Sharpe", "最大回撤", "年换手", "年化成本", "未成交"]
    rows = []
    for name, payload in ((backtest or {}).get("strategies") or {}).items():
        metrics = (payload or {}).get("metrics") or {}
        rows.append(
            {
                "策略": STRATEGY_LABELS.get(name, name),
                "CAGR": metrics.get("cagr"),
                "年化波动": metrics.get("ann_vol"),
                "Sharpe": metrics.get("sharpe"),
                "最大回撤": metrics.get("max_drawdown"),
                "年换手": metrics.get("annual_turnover"),
                "年化成本": metrics.get("annual_cost"),
                "未成交": metrics.get("blocked_fills"),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def backtest_diagnostics(backtest: dict | None) -> dict[str, Any]:
    diagnostics = (backtest or {}).get("diagnostics") or {}
    cpcv = (diagnostics.get("cpcv") or {}).get("summary") or {}
    p05 = {name: (payload or {}).get("p05") for name, payload in cpcv.items()}
    return {
        "pbo": (diagnostics.get("pbo") or {}).get("pbo"),
        "dsr": diagnostics.get("dsr"),
        "dsr_trials": diagnostics.get("dsr_trials"),
        "cpcv_p05": p05,
        "cpcv_groups": (diagnostics.get("cpcv") or {}).get("groups"),
        "cpcv_blocks": (diagnostics.get("cpcv") or {}).get("test_blocks"),
    }


def journal_entries_frame(entries: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["决策 ID", "日期", "范围", "标的", "动作", "理由", "置信度", "复盘天数"]
    if entries is None or entries.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for item in entries.to_dict("records"):
        rows.append(
            {
                "决策 ID": item.get("decision_id"),
                "日期": item.get("as_of"),
                "范围": "组合" if item.get("scope") == "portfolio" else "标的",
                "标的": item.get("symbol") or "—",
                "动作": ACTION_LABELS.get(str(item.get("action")), item.get("action")),
                "理由": item.get("rationale"),
                "置信度": item.get("confidence"),
                "复盘天数": item.get("review_days"),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def journal_reviews_frame(reviews: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["决策 ID", "入场", "出场", "收益", "超额", "方向", "方向超额", "结果"]
    if reviews is None or reviews.empty:
        return pd.DataFrame(columns=columns)
    outcome_labels = {
        "hit": "命中",
        "miss": "未命中",
        "observed": "观察项",
        "unscored": "无法评分",
    }
    rows = []
    for item in reviews.to_dict("records"):
        rows.append(
            {
                "决策 ID": item.get("decision_id"),
                "入场": item.get("entry_date"),
                "出场": item.get("exit_date"),
                "收益": item.get("ret"),
                "超额": item.get("excess"),
                "方向": item.get("direction"),
                "方向超额": item.get("dir_excess"),
                "结果": outcome_labels.get(str(item.get("outcome")), item.get("outcome")),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def strip_citations(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s{2,}", " ", _CITATION.sub("", text)).strip()


def pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(number):
        return "—"
    return f"{number * 100:.{digits}f}%"


def num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(number):
        return "—"
    return f"{number:.{digits}f}"


def money_cn(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(number):
        return "—"
    if abs(number) >= 1e8:
        return f"{number / 1e8:.2f} 亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:.2f} 万"
    return f"{number:.0f}"


__all__ = [
    "ACTION_LABELS",
    "CATEGORY_LABELS",
    "DIRECTION_LABELS",
    "HEALTH_LEVEL_LABELS",
    "RISK_LABELS",
    "STRATEGY_LABELS",
    "artifact_paths",
    "available_dates",
    "backtest_diagnostics",
    "category_exposure_frame",
    "cell",
    "factor_frame",
    "health_frame",
    "holdings_frame",
    "journal_entries_frame",
    "journal_reviews_frame",
    "load_bundle",
    "money_cn",
    "num",
    "pct",
    "read_json",
    "read_text",
    "risk_checks_frame",
    "signals_frame",
    "strategies_frame",
    "strip_citations",
    "validation_frame",
]
