# ============================================
# Hermes 治理层
# 功能：当确定性规则与 LLM 判断冲突时做出最终裁决
# 核心原则：
#   1. 法律/合规规则 → 绝对优先，LLM 不可覆盖
#   2. 风控硬性规则 → 需人工审批才可覆盖
#   3. 风控建议规则 → LLM 可覆盖，但需记录
#   4. 每次裁决生成完整的溯源链，支持事后审计
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # JSON 序列化
import hashlib  # 哈希（生成溯源码）
from typing import List, Dict, Optional, Any  # 类型注解
from dataclasses import dataclass, field  # 数据类
from datetime import datetime  # 时间戳
from enum import IntEnum  # 枚举

# 导入确定性规则引擎（周一）
from deterministic_rules import (
    DeterministicRuleResult,
    DeterministicRuleEngine,
    RulePriority
)

# 导入法规知识图谱（周二）
from legal_kg import LegalQueryService


# ============================================
# 第 1 步：定义冲突类型和裁决结果
# ============================================

class ConflictType:
    """冲突类型常量"""
    HARD_BLOCK = "hard_block"           # 硬拦截——规则禁止，LLM 必须服从
    NEEDS_APPROVAL = "needs_approval"   # 需审批——规则拦截但 LLM 认为可执行
    LLM_OVERRIDE = "llm_override"       # LLM 覆盖——LLM 推翻了低优先级规则
    NO_CONFLICT = "no_conflict"         # 无冲突——规则和 LLM 都同意


class FinalAction:
    """最终决策动作"""
    APPROVE = "批准执行"      # 批准交易
    BLOCK = "拦截禁止"        # 禁止交易
    ESCALATE = "上报审批"     # 需要人工审批
    FLAGGED = "标记执行"      # 执行但标记（有警告但放行）


@dataclass
class ConflictItem:
    """
    单个冲突项

    属性：
    - rule_result: 触发拦截的规则结果
    - llm_opinion: LLM 的判断（如"可以交易，因为..."）
    - conflict_type: 冲突类型
    - resolution: 裁决结果描述
    """
    rule_result: DeterministicRuleResult   # 规则结果
    llm_opinion: str = ""                  # LLM 意见
    conflict_type: str = ConflictType.NO_CONFLICT  # 冲突类型
    resolution: str = ""                   # 裁决结果


@dataclass
class GovernanceDecision:
    """
    Hermes 治理层的最终裁决

    属性：
    - decision_id: 裁决 ID（可审计）
    - final_action: 最终决策动作
    - conflicts: 所有冲突项
    - trace_id: 溯源码（SHA256）
    - trace_chain: 溯源链文本
    - legal_references: 引用的法律条文
    - decided_at: 裁决时间
    """
    decision_id: str = ""                      # 裁决 ID
    final_action: str = FinalAction.APPROVE    # 最终动作
    conflicts: List[ConflictItem] = field(default_factory=list)  # 冲突列表
    trace_id: str = ""                         # 溯源码
    trace_chain: str = ""                      # 溯源链
    legal_references: List[str] = field(default_factory=list)  # 法律引用
    decided_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "decision_id": self.decision_id,
            "final_action": self.final_action,
            "conflicts": [
                {
                    "rule_name": c.rule_result.rule_name,
                    "rule_passed": c.rule_result.passed,
                    "priority": c.rule_result.priority.value,
                    "llm_opinion": c.llm_opinion,
                    "conflict_type": c.conflict_type,
                    "resolution": c.resolution
                }
                for c in self.conflicts
            ],
            "trace_id": self.trace_id,
            "legal_references": self.legal_references,
            "decided_at": self.decided_at
        }

    def to_audit_report(self) -> str:
        """
        生成可审计的完整裁决报告

        返回：
            Markdown 格式的审计报告文本
        """
        lines = []
        lines.append("# 🔍 Hermes 治理层 · 裁决审计报告")
        lines.append("")
        lines.append(f"**裁决 ID**：{self.decision_id}")
        lines.append(f"**裁决时间**：{self.decided_at}")
        lines.append(f"**溯源码**：`{self.trace_id}`")
        lines.append(f"**最终决策**：{self.final_action}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 冲突详情
        if self.conflicts:
            lines.append("## ⚠️ 冲突详情")
            lines.append("")
            for i, c in enumerate(self.conflicts, 1):
                icon = "🚫" if c.conflict_type == ConflictType.HARD_BLOCK else "⚠️"
                lines.append(f"### {i}. {icon} {c.rule_result.rule_name}")
                lines.append(f"- **规则结果**：{'通过' if c.rule_result.passed else '拦截'}")
                lines.append(f"- **规则优先级**：{c.rule_result.priority.value}（{'不可覆盖' if c.rule_result.priority.value >= 80 else '可覆盖'}）")
                lines.append(f"- **LLM 意见**：{c.llm_opinion}")
                lines.append(f"- **冲突类型**：{c.conflict_type}")
                lines.append(f"- **裁决**：{c.resolution}")
                lines.append(f"- **法律依据**：{c.rule_result.legal_source}")
                lines.append("")
        else:
            lines.append("## ✅ 无冲突")
            lines.append("所有规则和 LLM 意见一致，交易可直接执行。")
            lines.append("")

        # 溯源链
        lines.append("---")
        lines.append("")
        lines.append("## 🔗 决策溯源链")
        lines.append("")
        lines.append("```")
        lines.append(self.trace_chain)
        lines.append("```")
        lines.append("")

        # 法律引用
        if self.legal_references:
            lines.append("---")
            lines.append("")
            lines.append("## 📜 引用的法律条文")
            lines.append("")
            for ref in self.legal_references:
                lines.append(f"- {ref}")

        return "\n".join(lines)


# ============================================
# 第 2 步：Hermes 治理引擎
# ============================================

class HermesGovernor:
    """
    Hermes 治理引擎

    裁决逻辑：
    1. 如果规则优先级 >= 80（法律/合规/交易所）→ 规则说了算，LLM 不可覆盖
    2. 如果规则优先级 >= 70（风控硬性）→ 规则拦截但允许 LLM 申请人工审批
    3. 如果规则优先级 < 70（风控建议）→ LLM 可覆盖，但需要记录
    4. 如果规则通过了 → 无冲突，直接执行

    使用方式：
        governor = HermesGovernor()
        decision = governor.resolve(rule_results, llm_opinion)
    """

    # 优先级阈值
    HARD_BLOCK_THRESHOLD = 80     # >= 80：规则绝对优先
    NEEDS_APPROVAL_THRESHOLD = 70  # >= 70：需人工审批
    # < 70：LLM 可覆盖

    def __init__(self):
        """初始化治理引擎"""
        # 法规查询服务（周二的知识图谱）
        self.legal_service = LegalQueryService()
        print("✅ Hermes 治理引擎已初始化")

    def resolve(
        self,
        rule_results: List[DeterministicRuleResult],
        llm_opinion: str = "",
        intent_summary: str = ""
    ) -> GovernanceDecision:
        """
        裁决规则结果和 LLM 意见之间的冲突

        参数：
            rule_results: 确定性规则引擎的检查结果列表
            llm_opinion: LLM 的分析意见
            intent_summary: 交易意图摘要（用于溯源）

        返回：
            GovernanceDecision 对象，包含最终裁决和完整溯源链
        """
        # 生成裁决 ID
        decision_id = f"GOV-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 冲突列表
        conflicts = []
        # 法律引用列表
        legal_refs = []
        # 溯源链构建
        trace_parts = []

        # 默认最终动作
        final_action = FinalAction.APPROVE

        # 逐条分析规则结果
        for result in rule_results:
            priority = result.priority

            if result.passed:
                # 规则通过 → 无冲突
                trace_parts.append(
                    f"✅ {result.rule_name}：通过"
                )
                legal_refs.append(result.legal_source)
                continue

            # 规则未通过 → 存在冲突
            if priority >= self.HARD_BLOCK_THRESHOLD:
                # 法律/合规规则 → 硬拦截
                conflict = ConflictItem(
                    rule_result=result,
                    llm_opinion=llm_opinion,
                    conflict_type=ConflictType.HARD_BLOCK,
                    resolution=(
                        f"规则优先级 {priority} >= {self.HARD_BLOCK_THRESHOLD}，"
                        f"属于法律/合规规则，LLM 不可覆盖，交易必须拦截。"
                        f"法律依据：{result.legal_source}"
                    )
                )
                conflicts.append(conflict)
                final_action = FinalAction.BLOCK
                trace_parts.append(
                    f"🚫 {result.rule_name}：触发硬拦截（优先级 {priority}），交易禁止"
                )

                # 查询处罚风险
                risk = self.legal_service.get_penalty_risk(result.rule_name)
                trace_parts.append(f"   ⚠️ 处罚风险：{risk[:100]}...")

            elif priority >= self.NEEDS_APPROVAL_THRESHOLD:
                # 风控硬性 → 需审批
                conflict = ConflictItem(
                    rule_result=result,
                    llm_opinion=llm_opinion,
                    conflict_type=ConflictType.NEEDS_APPROVAL,
                    resolution=(
                        f"规则优先级 {priority} >= {self.NEEDS_APPROVAL_THRESHOLD}，"
                        f"属于风控硬性规则。LLM 可以申请覆盖，但需要人工审批。"
                    )
                )
                conflicts.append(conflict)
                if final_action != FinalAction.BLOCK:
                    final_action = FinalAction.ESCALATE
                trace_parts.append(
                    f"⚠️ {result.rule_name}：需人工审批（优先级 {priority}）"
                )

            else:
                # 风控建议 → LLM 可覆盖
                conflict = ConflictItem(
                    rule_result=result,
                    llm_opinion=llm_opinion,
                    conflict_type=ConflictType.LLM_OVERRIDE,
                    resolution=(
                        f"规则优先级 {priority} < {self.NEEDS_APPROVAL_THRESHOLD}，"
                        f"属于风控建议。LLM 可以覆盖此规则，但需记录在案。"
                    )
                )
                conflicts.append(conflict)
                trace_parts.append(
                    f"💡 {result.rule_name}：被 LLM 覆盖（优先级 {priority}），已记录"
                )

        # 如果没有冲突
        if not conflicts:
            trace_parts.insert(0, "✅ 所有规则通过，无冲突")

        # 构建溯源链
        trace_chain = "\n".join(trace_parts)

        # 生成溯源码（SHA256 哈希）
        trace_data = json.dumps({
            "decision_id": decision_id,
            "final_action": final_action,
            "conflicts": [c.conflict_type for c in conflicts],
            "timestamp": datetime.now().isoformat()
        }, sort_keys=True)
        trace_id = hashlib.sha256(trace_data.encode()).hexdigest()[:16]

        # 构建裁决结果
        decision = GovernanceDecision(
            decision_id=decision_id,
            final_action=final_action,
            conflicts=conflicts,
            trace_id=trace_id,
            trace_chain=trace_chain,
            legal_references=legal_refs,
            decided_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        return decision

    def resolve_with_audit(
        self,
        rule_results: List[DeterministicRuleResult],
        llm_opinion: str = "",
        intent_summary: str = ""
    ) -> tuple:
        """
        执行裁决并返回裁决对象 + 审计报告

        返回：
            (GovernanceDecision, 审计报告文本)
        """
        decision = self.resolve(rule_results, llm_opinion, intent_summary)
        audit_report = decision.to_audit_report()
        return decision, audit_report


# ============================================
# 第 3 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Hermes 治理层测试")
    print("=" * 60)

    # 创建治理引擎
    governor = HermesGovernor()

    # ============================================
    # 场景 1：所有规则通过 → 无冲突
    # ============================================
    print("\n" + "=" * 60)
    print("场景 1：所有规则通过（无冲突）")
    print("=" * 60)

    # 模拟全部通过的规则结果
    all_passed = [
        DeterministicRuleResult(
            rule_name="涨跌停限制检查",
            rule_id="DET-001",
            passed=True,
            detail="价格在合理范围内",
            legal_source="《交易规则》第3.3.1条",
            priority=RulePriority.EXCHANGE
        ),
        DeterministicRuleResult(
            rule_name="T+1 交割制度检查",
            rule_id="DET-002",
            passed=True,
            detail="T+1 检查通过",
            legal_source="《证券法》第39条",
            priority=RulePriority.LEGAL
        ),
        DeterministicRuleResult(
            rule_name="印花税计算",
            rule_id="DET-003",
            passed=True,
            detail="应缴印花税 750.00 元",
            legal_source="《印花税法》",
            priority=RulePriority.TAX
        )
    ]

    decision_1, report_1 = governor.resolve_with_audit(
        all_passed,
        llm_opinion="所有指标正常，建议执行",
        intent_summary="买入茅台 1000 股"
    )

    print(f"最终决策：{decision_1.final_action}")
    print(f"溯源码：{decision_1.trace_id}")

    # ============================================
    # 场景 2：触发涨跌停 → 硬拦截
    # ============================================
    print("\n" + "=" * 60)
    print("场景 2：触发涨跌停（法律规则 → 硬拦截）")
    print("=" * 60)

    has_block = [
        DeterministicRuleResult(
            rule_name="涨跌停限制检查",
            rule_id="DET-001",
            passed=False,
            detail="触发创业板涨停限制：涨跌幅 21.5% 超过 20%",
            legal_source="《交易规则》第3.3.1条",
            priority=RulePriority.EXCHANGE,  # 优先级 90 >= 80
            evidence={"change_pct": "21.5%", "limit": "20%"}
        ),
        DeterministicRuleResult(
            rule_name="T+1 交割制度检查",
            rule_id="DET-002",
            passed=True,
            detail="T+1 检查通过",
            legal_source="《证券法》第39条",
            priority=RulePriority.LEGAL
        )
    ]

    decision_2, report_2 = governor.resolve_with_audit(
        has_block,
        llm_opinion="虽然触发涨停，但考虑到重大利好，建议仍然买入",
        intent_summary="买入宁德时代 1000 股（已涨停）"
    )

    print(f"最终决策：{decision_2.final_action}")
    print(f"溯源码：{decision_2.trace_id}")
    print(f"冲突数：{len(decision_2.conflicts)}")

    # ============================================
    # 场景 3：风控硬性拦截 → 需审批
    # ============================================
    print("\n" + "=" * 60)
    print("场景 3：关联交易超限（风控硬性 → 需审批）")
    print("=" * 60)

    needs_approval = [
        DeterministicRuleResult(
            rule_name="关联交易合规检查",
            rule_id="DET-004",
            passed=False,
            detail="关联交易金额占比 8.5% 超过 5% 披露阈值",
            legal_source="《信息披露管理办法》第12条",
            priority=RulePriority.CSRC,  # 优先级 85 >= 80
            evidence={"ratio": "8.5%", "threshold": "5%"}
        )
    ]

    decision_3, report_3 = governor.resolve_with_audit(
        needs_approval,
        llm_opinion="虽然是关联交易，但价格公允，建议批准",
        intent_summary="向关联方出售资产 8500 万"
    )

    print(f"最终决策：{decision_3.final_action}")
    print(f"溯源码：{decision_3.trace_id}")

    # ============================================
    # 打印审计报告（场景 2）
    # ============================================
    print("\n" + "=" * 60)
    print("📄 审计报告预览（场景 2）：")
    print("=" * 60)
    print(report_2[:1000])
    print("...")

    # ============================================
    # 保存审计报告
    # ============================================
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    report_file = os.path.join(data_dir, f"governance_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_2)

    print(f"\n✅ 审计报告已保存：{report_file}")

    print("\n" + "=" * 60)
    print("✅ Hermes 治理层测试完成")
    print("=" * 60)