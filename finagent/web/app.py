"""finagent 研究台：Streamlit 前端。

Run with:

    streamlit run finagent/web/app.py

The page reads the same artefacts the CLI writes and runs the same commands for
the pipeline page. It adds no strategy logic of its own: every number shown is
already in a JSON/Markdown file under `data/`.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from finagent import config
from finagent.data.universe import load_universe
from finagent.growth import (
    DecisionJournal,
    JournalError,
    run_growth_review,
    run_journal_review,
)
from finagent.growth.journal import ACTION_LABELS
from finagent.integrations.feishu import load_env
from finagent.web import data as D
from finagent.web.runner import (
    DAILY_ORDER,
    STEP_BY_ID,
    STEPS,
    display_command,
    run_step,
)

load_env()

st.set_page_config(
    page_title="finagent 研究台",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; padding-bottom: 3rem;}
      [data-testid="stMetricValue"] {font-size: 1.45rem;}
      .fi-note {color: #64748b; font-size: 0.82rem; line-height: 1.5;}
      .fi-action {border-left: 3px solid #cbd5e1; padding-left: 0.8rem; margin: 0.6rem 0;}
    </style>
    """,
    unsafe_allow_html=True,
)

WEEKDAYS = "一二三四五六日"
PAGES = [
    "今日总览",
    "研究报告",
    "信号与组合",
    "风险与验证",
    "成长与决策",
    "数据健康",
    "因子与回测",
    "运行流水线",
]

PRIORITY_LABELS = {"high": "🔴 高", "medium": "🟠 中", "low": "🟢 低"}
LEVEL_ICONS = {"L0": "🌱", "L1": "🌿", "L2": "📈", "L3": "🔁", "L4": "✅"}


def _data_dir() -> Path:
    return Path(config.DATA_DIR)


def _date_label(day: str) -> str:
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{day}（周{WEEKDAYS[parsed.weekday()]}）"


def _stamp(data_dir: Path) -> float:
    """Cheap mtime signature so cached bundles refresh when a run writes files."""
    latest = 0.0
    for folder in ("signals", "portfolio", "reports", "quality", "growth", "journal"):
        path = data_dir / folder
        if not path.exists():
            continue
        for item in path.glob("*"):
            try:
                latest = max(latest, item.stat().st_mtime)
            except OSError:
                continue
    return round(latest, 3)


@st.cache_data(show_spinner=False)
def _bundle(as_of: str, data_dir: str, stamp: float) -> dict[str, Any]:
    del stamp  # cache key only
    return D.load_bundle(as_of, Path(data_dir))


def _refresh() -> None:
    st.cache_data.clear()
    st.rerun()


def _risk_banner(status: str) -> None:
    if status == "pass":
        st.success("风控：全部硬约束通过")
    elif status == "warn":
        st.warning("风控：存在软约束警告（不阻断，但值得复盘）")
    elif status == "blocked":
        st.error("风控：硬约束越线，报告与结论处于阻断状态")
    else:
        st.info("风控：当日尚未运行判决")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _show_table(frame: pd.DataFrame, *, height: int | None = None, **kwargs: Any) -> None:
    if frame.empty:
        st.caption("没有数据。")
        return
    if height is None:
        st.dataframe(frame, hide_index=True, width="stretch", **kwargs)
    else:
        st.dataframe(frame, hide_index=True, width="stretch", height=height, **kwargs)


def _actions_block(actions: list[dict[str, Any]]) -> None:
    if not actions:
        st.caption("没有待办行动。")
        return
    for action in actions:
        st.markdown(
            f'<div class="fi-action"><b>{PRIORITY_LABELS.get(action["priority"], action["priority"])}'
            f' · {action["title"]}</b><br><span class="fi-note">{action["why"]}</span></div>',
            unsafe_allow_html=True,
        )
        if action.get("command"):
            st.code(action["command"], language="bash")


def _signals_preview(bundle: dict[str, Any], limit: int = 6) -> None:
    frame = D.signals_frame(bundle["signals"])
    if frame.empty:
        st.caption("当日还没有结构化信号。")
        return
    view = frame.drop(columns=["论点"]).head(limit)
    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        column_config={
            "合成得分": st.column_config.NumberColumn(format="%.2f"),
            "置信度": st.column_config.NumberColumn(format="%.2f"),
            "视界": st.column_config.NumberColumn(format="%d 日"),
        },
    )


def render_overview(bundle: dict[str, Any], as_of: str) -> None:
    growth = bundle["growth"]
    risk = bundle["risk"] or {}
    report = bundle["report"] or {}
    signals = bundle["signals"] or {}

    st.title("今日总览")
    st.caption(f"{_date_label(as_of)} · 数据目录 `{bundle['data_dir']}`")

    level = growth["level"]
    dims = growth["dimensions"]
    evidence = dims["evidence"]
    checks = report.get("checks") or {}
    columns = st.columns(4)
    columns[0].metric(
        "成长等级",
        f"{level['id']} {level['name']}",
        help=level["scale_note"],
    )
    columns[1].metric("风控状态", D.RISK_LABELS.get(risk.get("status"), "未运行"))
    columns[2].metric(
        "研究报告",
        f"{str(report.get('mode') or '未生成').upper()} · "
        f"{'门禁通过' if checks.get('passed') else '未通过/未生成'}",
    )
    columns[3].metric(
        "结算样本",
        f"{evidence['settled']} / {evidence['required']}",
        help="达到 385 条之前，命中率与超额没有统计意义。",
    )

    _risk_banner(risk.get("status", "not_run"))

    left, right = st.columns([0.95, 1.05])
    with left:
        st.subheader("下一步做什么")
        st.caption(f"成长分 {level['score']}/100；距离 {level['next_id']} {level['next_name']} 还差 {level['points_to_next']} 分。")
        _actions_block(growth["actions"])
    with right:
        st.subheader("当日信号")
        ledger = signals.get("ledger_summary") or {}
        st.caption(
            f"{signals.get('n_signals', 0)} 条信号 · 账本 {ledger.get('n_predictions', 0)} 条"
            f"（已结算 {ledger.get('n_settled', 0)}） · 全部 `validated={str(ledger.get('validated', False)).lower()}`"
        )
        _signals_preview(bundle)

    st.divider()
    st.subheader("报告结论")
    text = D.strip_citations(report.get("text"))
    if text:
        st.markdown(text[:700] + ("…" if len(text) > 700 else ""))
        st.caption("完整正文与门禁明细见「研究报告」页。")
    else:
        st.info("当日还没有报告。到「运行流水线」运行 `report` 即可生成。")

    st.divider()
    st.caption(
        "本页只汇总已有工件：数字由代码计算，叙事由 LLM 撰写，人做最终决策。"
        "成长分衡量研究过程，不衡量收益；`validated=false` 不会被任何页面修改。"
    )


def render_report(bundle: dict[str, Any], as_of: str) -> None:
    report = bundle["report"]
    st.title("研究报告")
    st.caption(_date_label(as_of))
    if not report:
        st.info("当日还没有报告。请到「运行流水线」运行 `report`。")
        return

    checks = report.get("checks") or {}
    citation = checks.get("citation") or {}
    numeric = checks.get("numeric_strict") or checks.get("numeric") or {}
    columns = st.columns(5)
    columns[0].metric("模式", str(report.get("mode") or "—").upper())
    columns[1].metric("模型", report.get("model") or "—")
    columns[2].metric("门禁", "通过" if checks.get("passed") else "未通过")
    columns[3].metric("引用准确率", D.pct(citation.get("score")))
    columns[4].metric("数字可追溯", D.pct(numeric.get("score")))

    if report.get("mode") == "template":
        st.warning(f"确定性模板：{report.get('fallback_reason') or '未知原因'}")
    failures = checks.get("failures") or []
    if failures:
        st.error("门禁失败项：" + "；".join(str(item) for item in failures))

    body = bundle.get("report_markdown") or report.get("text") or ""
    tabs = st.tabs(["正文", "门禁与证据", "下载"])
    with tabs[0]:
        st.markdown(body)
    with tabs[1]:
        summary = pd.DataFrame(
            [
                {"项目": "五段结构", "结果": "通过" if checks.get("sections") else "—"},
                {"项目": "引用数", "结果": f"{citation.get('cited', 0)} / 有效 {citation.get('valid', 0)}"},
                {"项目": "数字检查", "结果": f"{numeric.get('checked', 0)} 项，不可追溯 {len(numeric.get('untraceable') or [])} 项"},
                {"项目": "必须词组缺失", "结果": "、".join(checks.get("must_include_missing") or []) or "无"},
                {"项目": "禁用词命中", "结果": "、".join(checks.get("forbidden_hits") or []) or "无"},
            ]
        )
        _show_table(summary)
        items = (report.get("evidence") or {}).get("items") or []
        if items:
            st.subheader("证据表")
            query = st.text_input("搜索证据（ID 或标签）", key="evidence_search")
            frame = pd.DataFrame(
                [
                    {
                        "ID": item.get("id"),
                        "标签": item.get("label"),
                        "数值": item.get("value"),
                        "单位": item.get("unit"),
                        "备注": item.get("note"),
                    }
                    for item in items
                ]
            )
            if query:
                mask = frame["ID"].astype(str).str.contains(query, case=False) | frame[
                    "标签"
                ].astype(str).str.contains(query, case=False)
                frame = frame[mask]
            _show_table(frame, height=380)
    with tabs[2]:
        st.download_button(
            "下载 Markdown",
            data=body.encode("utf-8"),
            file_name=f"report_{as_of}.md",
            mime="text/markdown",
        )
        st.caption(f"JSON：`{bundle['paths']['report']}`")


def render_signals(bundle: dict[str, Any], as_of: str) -> None:
    st.title("信号与组合")
    st.caption(_date_label(as_of))

    sign_tab, portfolio_tab = st.tabs(["结构化信号", "目标权重"])
    with sign_tab:
        signals = bundle["signals"]
        if not signals:
            st.info("当日还没有结构化信号。")
        else:
            frame = D.signals_frame(signals)
            filters = st.columns([1, 1, 1.4])
            categories = ["全部"] + sorted(frame["类别"].dropna().unique().tolist())
            category = filters[0].selectbox("类别", categories, key="sig_category")
            direction = filters[1].selectbox("方向", ["全部", "看多", "看空"], key="sig_direction")
            query = filters[2].text_input("搜索代码或名称", key="sig_query")
            view = frame.copy()
            if category != "全部":
                view = view[view["类别"] == category]
            if direction != "全部":
                view = view[view["方向"] == direction]
            if query:
                mask = view["代码"].astype(str).str.contains(query) | view["名称"].astype(
                    str
                ).str.contains(query)
                view = view[mask]
            st.caption(
                f"展示 {len(view)} / {len(frame)} 条 · 置信度是同向度（|加权和| / 加权绝对值和），不是概率"
            )
            st.dataframe(
                view.drop(columns=["论点"]),
                hide_index=True,
                width="stretch",
                column_config={
                    "合成得分": st.column_config.NumberColumn(format="%.2f"),
                    "置信度": st.column_config.NumberColumn(format="%.2f"),
                    "视界": st.column_config.NumberColumn(format="%d 日"),
                },
            )
            if not frame.empty:
                st.subheader("单条信号详情")
                options = frame["代码"] + " · " + frame["名称"]
                selected = st.selectbox("选择信号", options.tolist(), key="sig_detail")
                signal = signals.get("signals", [])[options.tolist().index(selected)]
                st.markdown(f"**论点**：{signal.get('thesis')}")
                st.markdown(f"**信号 ID**：`{signal.get('signal_id')}` · **方向**：{signal.get('direction')}")
                evidence = signal.get("evidence") or []
                if evidence:
                    _show_table(
                        pd.DataFrame(evidence).rename(
                            columns={
                                "factor": "因子",
                                "value": "原始值",
                                "z": "截面 z",
                                "direction": "方向",
                                "contribution": "贡献",
                            }
                        ),
                        column_config={
                            "原始值": st.column_config.NumberColumn(format="%.4f"),
                            "截面 z": st.column_config.NumberColumn(format="%.3f"),
                            "贡献": st.column_config.NumberColumn(format="%.3f"),
                        },
                    )
                invalidation = signal.get("invalidation") or []
                for item in invalidation:
                    st.markdown(f"- 失效条件：{item.get('condition')}")
                st.caption("全部信号 `validated=false`：Phase 4 的因子检验没有给出显著证据。")

    with portfolio_tab:
        portfolio = bundle["portfolio"]
        if not portfolio:
            st.info("当日还没有目标权重。")
            return
        columns = st.columns(4)
        columns[0].metric("组合波动", D.pct(portfolio.get("portfolio_vol")))
        columns[1].metric("加权平均波动", D.pct(portfolio.get("weighted_vol")))
        columns[2].metric("持仓数", portfolio.get("n_holdings", 0))
        columns[3].metric("策略", portfolio.get("policy", {}).get("name", "—"))

        exposure = D.category_exposure_frame(portfolio)
        if not exposure.empty:
            chart_data = exposure.melt(
                id_vars="类别",
                value_vars=["预算", "实际"],
                var_name="口径",
                value_name="比例",
            )
            chart = (
                alt.Chart(chart_data)
                .mark_bar()
                .encode(
                    x=alt.X("类别:N", sort=None, title=None),
                    xOffset="口径:N",
                    y=alt.Y("比例:Q", axis=alt.Axis(format="%"), title="占组合比例"),
                    color=alt.Color(
                        "口径:N",
                        scale=alt.Scale(range=["#94a3b8", "#2563eb"]),
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    tooltip=["类别", "口径", alt.Tooltip("比例:Q", format=".2%")],
                )
                .properties(height=240)
            )
            st.altair_chart(chart, width="stretch")
            right = exposure.copy()
            right["预算"] = right["预算"].map(D.pct)
            right["实际"] = right["实际"].map(D.pct)
            right["偏离"] = right["偏离"].map(D.pct)
            _show_table(right)

        st.subheader("持仓明细")
        holdings = D.holdings_frame(portfolio)
        display = holdings.copy()
        display["权重"] = (display["权重"].astype(float) * 100).round(2)
        display["年化波动"] = display["年化波动"].map(D.pct)
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "权重": st.column_config.ProgressColumn(
                    "权重 %", min_value=0, max_value=12, format="%.2f%%"
                ),
                "得分": st.column_config.NumberColumn(format="%.2f"),
                "倾斜": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption(portfolio.get("notes") or "")


def _validation_display(risk: dict[str, Any] | None) -> pd.DataFrame:
    frame = D.validation_frame(risk)
    if frame.empty:
        return frame
    percent_ids = {"hit_rate_excess", "mean_directional_excess", "drawdown_budget"}
    display = frame.copy()
    for index, row in display.iterrows():
        condition = str(row["条件"])
        actual = row["实际"]
        required = row["要求"]
        if condition in percent_ids and actual is not None:
            display.at[index, "实际"] = D.pct(actual)
        else:
            display.at[index, "实际"] = D.cell(actual)
        if condition in percent_ids and isinstance(required, (int, float)):
            display.at[index, "要求"] = f"{float(required):.0%}"
        else:
            display.at[index, "要求"] = D.cell(required)
    return display


def render_risk(bundle: dict[str, Any], as_of: str) -> None:
    risk = bundle["risk"]
    st.title("风险与验证")
    st.caption(_date_label(as_of))
    if not risk:
        st.info("当日还没有风控判决。请到「运行流水线」运行 `risk`。")
        return

    status = risk.get("status", "not_run")
    _risk_banner(status)
    counts = risk.get("counts") or {}
    columns = st.columns(5)
    columns[0].metric("硬约束", f"{counts.get('hard_failed', 0)} / {counts.get('hard', 0)} 失败")
    columns[1].metric("软约束", f"{counts.get('soft_failed', 0)} / {counts.get('soft', 0)} 失败")
    columns[2].metric("信息项", counts.get("info", 0))
    columns[3].metric("策略指纹", risk.get("policy_fingerprint") or "—")
    columns[4].metric("验证状态", "eligible" if (risk.get("validation") or {}).get("eligible") else "validated=false")

    failed = risk.get("failed") or []
    if failed:
        st.markdown("**失败项**：" + "、".join(f"`{item}`" for item in failed))

    checks_tab, validation_tab = st.tabs(["检查明细", "升级门槛"])
    with checks_tab:
        frame = D.risk_checks_frame(risk)
        filters = st.columns(2)
        level = filters[0].selectbox("级别", ["全部", "hard", "soft", "info"], key="risk_level")
        result = filters[1].selectbox("结果", ["全部", "通过", "失败"], key="risk_result")
        view = frame.copy()
        if level != "全部":
            view = view[view["级别"] == level]
        if result == "通过":
            view = view[view["结果"] == "✅"]
        elif result == "失败":
            view = view[view["结果"] == "❌"]
        _show_table(view, height=460)
        st.caption("硬约束越线会阻断报告；软约束只警告；info 只记录，不改变状态。")
    with validation_tab:
        validation = risk.get("validation") or {}
        st.caption(
            f"`validated={str(validation.get('validated', False)).lower()}`，"
            f"`eligible={str(validation.get('eligible', False)).lower()}`。"
            "六条全部通过后仍需人工决定是否升级，系统不会自动改旗标。"
        )
        _show_table(_validation_display(risk))
        remaining = validation.get("remaining") or []
        st.markdown("**仍缺**：" + ("、".join(f"`{item}`" for item in remaining) if remaining else "无"))


def _dimension_chart(dimensions: dict[str, Any]) -> alt.Chart:
    labels = {"process": "流程", "evidence": "证据", "risk": "风控", "data": "数据"}
    frame = pd.DataFrame(
        [{"维度": labels[key], "得分": value["score"]} for key, value in dimensions.items()]
    )
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("维度:N", sort=None, title=None),
            y=alt.Y("得分:Q", scale=alt.Scale(domain=[0, 100]), title="得分"),
            color=alt.Color("维度:N", legend=None, scale=alt.Scale(range=["#2563eb"] * 4)),
            tooltip=["维度", "得分"],
        )
        .properties(height=220)
    )


def render_growth(bundle: dict[str, Any], as_of: str, data_dir: Path) -> None:
    growth = bundle["growth"]
    level = growth["level"]
    st.title("成长与决策")
    st.caption(_date_label(as_of))

    columns = st.columns(4)
    columns[0].metric(
        "成长等级",
        f"{level['id']} {level['name']}",
        help=level["scale_note"],
    )
    columns[1].metric("总分", f"{level['score']} / 100")
    columns[2].metric("下一级", f"{level['next_id']} {level['next_name']}")
    columns[3].metric("还差", f"{level['points_to_next']} 分")

    state_tab, journal_tab, review_tab = st.tabs(["每日状态", "决策日志", "周期报告"])
    with state_tab:
        chart_col, activity_col = st.columns([1.1, 1])
        with chart_col:
            st.altair_chart(_dimension_chart(growth["dimensions"]), width="stretch")
        with activity_col:
            dims = growth["dimensions"]
            activity = growth["activity"]
            st.markdown(
                f"- 流程：**{dims['process']['score']}**（工件 {dims['process']['passed']}/{dims['process']['total']}）\n"
                f"- 证据：**{dims['evidence']['score']}**（结算 {dims['evidence']['settled']}/{dims['evidence']['required']}）\n"
                f"- 风控：**{dims['risk']['score']}**（`{dims['risk']['status']}`）\n"
                f"- 数据：**{dims['data']['score']}**（errors {_fmt(dims['data']['errors'])} / warnings {_fmt(dims['data']['warnings'])}）\n"
                f"- 窗口内完整流程：**{activity['complete_days']}/{activity['calendar_days']}** 个交易日，"
                f"当前连续 **{activity['streak_days']}** 天"
            )
            if dims["process"]["missing"]:
                st.warning("缺少工件：" + "、".join(dims["process"]["missing"]))
        st.subheader("下一步行动")
        _actions_block(growth["actions"])

        st.subheader("里程碑")
        milestones = pd.DataFrame(
            [
                {
                    "里程碑": item["label"],
                    "状态": "✅" if item["achieved"] else "—",
                    "证据": item["evidence"],
                }
                for item in growth["milestones"]
            ]
        )
        _show_table(milestones)

    with journal_tab:
        summary = bundle["journal"]
        metrics = st.columns(4)
        metrics[0].metric("记录", summary["n_entries"])
        metrics[1].metric("已复盘", summary["n_reviewed"])
        metrics[2].metric("待复盘", summary["n_pending"])
        metrics[3].metric(
            "方向命中率",
            D.pct(summary.get("hit_rate_excess")),
            help="只统计有方向的 add/hold/trim/exit；watch/no_trade 记为观察项。",
        )
        st.caption(
            "决策日志只由人写入：系统不会生成决策，只做到期后的价格对照。"
            "好的过程可能遇到坏结果，反之亦然。"
        )

        with st.form("journal_add", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            symbol = c1.text_input("标的代码（留空=组合级）", placeholder="510300")
            action = c2.selectbox(
                "动作",
                options=["add", "hold", "trim", "exit", "watch", "no_trade"],
                format_func=lambda key: ACTION_LABELS[key],
            )
            confidence = c3.slider("置信度（判断分，不是概率）", 0.0, 1.0, 0.5, 0.05)
            review_days = c4.number_input("复盘天数（交易日）", 1, 120, 20)
            rationale = st.text_area(
                "理由（必填）",
                placeholder="当时看到了什么？什么证据会让你改变判断？",
            )
            tags = st.text_input("标签（逗号分隔）")
            signal_ids = st.text_input("关联信号 ID（逗号分隔）")
            submitted = st.form_submit_button("记录决策", type="primary")
        if submitted:
            try:
                record = DecisionJournal(data_dir / "journal").add(
                    as_of=as_of,
                    action=action,
                    rationale=rationale,
                    symbol=symbol or None,
                    confidence=confidence,
                    review_days=int(review_days),
                    tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
                    signal_ids=[item.strip() for item in signal_ids.split(",") if item.strip()],
                )
            except JournalError as exc:
                st.error(f"没有记录：{exc}")
            else:
                st.success(f"已记录 {record['decision_id']}")
                _refresh()

        st.subheader("已记录的决策")
        _show_table(D.journal_entries_frame(bundle["journal_entries"]), height=260)
        st.subheader("到期复盘")
        if st.button("复盘到期决策", key="journal_review_button"):
            try:
                universe = load_universe(config.CONFIG_DIR / "universe.yaml")
                symbols = universe.symbols(date.fromisoformat(as_of))
                with st.spinner("读取价格缓存并复盘…"):
                    result = run_journal_review(
                        as_of, data_dir=data_dir, universe_symbols=symbols
                    )
            except Exception as exc:  # noqa: BLE001 - the page must show, not crash
                st.error(f"复盘失败：{exc}")
            else:
                st.session_state["last_journal_review"] = result
                _refresh()
        last = st.session_state.get("last_journal_review")
        if last and last.get("as_of") == as_of:
            st.info(
                f"本次新增复盘 {last['n_new_reviews']} 条"
                + (f"；{last['note']}" if last.get("note") else "")
            )
        _show_table(D.journal_reviews_frame(bundle["journal_reviews"]))
        st.caption(
            f"复盘写 `data/journal/reviews.jsonl`；当日摘要 `{bundle['paths']['journal_review']}`。"
        )

    with review_tab:
        c1, c2 = st.columns([1, 2])
        if c1.button("生成／更新周期成长报告", type="primary"):
            with st.spinner("汇总流程、证据、决策与风险…"):
                result = run_growth_review(as_of, data_dir=data_dir)
            st.session_state["last_growth_review"] = result
            _refresh()
        c2.caption(
            "周期报告是确定性的：它不会把 0/385 写成「稳步积累」。"
            "默认窗口 30 个交易日。"
        )
        last = st.session_state.get("last_growth_review")
        markdown = (last or {}).get("markdown") or bundle.get("growth_review_markdown")
        if markdown:
            st.markdown(markdown)
            st.download_button(
                "下载成长报告",
                data=markdown.encode("utf-8"),
                file_name=f"review_{as_of}.md",
                mime="text/markdown",
            )
        else:
            st.info("还没有周期报告。点击上面的按钮生成。")


def render_health(bundle: dict[str, Any], as_of: str) -> None:
    health = bundle["health"]
    st.title("数据健康")
    st.caption(_date_label(as_of))

    collect = bundle["collect"]
    if collect:
        columns = st.columns(4)
        columns[0].metric("数据集", collect.get("dataset_count", 0))
        columns[1].metric("采集状态", "正常" if collect.get("ok") else "有失败")
        columns[2].metric("失败项", len(collect.get("failures") or []))
        columns[3].metric("快照", collect.get("snapshot_id") or "未生成")
        failures = collect.get("failures") or []
        if failures:
            with st.expander(f"采集失败 / 缺口（{len(failures)}）"):
                _show_table(pd.DataFrame(failures), height=260)
        quality = (collect.get("quality") or {}).get("unavailable")
        if isinstance(quality, dict) and quality:
            with st.expander("已登记但当前不可用的数据源"):
                st.json(quality)

    if not health:
        st.info("当日还没有健康检查文件。请到「运行流水线」运行 `health`。")
        return

    columns = st.columns(4)
    columns[0].metric("检查结果", "通过" if health.get("ok") else "失败")
    columns[1].metric("错误", health.get("errors", 0))
    columns[2].metric("警告", health.get("warnings", 0))
    columns[3].metric("最后交易日", health.get("last_trading_day") or "—")

    frame = D.health_frame(health)
    filters = st.columns(2)
    level = filters[0].selectbox(
        "级别", ["全部", "错误", "警告", "正常"], index=0, key="health_level"
    )
    query = filters[1].text_input("搜索数据集或标的", key="health_query")
    view = frame.copy()
    if level != "全部":
        view = view[view["级别"] == level]
    if query:
        mask = view["数据集"].astype(str).str.contains(query) | view["标的"].astype(str).str.contains(query)
        view = view[mask]
    st.caption(f"展示 {len(view)} / {len(frame)} 项")
    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        height=460,
        column_config={
            "滞后天数": st.column_config.NumberColumn(format="%d 天"),
            "行数": st.column_config.NumberColumn(format="%d"),
            "空值率": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption(
        "健康检查的错误会让风控的硬约束失败；所以它必须排在风控与成长之前运行。"
    )


def render_research(bundle: dict[str, Any], as_of: str) -> None:
    st.title("因子与回测")
    st.caption(_date_label(as_of))

    factor = bundle["factor_report"]
    if not factor:
        st.info("当日没有因子报告。到「运行流水线」运行 `factor`。")
    else:
        meta = factor.get("meta") or {}
        columns = st.columns(4)
        columns[0].metric("标的数", factor.get("n_symbols", 0))
        columns[1].metric("检验数", meta.get("m_tests", 0))
        columns[2].metric("FDR q", meta.get("fdr_q", "—"))
        significant = sum(
            1 for item in factor.get("tests", []) if item.get("significant_neutral")
        )
        columns[3].metric("中性因子显著", significant, help="BH-FDR 校正后显著的检验数量。")
        horizons = sorted({int(item.get("horizon", 0)) for item in factor.get("tests", [])})
        if not horizons:
            st.info("因子报告里没有检验结果。")
        else:
            horizon = st.selectbox(
                "视界（交易日）", horizons, index=min(2, len(horizons) - 1)
            )
            frame = D.factor_frame(factor, horizon=int(horizon))
            st.dataframe(
                frame,
                hide_index=True,
                width="stretch",
                column_config={
                    "中性 IC": st.column_config.NumberColumn(format="%.4f"),
                    "NW t": st.column_config.NumberColumn(format="%.2f"),
                    "ICIR": st.column_config.NumberColumn(format="%.2f"),
                    "q 值": st.column_config.NumberColumn(format="%.3f"),
                    "DSR": st.column_config.NumberColumn(format="%.2f"),
                    "覆盖率": st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.caption(
                "主指标是类别中性 IC：先减掉当日所属类别均值，避免「哪个类别涨得好」冒充选股能力。"
                "`validated=false` 的依据就在这里：显著因子为 0。"
            )

    st.divider()
    backtest = bundle["backtest"]
    st.subheader("回测")
    if not backtest:
        st.info("当日目录下没有回测 JSON。回测是按需研究命令，不进入每日 cron。")
        return
    window = backtest.get("window") or {}
    st.caption(
        f"{window.get('start')} → {window.get('end')} · "
        f"成本 {backtest.get('cost_model', {}).get('one_way_bps', '—')} bp/边 · "
        f"策略指纹 `{backtest.get('policy_fingerprint') or '—'}`"
    )
    strategies = D.strategies_frame(backtest)
    display = strategies.copy()
    for column in ("CAGR", "年化波动", "最大回撤", "年化成本"):
        display[column] = display[column].map(D.pct)
    display["Sharpe"] = display["Sharpe"].map(lambda value: D.num(value, 3))
    display["年换手"] = display["年换手"].map(lambda value: D.num(value, 2) + "x")
    _show_table(display)
    diagnostics = D.backtest_diagnostics(backtest)
    columns = st.columns(3)
    columns[0].metric("PBO", D.pct(diagnostics.get("pbo"), 1))
    columns[1].metric("DSR", "见 JSON", help="每个策略的 DSR 在 JSON 的 strategies.*.metrics 中。")
    columns[2].metric("CPCV 分组", f"{diagnostics.get('cpcv_groups')} × {diagnostics.get('cpcv_blocks')}")
    p05 = diagnostics.get("cpcv_p05") or {}
    if p05:
        frame = pd.DataFrame(
            [
                {"策略": D.STRATEGY_LABELS.get(name, name), "5% 分位夏普": value}
                for name, value in p05.items()
            ]
        )
        _show_table(frame, column_config={"5% 分位夏普": st.column_config.NumberColumn(format="%.2f")})
    st.caption(
        "PBO 是「组合内最优策略在样本外落到中位数以下」的频率；CPCV 的 5% 分位夏普为负，"
        "说明最差路径很痛。评价策略的主指标是净成本增量，不是 0 成本下的绝对收益。"
    )


def _render_step_result(result: dict[str, Any]) -> None:
    if result["ok"]:
        st.success(f"完成（{result['elapsed']:.1f}s）")
    else:
        st.error(f"失败（exit {result['returncode']}，{result['elapsed']:.1f}s）")
    if result.get("output"):
        with st.expander("运行输出", expanded=not result["ok"]):
            st.code(result["output"], language="text")


def render_pipeline(as_of: str, data_dir: Path) -> None:
    st.title("运行流水线")
    st.caption(
        "这里调用与 cron 完全相同的命令，使用同一个解释器与数据目录。"
        "采集需要联网，报告可能调用 LLM（会产生费用）。"
    )
    st.warning(
        "在服务器上，18:30 之后 cron 会自动运行同一套流程；重复点击不会损坏数据，"
        "但会重复消耗时间与 API 调用。"
    )

    controls = st.columns([1, 1, 1])
    run_date = controls[0].date_input("运行日期", value=date.fromisoformat(as_of)).isoformat()
    no_llm = controls[1].checkbox("报告只走确定性模板（不调用 LLM）", value=False)
    controls[2].caption(
        f"LLM key：{'已配置' if os.environ.get('DEEPSEEK_API_KEY') else '未配置（报告将回退模板）'}"
    )

    if st.button("运行当日完整流程", type="primary"):
        st.caption("顺序：" + " → ".join(STEP_BY_ID[key].label for key in DAILY_ORDER))
        for step_id in DAILY_ORDER:
            step = STEP_BY_ID[step_id]
            label = step.label + ("（较慢）" if step.slow else "")
            with st.status(label, expanded=True) as status:
                st.caption(step.description)
                result = run_step(step_id, run_date, no_llm=no_llm, data_dir=data_dir)
                if result.get("output"):
                    st.code(result["output"], language="text")
                if result["ok"]:
                    status.update(label=f"{label} · 完成（{result['elapsed']:.1f}s）", state="complete")
                else:
                    status.update(label=f"{label} · 失败（exit {result['returncode']}）", state="error")
                    st.stop()
        st.success("流程跑完。刷新后即可看到新产物。")
        if st.button("刷新视图"):
            _refresh()

    st.divider()
    st.subheader("单独运行")
    for step in STEPS:
        with st.expander(f"{step.label} · {step.description}"):
            st.code(display_command(step.id, run_date, no_llm=no_llm), language="bash")
            if step.group == "review":
                st.caption("复盘类命令不进每日流程：决策复盘每天 19:05 由 cron 运行，周期报告每周日 03:30 运行。")
            if st.button("运行", key=f"run_{step.id}"):
                with st.spinner(f"正在运行{step.label}…"):
                    st.session_state[f"result_{step.id}"] = run_step(
                        step.id, run_date, no_llm=no_llm, data_dir=data_dir
                    )
            result = st.session_state.get(f"result_{step.id}")
            if result:
                _render_step_result(result)

    st.divider()
    st.caption(
        "数据目录：`" + str(data_dir) + "`。运行记录不会自动刷新当前页，"
        "需要点击侧边栏的「刷新数据」或上方按钮。"
    )


def main() -> None:
    data_dir = _data_dir()
    dates = D.available_dates(data_dir)

    st.sidebar.title("finagent 研究台")
    st.sidebar.caption("A股 ETF 多因子投研 · 人做最终决策")

    if not dates:
        st.sidebar.warning("还没有任何产物")
        st.title("欢迎使用 finagent 研究台")
        st.info(
            "当前数据目录里还没有信号、权重或报告。请先运行一次采集与流水线：\n\n"
            "`python scripts/collect_daily.py` 然后运行 `python -m finagent.cli factor-report` 等命令，"
            "或直接使用项目里的 `deploy/crontab.example`。"
        )
        st.caption(f"数据目录：`{data_dir}`")
        return

    default_index = 0
    as_of = st.sidebar.selectbox(
        "研究日期",
        dates,
        index=default_index,
        format_func=_date_label,
        key="as_of",
    )
    page = st.sidebar.radio("页面", PAGES, key="page")

    if st.sidebar.button("刷新数据", width="stretch"):
        _refresh()

    st.sidebar.divider()
    st.sidebar.caption(
        f"数据目录：`{data_dir}`\n\n"
        f"LLM：{'已配置' if os.environ.get('DEEPSEEK_API_KEY') else '未配置'}\n\n"
        "全部信号与组合保持 `validated=false`；成长分只衡量过程，不衡量收益。"
    )

    bundle = _bundle(as_of, str(data_dir), _stamp(data_dir))

    if page == "今日总览":
        render_overview(bundle, as_of)
    elif page == "研究报告":
        render_report(bundle, as_of)
    elif page == "信号与组合":
        render_signals(bundle, as_of)
    elif page == "风险与验证":
        render_risk(bundle, as_of)
    elif page == "成长与决策":
        render_growth(bundle, as_of, data_dir)
    elif page == "数据健康":
        render_health(bundle, as_of)
    elif page == "因子与回测":
        render_research(bundle, as_of)
    else:
        render_pipeline(as_of, data_dir)


if __name__ == "__main__":
    main()
