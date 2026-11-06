"""Deterministic fallback report.

It is generated only from the evidence bundle: every number goes through
`_show`, so the same numeric-traceability gate that judges the LLM applies to
the template. If the template itself cannot pass, that is a bug, not a reason
to publish an ungrounded report.
"""

from __future__ import annotations

import math

from finagent.agent.evidence import EvidenceBundle, ReportFacts

REPORT_TITLE = "# finagent 每日研究报告"


def _show(bundle: EvidenceBundle, evidence_id: str, pattern: str = "{:.2f}") -> str:
    """Number only; the prose supplies the unit exactly once."""
    return pattern.format(bundle.by_id(evidence_id).value)


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _signal_lines(bundle: EvidenceBundle, facts: ReportFacts, direction: int, limit: int = 3) -> list[str]:
    rows = [
        row
        for row in facts.signals.get("signals", [])
        if _finite(row.get("composite")) and (row.get("direction", 0) > 0) == (direction > 0)
    ]
    rows.sort(key=lambda row: row["composite"], reverse=direction > 0)
    lines = []
    for row in rows[:limit]:
        symbol = str(row.get("symbol"))
        name = row.get("name", symbol)
        composite = _show(bundle, f"signal:{symbol}:composite")
        confidence = _show(bundle, f"signal:{symbol}:confidence_pct", "{:.1f}")
        lines.append(
            f"- {name}（{symbol}）：合成得分 {composite} [snap:signal:{symbol}:composite]，"
            f"置信度 {confidence}% [snap:signal:{symbol}:confidence_pct]"
        )
    return lines


def render_template(bundle: EvidenceBundle, facts: ReportFacts) -> str:
    as_of = bundle.as_of
    signals = facts.signals
    portfolio = facts.portfolio or {}
    factor = facts.factor or {}
    health = facts.health or {}
    phase = facts.phase_eval or {}
    risk = facts.risk or {}
    value = phase.get("value") or {}
    news = (signals.get("overlays") or {}).get("news") or {}

    n_signals = _show(bundle, f"signals:{as_of}:n_signals", "{:.0f}")
    n_long = _show(bundle, f"signals:{as_of}:n_long", "{:.0f}")
    n_short = _show(bundle, f"signals:{as_of}:n_short", "{:.0f}")
    horizon = _show(bundle, f"signals:{as_of}:horizon", "{:.0f}")
    n_pending = _show(bundle, f"ledger:{as_of}:n_pending", "{:.0f}")

    lines = [
        f"{REPORT_TITLE} · {as_of}",
        "",
        "> 所有数字由代码计算，本报告只做组织与解释；不构成投资建议。",
        "",
        "## 结论",
        f"- 当日共产生 {n_signals} 条信号 [snap:signals:{as_of}:n_signals]，"
        f"其中看多 {n_long} 条 [snap:signals:{as_of}:n_long]、"
        f"看空 {n_short} 条 [snap:signals:{as_of}:n_short]。",
    ]

    if portfolio:
        n_holdings = _show(bundle, f"portfolio:{as_of}:n_holdings", "{:.0f}")
        vol = _show(bundle, f"portfolio:{as_of}:portfolio_vol_pct")
        lines.append(
            f"- 目标组合持有 {n_holdings} 只标的 [snap:portfolio:{as_of}:n_holdings]，"
            f"组合年化波动率 {vol}% [snap:portfolio:{as_of}:portfolio_vol_pct]。"
        )
    if factor:
        n_tests = _show(bundle, f"factor:{as_of}:n_tests", "{:.0f}")
        n_sig = _show(bundle, f"factor:{as_of}:n_significant", "{:.0f}")
        fdr = _show(bundle, f"factor:{as_of}:fdr_q_pct", "{:.0f}")
        lines.append(
            f"- 因子检验共 {n_tests} 项 [snap:factor:{as_of}:n_tests]，"
            f"BH-FDR（q={fdr}%）校正后显著 {n_sig} 项 "
            f"[snap:factor:{as_of}:n_significant] [snap:factor:{as_of}:fdr_q_pct]。"
        )
    if risk and risk.get("status") == "blocked":
        hard_failed = _show(bundle, f"risk:{as_of}:n_hard_failed", "{:.0f}")
        lines.append(
            f"- 风控硬约束失败 {hard_failed} 项 [snap:risk:{as_of}:n_hard_failed]，"
            "本报告触发风控阻断，不给出组合层面的正常结论。"
        )
    lines.append(
        f"- 以上信号全部标记 validated=false，只能作为研究观察；"
        f"账本尚有 {n_pending} 条待结算 [snap:ledger:{as_of}:n_pending]。"
    )
    lines.append("")

    lines.append("## 信号")
    longs = _signal_lines(bundle, facts, direction=1)
    shorts = _signal_lines(bundle, facts, direction=-1)
    if longs:
        lines.append("看多（按合成得分排序）：")
        lines.extend(longs)
    else:
        lines.append("当日没有满足条件的看多信号。")
    if shorts:
        lines.append("")
        lines.append("看空（按合成得分排序）：")
        lines.extend(shorts)
    else:
        lines.append("")
        lines.append("当日没有满足条件的看空信号。")
    lines.append(
        f"信号持有期 {horizon} 个交易日 [snap:signals:{as_of}:horizon]，"
        "到期后由预测账本自动结算。"
    )
    lines.append("")

    lines.append("## 组合")
    if portfolio:
        n_holdings = _show(bundle, f"portfolio:{as_of}:n_holdings", "{:.0f}")
        n_symbols = _show(bundle, f"portfolio:{as_of}:n_symbols", "{:.0f}")
        vol = _show(bundle, f"portfolio:{as_of}:portfolio_vol_pct")
        weighted = _show(bundle, f"portfolio:{as_of}:weighted_vol_pct")
        cap = _show(bundle, f"portfolio:{as_of}:asset_cap_pct", "{:.0f}")
        lines.append(
            f"- 在 {n_symbols} 只候选 [snap:portfolio:{as_of}:n_symbols] 中持有 {n_holdings} 只"
            f" [snap:portfolio:{as_of}:n_holdings]，单标的权重上限 {cap}%"
            f" [snap:portfolio:{as_of}:asset_cap_pct]。"
        )
        lines.append(
            f"- 组合年化波动率 {vol}% [snap:portfolio:{as_of}:portfolio_vol_pct]，"
            f"持仓加权平均 {weighted}% [snap:portfolio:{as_of}:weighted_vol_pct]；"
            "差额来自类别预算与标的相关性。"
        )
        exposures = []
        for category in sorted(portfolio.get("category_exposure") or {}):
            eid = f"portfolio:{as_of}:exposure:{category}_pct"
            bid = f"portfolio:{as_of}:budget:{category}_pct"
            if eid in bundle.ids and bid in bundle.ids:
                exposures.append(
                    f"{category} {_show(bundle, eid)}% [snap:{eid}]"
                    f"（预算 {_show(bundle, bid)}% [snap:{bid}]）"
                )
        if exposures:
            lines.append("- 类别暴露：" + "，".join(exposures) + "。")
        holdings = sorted(
            (h for h in portfolio.get("holdings", []) if _finite(h.get("weight"))),
            key=lambda h: h["weight"],
            reverse=True,
        )[:5]
        if holdings:
            parts = []
            for holding in holdings:
                symbol = str(holding.get("symbol"))
                weight = _show(bundle, f"holding:{symbol}:weight_pct")
                parts.append(
                    f"{holding.get('name', symbol)}（{symbol}） {weight}% "
                    f"[snap:holding:{symbol}:weight_pct]"
                )
            lines.append("- 权重前五：" + "，".join(parts) + "。")
    else:
        lines.append("本次没有找到组合文件，组合层面的数字从略。")
    lines.append("")

    lines.append("## 数据与限制")
    if health:
        errors = _show(bundle, f"health:{as_of}:errors", "{:.0f}")
        warnings = _show(bundle, f"health:{as_of}:warnings", "{:.0f}")
        lines.append(
            f"- 数据健康检查：errors {errors} 项 [snap:health:{as_of}:errors]，"
            f"warnings {warnings} 项 [snap:health:{as_of}:warnings]。"
        )
    else:
        lines.append("- 本次没有找到当日的数据健康检查文件，数据新鲜度未在报告中确认。")
    if bundle.missing:
        lines.append(f"- 缺失的工件：{'、'.join(bundle.missing)}；相关结论已从略。")
    if risk and f"risk:{as_of}:n_checks" in bundle.ids:
        n_checks = _show(bundle, f"risk:{as_of}:n_checks", "{:.0f}")
        hard_failed = _show(bundle, f"risk:{as_of}:n_hard_failed", "{:.0f}")
        soft_failed = _show(bundle, f"risk:{as_of}:n_soft_failed", "{:.0f}")
        lines.append(
            f"- 风控检查 {n_checks} 项 [snap:risk:{as_of}:n_checks]："
            f"硬约束失败 {hard_failed} 项 [snap:risk:{as_of}:n_hard_failed]，"
            f"软约束失败 {soft_failed} 项 [snap:risk:{as_of}:n_soft_failed]；"
            f"状态 {risk.get('status')}。"
        )
    lines.append(
        "- 存续偏差：股票池按当前存续标的构建，已退市或当时尚未上市的标的没有被完整纳入。"
    )
    lines.append(
        "- 新闻叠加："
        + ("已应用，但只影响最新一日且有上限。" if news.get("available") else "不可用，本次信号未做新闻调整。")
    )
    lines.append(
        "- 因子与回测结果存在多重检验、窗口敏感和交易成本问题；"
        "信号仍为 validated=false，不能当作已经被验证的策略。"
    )
    if value.get("breadth"):
        n_eff = _show(bundle, "breadth:n_eff")
        avg_corr = _show(bundle, "breadth:avg_corr_pct")
        lines.append(
            f"- 有效广度：相关性调整后约 {n_eff} 只 [snap:breadth:n_eff]，"
            f"标的平均相关系数 {avg_corr}% [snap:breadth:avg_corr_pct]；"
            "分散化空间有限。"
        )
    lines.append("- 本报告不构成投资建议。")
    lines.append("")

    lines.append("## 证伪条件")
    lines.append("- 若合成得分翻转为负，当前方向的观点失效（阈值由信号文件给出）。")
    lines.append(
        f"- 若 {horizon} 个交易日后的相对收益为负，本批信号在账本中被记为未命中"
        f" [snap:signals:{as_of}:horizon]。"
    )
    if factor:
        fdr = _show(bundle, f"factor:{as_of}:fdr_q_pct", "{:.0f}")
        lines.append(
            f"- 若后续数据下因子中性 IC 的 q 值仍高于 {fdr}% [snap:factor:{as_of}:fdr_q_pct]，"
            "则不把因子结果当作有效证据。"
        )
    ledger_eval = value.get("ledger") or {}
    if ledger_eval.get("required_settled_5pct") and "ledger:required_settled_5pct" in bundle.ids:
        required = _show(bundle, "ledger:required_settled_5pct", "{:.0f}")
        lines.append(
            f"- 账本需要约 {required} 条结算样本 [snap:ledger:required_settled_5pct]"
            "才能对命中率给出有意义的区间；在此之前不做能力判断。"
        )
    else:
        lines.append("- 账本结算样本不足，命中率尚不能用于判断信号能力。")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
