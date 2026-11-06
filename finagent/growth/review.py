"""Periodic growth review: process, evidence, decisions and next actions.

The review is deterministic. It does not call an LLM, because the point is to
show exactly what the artefacts say — no narrative layer is allowed to soften a
missing sample, a blocked risk check or an unreviewed decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from finagent.growth.journal import ACTION_LABELS


def _pct(value) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _lessons(state: dict[str, Any]) -> list[dict[str, str]]:
    dims = state["dimensions"]
    journal = state["journal"]
    lessons: list[dict[str, str]] = []

    if dims["evidence"]["settled"] == 0:
        lessons.append(
            {
                "id": "evidence.pending",
                "title": "没有结算样本时，命中率不是能力",
                "body": (
                    "账本已经记账，但还没有预测到期。此时任何「看起来准」的判断都只是叙事；"
                    "先让时间和结算把证据补齐。"
                ),
            }
        )
    elif not state.get("validation", {}).get("eligible", False):
        remaining = state.get("validation", {}).get("remaining") or dims["evidence"]["remaining"]
        lessons.append(
            {
                "id": "evidence.remaining",
                "title": "证据门槛仍差几项",
                "body": "还差：" + "、".join(remaining) + "。不要因为某天命中率高就提前改 validated。",
            }
        )

    if dims["process"]["missing"]:
        lessons.append(
            {
                "id": "process.gap",
                "title": "流程缺口会让结论变成局部事实",
                "body": (
                    "缺少：" + "、".join(dims["process"]["missing"])
                    + "。报告和风控只能看到已存在的工件，缺件不会被默认补全。"
                ),
            }
        )

    if dims["risk"]["status"] == "blocked":
        lessons.append(
            {
                "id": "risk.blocked",
                "title": "硬约束越线时，先停止解释",
                "body": "风控阻断意味着组合层面没有「正常结论」可写；修复约束比润色叙事更重要。",
            }
        )
    elif dims["risk"]["status"] == "warn":
        failed = dims["risk"].get("failed") or []
        lessons.append(
            {
                "id": "risk.warn",
                "title": "软约束解释了「通过得勉强」",
                "body": "失败项：" + ("、".join(failed) if failed else "见 risk JSON") + "。warn 不阻断，但值得复盘。",
            }
        )

    if not journal.get("n_entries"):
        lessons.append(
            {
                "id": "journal.empty",
                "title": "没有记录，就没有可复盘的对象",
                "body": (
                    "决策日志是唯一由人填写的一层。哪怕今天只是「观察、不操作」，"
                    "写下理由，未来才能区分「判断错了」和「运气不好」。"
                ),
            }
        )
    elif journal.get("n_pending"):
        lessons.append(
            {
                "id": "journal.pending",
                "title": "有决策等待复盘",
                "body": f"{journal['n_pending']} 条记录尚未到期或未生成复盘；到期后再看结果。",
            }
        )

    if state["report"].get("mode") == "template":
        lessons.append(
            {
                "id": "report.template",
                "title": "模板不是失败，是降级路径",
                "body": "确定性模板同样通过门禁；如果长期停在模板，检查 key、网络或门禁失败原因。",
            }
        )

    if dims["data"].get("errors"):
        lessons.append(
            {
                "id": "data.errors",
                "title": "数据错误优先于策略讨论",
                "body": f"健康检查有 {dims['data']['errors']} 个错误；先修数据，再谈信号。",
            }
        )
    elif dims["data"].get("warnings"):
        lessons.append(
            {
                "id": "data.warnings",
                "title": "警告是覆盖下降的前兆",
                "body": f"健康检查有 {dims['data']['warnings']} 个警告，检查缓存新鲜度与缺口。",
            }
        )

    if not lessons:
        lessons.append(
            {
                "id": "keep.loop",
                "title": "闭环比单次判断更重要",
                "body": "今天没有明显缺口；继续保持记录、结算和定期复盘。",
            }
        )
    return lessons[:5]


def build_growth_review(state: dict[str, Any], *, window: int = 30) -> dict[str, Any]:
    """Wrap the daily state with period context, lessons and next actions."""
    activity = state["activity"]
    journal = state["journal"]
    review = {
        "as_of": state["as_of"],
        "window": window,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": state["level"],
        "dimensions": state["dimensions"],
        "activity": activity,
        "artifacts": state["artifacts"],
        "validation": state.get("validation") or {},
        "journal": journal,
        "risk": {
            "status": state["dimensions"]["risk"]["status"],
            "failed": state["dimensions"]["risk"].get("failed") or [],
            "policy_fingerprint": state["dimensions"]["risk"].get("policy_fingerprint"),
        },
        "report": state["report"],
        "milestones": state["milestones"],
        "actions": state["actions"],
        "lessons": _lessons(state),
        "disclaimer": state["disclaimer"],
    }
    return review


def render_growth_review(review: dict[str, Any]) -> str:
    level = review["level"]
    dims = review["dimensions"]
    activity = review["activity"]
    journal = review["journal"]
    risk = review["risk"]
    lines = [
        f"# 研究成长报告 {review['as_of']}",
        "",
        f"> 生成于 {review['generated_at']}；窗口 {review['window']} 个交易日。"
        "本报告衡量流程与证据，不衡量收益，不构成投资建议。",
        "",
        "## 一页结论",
        "",
        "| 项目 | 结果 |",
        "|---|---|",
        f"| 成长等级 | **{level['id']} {level['name']}**，{level['score']}/100 |",
        f"| 流程完整度 | {dims['process']['passed']}/{dims['process']['total']} 个工件 |",
        f"| 证据进度 | {dims['evidence']['settled']}/{dims['evidence']['required']} 条已结算 |",
        f"| 风控状态 | `{risk['status']}` |",
        f"| 决策记录 | {journal['n_entries']} 条，已复盘 {journal['n_reviewed']} 条 |",
        f"| 全流程完成 | 窗口内 {activity['complete_days']}/{activity['calendar_days']} 个交易日，"
        f"当前连续 {activity['streak_days']} 天 |",
        "",
        f"**下一步**：{level['next_id']} {level['next_name']}，还差 {level['points_to_next']} 分。"
        if level["points_to_next"]
        else "**下一步**：已到最高等级，保持闭环。",
        "",
        "## 过程：每天做了什么",
        "",
        "| 工件 | 当日 | 窗口内天数 |",
        "|---|---|---|",
    ]
    counts = activity["counts"]
    artifact_map = {item["id"]: item for item in review.get("artifacts", [])}
    for key in ("signals", "portfolio", "risk", "report"):
        present = artifact_map.get(key, {}).get("present")
        mark = "✅" if present else ("—" if present is None else "❌")
        lines.append(f"| {key} | {mark} | {counts.get(key, 0)} |")
    lines += [
        "",
        f"当前连续完成全流程：**{activity['streak_days']}** 个交易日。"
        "连续天数按全部核心工件（signals / portfolio / risk / report）同时存在计算。",
        "",
        "## 证据：离 `validated=false` 还有多远",
        "",
    ]
    validation = review.get("validation") or {}
    criteria = validation.get("criteria") or []
    if criteria:
        lines += [
            "| 条件 | 实际 | 要求 | 结果 |",
            "|---|---|---|---|",
        ]
        for item in criteria:
            result = "✅" if item.get("passed") else "❌"
            lines.append(
                f"| `{item['id']}` | {item.get('actual')} | {item.get('required')} | {result} |"
            )
        remaining = validation.get("remaining") or []
        lines += [
            "",
            f"`eligible={str(validation.get('eligible', False)).lower()}`，"
            f"`validated=false`；剩余：{('、'.join(remaining) if remaining else '无')}。",
            "",
        ]
    else:
        lines += [
            "没有 `risk_<date>.json`，无法列出六条验证门槛；先运行 `finagent risk`。",
            "",
        ]

    lines += [
        "## 决策：记录与复盘",
        "",
        f"- 记录：**{journal['n_entries']}** 条；已复盘：**{journal['n_reviewed']}** 条；"
        f"待复盘：**{journal['n_pending']}** 条。",
        f"- 方向性决策命中率（相对等权全池）：{_pct(journal.get('hit_rate_excess'))}；"
        f"平均方向性超额：{_pct(journal.get('mean_directional_excess'))}。",
    ]
    by_action = journal.get("by_action") or {}
    if by_action:
        lines += ["", "| 动作 | 条数 | 命中率 | 平均超额 |", "|---|---|---|---|"]
        for action, row in sorted(by_action.items()):
            lines.append(
                f"| {ACTION_LABELS.get(action, action)} | {row['n']} | "
                f"{_pct(row.get('hit_rate_excess'))} | {_pct(row.get('mean_directional_excess'))} |"
            )
    lines += [
        "",
        "> 决策质量与结果分开看：好的过程可能遇到坏结果，坏的过程也可能撞上好结果。"
        "命中率只统计有方向的 `add / hold / trim / exit`，`watch / no_trade` 记为观察项。",
        "",
        "## 风险：边界是否守住",
        "",
        f"- 状态：`{risk['status']}`；策略指纹：`{risk.get('policy_fingerprint') or 'n/a'}`。",
        f"- hard 失败 {dims['risk'].get('hard_failed')} 项，soft 失败 {dims['risk'].get('soft_failed')} 项。",
    ]
    if risk.get("failed"):
        lines.append("- 失败项：" + "、".join(f"`{item}`" for item in risk["failed"]))
    lines += [
        "",
        "## 下一周的行动",
        "",
    ]
    for action in review["actions"]:
        lines.append(f"- [ ] **[{action['priority']}] {action['title']}** — {action['why']}")
        if action.get("command"):
            lines.append(f"  - `{action['command']}`")
    lines += [
        "",
        "## 学习卡",
        "",
    ]
    for lesson in review["lessons"]:
        lines += [f"### {lesson['title']}", "", lesson["body"], ""]
    lines += [
        "## 口径说明",
        "",
        "- 成长分 = 流程 30% + 证据 30% + 风控 25% + 数据 15%，只衡量研究过程。",
        "- `validated=false` 不会被本报告或任何自动任务修改；升级必须由人决定并记录理由。",
        "- 证据进度以预测账本的已结算条数和 Phase 7 的六条门槛为准。",
        "- 决策日志是人工记录层；系统只做到期后的价格复盘，不生成决策。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def format_growth_review(review: dict[str, Any]) -> str:
    level = review["level"]
    lines = [
        f"Growth review {review['as_of']}  window={review['window']} sessions",
        f"Level       : {level['id']} {level['name']} ({level['score']}/100)",
        f"Process     : {review['dimensions']['process']['passed']}/"
        f"{review['dimensions']['process']['total']} artifacts",
        f"Evidence    : {review['dimensions']['evidence']['settled']}/"
        f"{review['dimensions']['evidence']['required']} settled",
        f"Risk        : {review['risk']['status']}",
        f"Journal     : {review['journal']['n_entries']} entries / "
        f"{review['journal']['n_reviewed']} reviewed",
        f"Complete    : {review['activity']['complete_days']}/"
        f"{review['activity']['calendar_days']} sessions  streak={review['activity']['streak_days']}",
        "",
        "Next actions:",
    ]
    for action in review["actions"]:
        lines.append(f"  - [{action['priority']}] {action['title']}")
    return "\n".join(lines)
