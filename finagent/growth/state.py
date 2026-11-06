"""Daily growth state: process, evidence, risk discipline and data quality.

The score is a *process* gauge, not an investment result. It rewards the habits
that make research auditable — running the pipeline, keeping risk limits,
accumulating settled samples — and it deliberately gives no points for returns.

Everything is derived from artefacts already on disk. Missing inputs reduce a
dimension and produce an action; they never crash the daily state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from finagent import config
from finagent.data.cache import ParquetCache
from finagent.data.panel import as_date
from finagent.growth.journal import DecisionJournal

ARTIFACTS = [
    {
        "id": "collect",
        "label": "采集",
        "relative": "quality/collect_{date}.json",
        "command": "python scripts/collect_daily.py --end {date}",
    },
    {
        "id": "factor_report",
        "label": "因子报告",
        "relative": "quality/factor_report_{date}.json",
        "command": "python -m finagent.cli factor-report --date {date}",
    },
    {
        "id": "signals",
        "label": "结构化信号",
        "relative": "signals/{date}.json",
        "command": "python -m finagent.cli signals --date {date}",
    },
    {
        "id": "portfolio",
        "label": "目标权重",
        "relative": "portfolio/{date}.json",
        "command": "python -m finagent.cli portfolio --date {date}",
    },
    {
        "id": "risk",
        "label": "风控判决",
        "relative": "quality/risk_{date}.json",
        "command": "python -m finagent.cli risk --date {date}",
    },
    {
        "id": "report",
        "label": "研究报告",
        "relative": "reports/report_{date}.json",
        "command": "python -m finagent.cli report --date {date}",
    },
    {
        "id": "health",
        "label": "健康检查",
        "relative": "quality/health_{date}.json",
        "command": "python scripts/health_check.py",
    },
]

LEVELS = [
    (0, "L0", "流程搭建期"),
    (40, "L1", "习惯养成期"),
    (60, "L2", "证据积累期"),
    (75, "L3", "复盘进阶期"),
    (90, "L4", "稳定闭环期"),
]

CORE_DAILY = ("signals", "portfolio", "risk", "report")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _portfolio_min_samples(risk: dict | None) -> int:
    return int(((risk or {}).get("policy") or {}).get("min_settled_samples") or 385)


def _dates(data_dir: Path, folder: str, suffix: str = ".json") -> list[str]:
    path = data_dir / folder
    if not path.exists():
        return []
    return sorted(p.stem for p in path.glob(f"*{suffix}") if p.is_file())


def _trading_calendar(
    data_dir: Path, cache_dir: Path, as_of: str, window: int
) -> list[str]:
    """Last `window` trading dates up to `as_of`; never includes the future."""
    cache = ParquetCache(cache_dir)
    frame = cache.read("trade_calendar", "all")
    if frame is not None and not frame.empty and "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        dates = dates[dates <= pd.Timestamp(as_of)].sort_values().tail(window)
        if len(dates):
            return [d.date().isoformat() for d in dates]
    # Fallback: dates that actually produced an artefact. Better a shorter,
    # honest window than a business-day guess that invents holidays.
    observed = sorted(
        set(_dates(data_dir, "signals"))
        | set(_dates(data_dir, "reports", ".json"))
        | set(_dates(data_dir, "portfolio"))
    )
    observed = [d for d in observed if d <= as_of][-window:]
    if observed:
        return observed
    return [d.date().isoformat() for d in pd.bdate_range(end=as_of, periods=window)]


def _relative_exists(data_dir: Path, template: str, as_of: str) -> bool:
    return (data_dir / template.format(date=as_of)).exists()


def _score_process(present: list[str]) -> int:
    return int(round(100 * len(present) / len(ARTIFACTS)))


def _score_risk(status: str) -> int:
    return {"pass": 100, "warn": 70, "blocked": 0}.get(status, 50)


def _score_data(health: dict | None) -> int:
    if not health:
        return 50
    errors = int(health.get("errors") or 0)
    warnings = int(health.get("warnings") or 0)
    return max(0, 100 - 50 * errors - 10 * warnings)


def _level(score: int) -> dict[str, Any]:
    current = LEVELS[0]
    for threshold, name, label in LEVELS:
        if score >= threshold:
            current = (threshold, name, label)
    index = LEVELS.index(current)
    if index + 1 < len(LEVELS):
        next_threshold, next_name, next_label = LEVELS[index + 1]
        points = max(next_threshold - score, 0)
    else:
        next_threshold, next_name, next_label = current
        points = 0
    return {
        "id": current[1],
        "name": current[2],
        "score": score,
        "next_id": next_name,
        "next_name": next_label,
        "next_threshold": next_threshold,
        "points_to_next": points,
        "scale_note": (
            "过程分，不是收益分。权重：流程 30%、证据 30%、风控 25%、数据 15%。"
        ),
    }


def _actions(
    as_of: str,
    missing: list[dict],
    risk: dict | None,
    health: dict | None,
    report: dict | None,
    journal: dict,
    settled: int,
    required: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rank = {"high": 0, "medium": 1, "low": 2}

    def add(action_id: str, priority: str, title: str, why: str, command: str | None) -> None:
        out.append(
            {
                "id": action_id,
                "priority": priority,
                "title": title,
                "why": why,
                "command": command,
            }
        )

    if missing:
        first = missing[0]
        add(
            "pipeline.missing",
            "high",
            "补齐当日流程：" + "、".join(item["label"] for item in missing),
            "缺少工件会降低过程分，并让报告与风控只能看到部分事实。",
            first["command"],
        )

    status = (risk or {}).get("status")
    if status == "blocked":
        add(
            "risk.blocked",
            "high",
            "先处理风控硬约束失败，再看收益",
            "硬约束越线时，组合层面的正常结论没有意义。",
            f"python -m finagent.cli risk --date {as_of} --json",
        )
    elif status == "warn":
        failed = (risk or {}).get("failed") or []
        add(
            "risk.warn",
            "medium",
            "复盘软约束：" + ("、".join(failed[:3]) if failed else "查看失败项"),
            "软约束不阻断，但它解释了「通过得勉强」在哪里。",
            f"python -m finagent.cli risk --date {as_of} --json",
        )
    elif risk is None:
        add(
            "risk.not_run",
            "medium",
            "运行风控判决",
            "没有风控文件，报告无法说明组合是否越线。",
            f"python -m finagent.cli risk --date {as_of}",
        )

    if settled < required:
        add(
            "evidence.samples",
            "medium",
            f"继续积累结算样本：{settled}/{required}",
            "在样本达到门槛前，命中率与超额都没有统计意义；不要提前修改 validated。",
            f"python -m finagent.cli ledger --date {as_of}",
        )

    errors = int((health or {}).get("errors") or 0)
    warnings = int((health or {}).get("warnings") or 0)
    if errors:
        add(
            "data.errors",
            "high",
            f"修复数据健康检查错误：{errors} 项",
            "带错误的数据会让所有下游数字失去可比性。",
            f"python -m finagent.cli data-check --date {as_of}",
        )
    elif warnings:
        add(
            "data.warnings",
            "medium",
            f"查看数据健康检查警告：{warnings} 项",
            "警告不阻断，但可能是覆盖下降或缓存落后的前兆。",
            f"python -m finagent.cli data-check --date {as_of}",
        )

    if (report or {}).get("mode") == "template":
        add(
            "report.template",
            "low",
            "检查报告为何走确定性模板",
            "模板可用；但若 key 或网络正常，LLM 版本的信息密度更高。",
            f"python -c \"import json; print(json.load(open('data/reports/report_{as_of}.json'))['fallback_reason'])\"",
        )

    if not journal.get("n_entries"):
        add(
            "journal.first",
            "low",
            "记录第一条决策或观察",
            "没有记录就没有可复盘的对象；决策日志是成长体系里唯一由人填写的一层。",
            f"python -m finagent.cli journal --date {as_of} --add --action watch --rationale \"今天的观察\"",
        )

    if not out:
        add(
            "keep.rhythm",
            "low",
            "保持每日流程，按周复盘",
            "今天没有需要补救的缺口；成长来自持续记录，不是一次冲刺。",
            f"python -m finagent.cli growth --date {as_of} --review",
        )

    out.sort(key=lambda item: (rank[item["priority"]], item["id"]))
    return out[:6]


def _milestones(
    data_dir: Path,
    ledger: dict,
    journal: dict,
    activity: dict,
    required: int,
) -> list[dict[str, Any]]:
    signal_dates = _dates(data_dir, "signals")
    report_dates = [d.removeprefix("report_") for d in _dates(data_dir, "reports")]
    risk_dates = [
        p.stem.removeprefix("risk_")
        for p in (data_dir / "quality").glob("risk_*.json")
        if p.is_file()
    ]
    settled = int(ledger.get("n_settled") or 0)

    def item(mid: str, label: str, achieved: bool, evidence: str) -> dict[str, Any]:
        return {"id": mid, "label": label, "achieved": bool(achieved), "evidence": evidence}

    return [
        item("first_signal", "第一条结构化信号", bool(signal_dates), signal_dates[0] if signal_dates else "尚未产生"),
        item("first_report", "第一份研究报告", bool(report_dates), report_dates[0] if report_dates else "尚未产生"),
        item("first_risk", "第一次风控判决", bool(risk_dates), sorted(risk_dates)[0] if risk_dates else "尚未产生"),
        item("first_journal", "第一条决策记录", bool(journal.get("n_entries")), f"{journal.get('n_entries', 0)} 条"),
        item("first_review", "第一次决策复盘", bool(journal.get("n_reviewed")), f"{journal.get('n_reviewed', 0)} 条"),
        item("first_settled", "第一条预测结算", settled >= 1, f"{settled} 条已结算"),
        item("samples_100", "结算样本达到 100", settled >= 100, f"{settled}/100"),
        item("samples_required", f"结算样本达到 {required}", settled >= required, f"{settled}/{required}"),
        item("process_20d", "30 个交易日内完成 20 天全流程", activity["complete_days"] >= 20, f"{activity['complete_days']} 天"),
    ]


def build_growth_state(
    as_of: str,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    window: int = 30,
) -> dict[str, Any]:
    """Aggregate one day's process, evidence, risk and data state."""
    as_of = as_date(as_of).isoformat()
    data_dir = Path(data_dir or config.DATA_DIR)
    cache_dir = Path(cache_dir or data_dir / "cache")
    window = max(int(window), 1)

    artifacts = []
    for spec in ARTIFACTS:
        relative = spec["relative"].format(date=as_of)
        artifacts.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "path": relative,
                "present": (data_dir / relative).exists(),
                "command": spec["command"].format(date=as_of),
            }
        )
    present = [item["id"] for item in artifacts if item["present"]]
    missing = [item for item in artifacts if not item["present"]]

    risk = _read_json(data_dir / f"quality/risk_{as_of}.json")
    health = _read_json(data_dir / f"quality/health_{as_of}.json")
    report = _read_json(data_dir / f"reports/report_{as_of}.json")
    signals = _read_json(data_dir / f"signals/{as_of}.json")
    ledger = (signals or {}).get("ledger_summary") or {}
    if not ledger:
        from finagent.predictions.ledger import PredictionLedger

        ledger = PredictionLedger(data_dir / "predictions").summary(as_of)
    settled = int(ledger.get("n_settled") or 0)
    required = _portfolio_min_samples(risk)

    journal = DecisionJournal(data_dir / "journal").summary(as_of)

    calendar = _trading_calendar(data_dir, cache_dir, as_of, window)
    counts = {key: 0 for key in ("signals", "portfolio", "risk", "report")}
    complete_days = 0
    for day in calendar:
        day_present = {
            "signals": (data_dir / f"signals/{day}.json").exists(),
            "portfolio": (data_dir / f"portfolio/{day}.json").exists(),
            "risk": (data_dir / f"quality/risk_{day}.json").exists(),
            "report": (data_dir / f"reports/report_{day}.json").exists(),
        }
        for key, value in day_present.items():
            counts[key] += int(value)
        complete_days += int(all(day_present[key] for key in CORE_DAILY))

    streak = 0
    for day in reversed(calendar):
        complete = all(
            (data_dir / rel.format(date=day)).exists()
            for rel in (
                "signals/{date}.json",
                "portfolio/{date}.json",
                "quality/risk_{date}.json",
                "reports/report_{date}.json",
            )
        )
        if not complete:
            break
        streak += 1
    activity = {
        "window": window,
        "calendar_days": len(calendar),
        "complete_days": complete_days,
        "streak_days": streak,
        "counts": counts,
    }

    process_score = _score_process(present)
    evidence_score = int(round(min(settled / required, 1.0) * 100)) if required else 0
    risk_status = str((risk or {}).get("status") or "not_run")
    risk_score = _score_risk(risk_status)
    data_score = _score_data(health)
    total = int(round(0.30 * process_score + 0.30 * evidence_score + 0.25 * risk_score + 0.15 * data_score))

    counts_risk = (risk or {}).get("counts") or {}
    validation = (risk or {}).get("validation") or {}
    report_checks = (report or {}).get("checks") or {}
    state = {
        "as_of": as_of,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": _level(total),
        "dimensions": {
            "process": {
                "score": process_score,
                "passed": len(present),
                "total": len(ARTIFACTS),
                "missing": [item["id"] for item in missing],
            },
            "evidence": {
                "score": evidence_score,
                "settled": settled,
                "required": required,
                "ratio": round(settled / required, 4) if required else 0.0,
                "remaining": validation.get("remaining") or [],
            },
            "risk": {
                "score": risk_score,
                "status": risk_status,
                "hard_failed": counts_risk.get("hard_failed"),
                "soft_failed": counts_risk.get("soft_failed"),
                "failed": (risk or {}).get("failed") or [],
                "policy_fingerprint": (risk or {}).get("policy_fingerprint"),
            },
            "data": {
                "score": data_score,
                "errors": (health or {}).get("errors"),
                "warnings": (health or {}).get("warnings"),
            },
        },
        "artifacts": artifacts,
        "activity": activity,
        "report": {
            "present": report is not None,
            "mode": (report or {}).get("mode"),
            "gate_passed": report_checks.get("passed"),
            "fallback_reason": (report or {}).get("fallback_reason"),
        },
        "journal": journal,
        "milestones": _milestones(data_dir, ledger, journal, activity, required),
        "actions": _actions(
            as_of,
            missing,
            risk,
            health,
            report,
            journal,
            settled,
            required,
        ),
        "validation": validation,
        "inputs": {
            "signals": str(data_dir / f"signals/{as_of}.json") if signals else None,
            "portfolio": str(data_dir / f"portfolio/{as_of}.json") if (data_dir / f"portfolio/{as_of}.json").exists() else None,
            "risk": str(data_dir / f"quality/risk_{as_of}.json") if risk else None,
            "health": str(data_dir / f"quality/health_{as_of}.json") if health else None,
            "report": str(data_dir / f"reports/report_{as_of}.json") if report else None,
            "ledger": str(data_dir / "predictions"),
            "journal": str(data_dir / "journal"),
        },
        "disclaimer": (
            "成长分只衡量研究流程与证据积累，不衡量收益，也不是投资建议。"
            "validated=false 不会被自动修改。"
        ),
    }
    return state


def format_growth(state: dict[str, Any]) -> str:
    level = state["level"]
    dims = state["dimensions"]
    activity = state["activity"]
    journal = state["journal"]
    lines = [
        f"Growth for {state['as_of']}  level={level['id']} {level['name']}  "
        f"score={level['score']}/100",
        f"Process {dims['process']['score']:3d}  Evidence {dims['evidence']['score']:3d}  "
        f"Risk {dims['risk']['score']:3d}  Data {dims['data']['score']:3d}",
        f"Artifacts {dims['process']['passed']}/{dims['process']['total']}  "
        f"Risk {dims['risk']['status']}  Settled {dims['evidence']['settled']}/{dims['evidence']['required']}  "
        f"Journal {journal['n_entries']} entries / {journal['n_reviewed']} reviewed",
        f"Activity last {activity['window']} sessions: complete {activity['complete_days']}  "
        f"streak {activity['streak_days']}",
    ]
    if level["points_to_next"]:
        lines.append(
            f"Next: {level['next_id']} {level['next_name']} in {level['points_to_next']} points"
        )
    else:
        lines.append("Next: top level reached; keep the loop running")
    lines.append("")
    lines.append("Actions:")
    for action in state["actions"]:
        lines.append(f"  - [{action['priority']}] {action['title']}")
        lines.append(f"    why: {action['why']}")
        if action.get("command"):
            lines.append(f"    cmd: {action['command']}")
    achieved = sum(1 for item in state["milestones"] if item["achieved"])
    lines.append("")
    lines.append(f"Milestones {achieved}/{len(state['milestones'])}")
    return "\n".join(lines)
