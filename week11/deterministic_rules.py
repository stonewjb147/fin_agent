# ============================================
# 确定性规则引擎
# 功能：执行精确的、不可被 LLM 覆盖的交易规则检查
# 包含四条核心规则：
#   1. 涨跌停限制检查
#   2. T+1 交割制度检查
#   3. 印花税计算
#   4. 关联交易合规检查
#
# 每条规则输出：
#   - 是否通过（True/False）
#   - 详细信息
#   - 引用法律条文
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 为了复用前几周的 TradeIntent，需要把 week7 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))

from dataclasses import dataclass, field, asdict  # 数据类
from typing import List, Dict, Optional, Callable  # 类型注解
from enum import Enum  # 枚举类型
from datetime import datetime  # 时间戳
import json  # JSON 序列化

# 导入交易意图模型（从 week7 复用）
from trade_intent import TradeIntent


# ============================================
# 第 1 步：定义规则结果数据结构
# ============================================

class RulePriority(int, Enum):
    """规则优先级枚举——数值越高越不可被覆盖"""
    LEGAL = 100           # 法律合规——绝对不可覆盖
    EXCHANGE = 90         # 交易所规则——绝对不可覆盖
    CSRC = 85             # 证监会规定——绝对不可覆盖
    TAX = 80              # 税务规则——不可覆盖
    RISK_HARD = 70        # 风控硬性——需审批才可覆盖
    RISK_SOFT = 50        # 风控建议——LLM 可覆盖但需记录


@dataclass
class DeterministicRuleResult:
    """
    确定性规则的检查结果

    与 week7 的 RiskCheckResult 的区别：
    - 增加了 legal_source 字段（法律条文引用）
    - 增加了 priority 字段（规则优先级，用于冲突裁决）
    - 增加了 evidence 字段（支持审计的证据）

    属性：
    - rule_name: 规则名称（如"涨跌停限制"）
    - rule_id: 规则唯一标识（如"DET-001"）
    - passed: 是否通过检查
    - detail: 详细信息（如"触发涨停限制 10.5% >= 10%"）
    - legal_source: 法律条文引用（如"《上海证券交易所交易规则》第3.3.1条"）
    - priority: 规则优先级（决定冲突时谁说了算）
    - evidence: 审计证据（当前价格、参考价格、阈值等具体数值）
    - checked_at: 检查时间
    """
    rule_name: str                    # 规则名称
    rule_id: str                      # 规则 ID
    passed: bool = True               # 是否通过
    detail: str = ""                  # 详细信息
    legal_source: str = ""            # 法律条文引用
    priority: RulePriority = RulePriority.EXCHANGE  # 优先级
    evidence: Dict = field(default_factory=dict)  # 审计证据
    checked_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        """转为字典（方便 JSON 序列化和 LangGraph 传递）"""
        d = asdict(self)
        d["priority"] = self.priority.value
        return d

    def to_audit_log(self) -> str:
        """生成审计日志条目"""
        icon = "✅" if self.passed else "🚫"
        return (
            f"{icon} [{self.rule_id}] {self.rule_name}\n"
            f"   结果：{'通过' if self.passed else '拦截'}\n"
            f"   详情：{self.detail}\n"
            f"   依据：{self.legal_source}\n"
            f"   证据：{json.dumps(self.evidence, ensure_ascii=False)}"
        )


# ============================================
# 第 2 步：实现四条核心确定性规则
# ============================================

class PriceLimitRule:
    """
    规则1：涨跌停限制检查

    法律依据：《上海证券交易所交易规则》第3.3.1条
    主板 ±10%，创业板 ±20%，科创板 ±20%，北交所 ±30%

    检查逻辑：
    - 计算当前价格相对于昨日收盘价的涨跌幅
    - 如果超过对应板块的涨跌停限制 → 拦截
    """

    RULE_ID = "DET-001"
    RULE_NAME = "涨跌停限制检查"
    LEGAL_SOURCE = "《上海证券交易所交易规则》第3.3.1条、《深圳证券交易所交易规则》第3.3.1条"
    PRIORITY = RulePriority.EXCHANGE

    # 各板块涨跌停比例
    LIMITS = {
        "主板": 0.10,
        "创业板": 0.20,
        "科创板": 0.20,
        "北交所": 0.30,
        "ETF": 0.10,       # ETF 一般跟随主板
        "可转债": 0.20     # 可转债 ±20%（部分无限制）
    }

    @classmethod
    def check(cls, intent: TradeIntent, context: Dict) -> DeterministicRuleResult:
        """
        检查是否触发涨跌停限制

        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - current_price: 当前价格
                - prev_close: 昨日收盘价
                - board_type: 板块类型（主板/创业板/科创板）

        返回：
            DeterministicRuleResult 对象
        """
        # 从上下文获取数据
        current_price = context.get("current_price", 0)
        prev_close = context.get("prev_close", 0)
        board_type = context.get("board_type", "主板")

        # 获取该板块的涨跌停限制
        limit = cls.LIMITS.get(board_type, 0.10)

        # 如果昨收价无效，跳过检查
        if prev_close <= 0:
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=True,
                detail="昨收价数据缺失，跳过涨跌停检查",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={"reason": "prev_close 无效"}
            )

        # 计算涨跌幅
        change_pct = (current_price - prev_close) / prev_close

        # 判断是否触发涨跌停
        if abs(change_pct) >= limit:
            # 触发涨跌停
            direction = "涨停" if change_pct > 0 else "跌停"
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=False,
                detail=(
                    f"触发{board_type}{direction}限制："
                    f"涨跌幅 {change_pct:.2%} 超过 {limit:.1%}"
                ),
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={
                    "current_price": current_price,
                    "prev_close": prev_close,
                    "change_pct": f"{change_pct:.2%}",
                    "limit": f"{limit:.1%}",
                    "board_type": board_type
                }
            )

        # 未触发涨跌停
        return DeterministicRuleResult(
            rule_name=cls.RULE_NAME,
            rule_id=cls.RULE_ID,
            passed=True,
            detail=f"价格在合理范围内（涨跌幅 {change_pct:.2%}，{board_type}限制 ±{limit:.1%}）",
            legal_source=cls.LEGAL_SOURCE,
            priority=cls.PRIORITY,
            evidence={
                "current_price": current_price,
                "prev_close": prev_close,
                "change_pct": f"{change_pct:.2%}",
                "limit": f"{limit:.1%}"
            }
        )


class T1SettlementRule:
    """
    规则2：T+1 交割制度检查

    法律依据：《证券法》第39条
    A 股实行 T+1 交割制度——当日买入的股票，当日不得卖出

    检查逻辑：
    - 如果是卖出操作
    - 检查该标的的持仓中是否有"当日买入"的股份
    - 如果有 → 拦截
    """

    RULE_ID = "DET-002"
    RULE_NAME = "T+1 交割制度检查"
    LEGAL_SOURCE = "《中华人民共和国证券法》第39条"
    PRIORITY = RulePriority.LEGAL

    @classmethod
    def check(cls, intent: TradeIntent, context: Dict) -> DeterministicRuleResult:
        """
        检查是否违反 T+1 制度

        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - positions: 持仓列表，每个持仓包含 buy_date 和 quantity

        返回：
            DeterministicRuleResult 对象
        """
        # 只有卖出才需要检查 T+1
        if intent.direction.value != "卖出":
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=True,
                detail="非卖出操作，无需检查 T+1",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={"action": intent.direction.value}
            )

        # 获取持仓信息
        positions = context.get("positions", [])
        today = context.get("today", datetime.now().strftime("%Y-%m-%d"))

        # 检查是否有当日买入的该标的
        today_bought = 0
        for pos in positions:
            if pos.get("symbol") == intent.symbol and pos.get("buy_date") == today:
                today_bought += pos.get("quantity", 0)

        if today_bought > 0 and intent.quantity > today_bought:
            # 想卖出的数量超过今日之前持有的数量 → 违反 T+1
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=False,
                detail=(
                    f"违反 T+1 制度：今日买入 {today_bought} 股不可卖出，"
                    f"尝试卖出 {intent.quantity} 股"
                ),
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={
                    "today_bought": today_bought,
                    "sell_quantity": intent.quantity,
                    "today": today
                }
            )

        return DeterministicRuleResult(
            rule_name=cls.RULE_NAME,
            rule_id=cls.RULE_ID,
            passed=True,
            detail="T+1 检查通过",
            legal_source=cls.LEGAL_SOURCE,
            priority=cls.PRIORITY,
            evidence={"today_bought": today_bought}
        )


class StampDutyRule:
    """
    规则3：印花税计算

    法律依据：《中华人民共和国印花税法》（2023年修订）
    证券交易印花税：卖出时按成交金额的 0.05% 征收，买入不征

    检查逻辑：
    - 如果是卖出操作 → 计算应缴印花税
    - 检查账户现金是否足够支付
    - 返回税额信息（不拦截，仅提醒）
    """

    RULE_ID = "DET-003"
    RULE_NAME = "印花税计算"
    LEGAL_SOURCE = "《中华人民共和国印花税法》（2023年修订）第2条"
    PRIORITY = RulePriority.TAX

    # 印花税率
    STAMP_DUTY_RATE = 0.0005  # 0.05%

    @classmethod
    def check(cls, intent: TradeIntent, context: Dict) -> DeterministicRuleResult:
        """
        计算印花税

        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - available_cash: 可用现金

        返回：
            DeterministicRuleResult 对象（包含税额）
        """
        # 只有卖出才征印花税
        if intent.direction.value != "卖出":
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=True,
                detail="买入不征印花税",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={"action": "买入", "tax": 0}
            )

        # 计算成交金额和印花税
        trade_amount = intent.total_amount
        tax = round(trade_amount * cls.STAMP_DUTY_RATE, 2)

        # 检查现金是否足够支付
        available_cash = context.get("available_cash", 0)

        if tax > available_cash:
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=False,
                detail=f"现金不足支付印花税：需 {tax:.2f}，可用 {available_cash:.2f}",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={
                    "trade_amount": trade_amount,
                    "tax_rate": f"{cls.STAMP_DUTY_RATE:.4f}",
                    "tax_amount": tax,
                    "available_cash": available_cash
                }
            )

        return DeterministicRuleResult(
            rule_name=cls.RULE_NAME,
            rule_id=cls.RULE_ID,
            passed=True,
            detail=f"应缴印花税：{tax:.2f} 元（成交金额 {trade_amount:,.2f} × {cls.STAMP_DUTY_RATE:.4f}）",
            legal_source=cls.LEGAL_SOURCE,
            priority=cls.PRIORITY,
            evidence={
                "trade_amount": trade_amount,
                "tax_rate": f"{cls.STAMP_DUTY_RATE:.4f}",
                "tax_amount": tax
            }
        )


class RelatedPartyRule:
    """
    规则4：关联交易合规检查

    法律依据：《上市公司信息披露管理办法》第12条
    与关联方的交易金额超过公司最近一期经审计净资产 5% 的，需披露

    检查逻辑：
    - 判断交易对手是否为关联方
    - 如果是 → 计算交易金额占净资产比例
    - 超过 5% → 警告（需披露）
    """

    RULE_ID = "DET-004"
    RULE_NAME = "关联交易合规检查"
    LEGAL_SOURCE = "《上市公司信息披露管理办法》第12条"
    PRIORITY = RulePriority.CSRC

    # 关联交易披露阈值
    DISCLOSURE_THRESHOLD = 0.05  # 5%

    @classmethod
    def check(cls, intent: TradeIntent, context: Dict) -> DeterministicRuleResult:
        """
        检查关联交易合规

        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - related_parties: 关联方列表
                - net_assets: 公司净资产
                - is_related: 是否关联交易

        返回：
            DeterministicRuleResult 对象
        """
        # 判断是否关联交易
        is_related = context.get("is_related", False)
        if not is_related:
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=True,
                detail="非关联交易，无需额外披露",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={"is_related": False}
            )

        # 是关联交易，计算占比
        trade_amount = intent.total_amount
        net_assets = context.get("net_assets", 1)  # 避免除零

        if net_assets <= 0:
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=False,
                detail="净资产数据异常，无法判断关联交易合规性",
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={"net_assets": net_assets}
            )

        ratio = trade_amount / net_assets

        if ratio >= cls.DISCLOSURE_THRESHOLD:
            # 超过 5%，需要披露
            return DeterministicRuleResult(
                rule_name=cls.RULE_NAME,
                rule_id=cls.RULE_ID,
                passed=False,
                detail=(
                    f"关联交易金额 {trade_amount:,.2f} 占净资产 {net_assets:,.2f} 的 "
                    f"{ratio:.1%}，超过 {cls.DISCLOSURE_THRESHOLD:.0%}，需按规披露"
                ),
                legal_source=cls.LEGAL_SOURCE,
                priority=cls.PRIORITY,
                evidence={
                    "trade_amount": trade_amount,
                    "net_assets": net_assets,
                    "ratio": f"{ratio:.1%}",
                    "threshold": f"{cls.DISCLOSURE_THRESHOLD:.0%}"
                }
            )

        return DeterministicRuleResult(
            rule_name=cls.RULE_NAME,
            rule_id=cls.RULE_ID,
            passed=True,
            detail=f"关联交易比例 {ratio:.1%} 在披露阈值以内",
            legal_source=cls.LEGAL_SOURCE,
            priority=cls.PRIORITY,
            evidence={"ratio": f"{ratio:.1%}"}
        )


# ============================================
# 第 3 步：搭建确定性规则引擎
# ============================================

class DeterministicRuleEngine:
    """
    确定性规则引擎

    管理所有确定性规则，提供统一的检查接口。
    与 week7 的 RiskEngine 的区别：
    - 本引擎所有规则都是精确计算，不存在 LLM 判断
    - 每条结果都附带法律条文引用
    - 规则有明确的优先级，用于冲突裁决
    """

    def __init__(self):
        """初始化引擎，注册四条核心规则"""
        # 规则注册表：rule_id → (规则类, 是否启用)
        self._rules: Dict[str, tuple] = {}

        # 注册四条核心规则
        self.register(PriceLimitRule)
        self.register(T1SettlementRule)
        self.register(StampDutyRule)
        self.register(RelatedPartyRule)

    def register(self, rule_cls) -> None:
        """
        注册一条确定性规则

        参数：
            rule_cls: 规则类（必须有 RULE_ID 和 check 方法）
        """
        self._rules[rule_cls.RULE_ID] = (rule_cls, True)
        print(f"✅ 确定性规则已注册：{rule_cls.RULE_ID} {rule_cls.RULE_NAME}")

    def list_rules(self) -> List[Dict]:
        """列出所有已注册的规则"""
        return [
            {
                "rule_id": rid,
                "rule_name": cls.RULE_NAME,
                "legal_source": cls.LEGAL_SOURCE,
                "priority": cls.PRIORITY.value
            }
            for rid, (cls, enabled) in self._rules.items()
            if enabled
        ]

    def check(self, intent: TradeIntent, context: Dict) -> List[DeterministicRuleResult]:
        """
        执行所有确定性规则检查

        参数：
            intent: 交易意图
            context: 上下文信息（包含价格、持仓、关联方等）

        返回：
            每条规则的检查结果列表
        """
        results = []

        for rule_id, (rule_cls, enabled) in self._rules.items():
            if not enabled:
                continue

            try:
                result = rule_cls.check(intent, context)
                results.append(result)
            except Exception as e:
                # 规则执行异常时生成错误结果
                results.append(DeterministicRuleResult(
                    rule_name=rule_cls.RULE_NAME,
                    rule_id=rule_id,
                    passed=False,
                    detail=f"规则执行异常：{str(e)[:100]}",
                    legal_source=rule_cls.LEGAL_SOURCE,
                    priority=rule_cls.PRIORITY,
                    evidence={"error": str(e)[:100]}
                ))

        return results

    def check_and_summarize(self, intent: TradeIntent, context: Dict) -> Dict:
        """
        执行检查并生成摘要

        返回：
            包含 results、passed、blocked_rules、audit_log 的字典
        """
        results = self.check(intent, context)

        blocked = [r for r in results if not r.passed]
        audit_lines = []

        for r in results:
            audit_lines.append(r.to_audit_log())

        return {
            "results": results,
            "total": len(results),
            "passed_count": len(results) - len(blocked),
            "blocked_count": len(blocked),
            "all_passed": len(blocked) == 0,
            "blocked_rules": [r.rule_name for r in blocked],
            "audit_log": "\n".join(audit_lines)
        }


# ============================================
# 第 4 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 确定性规则引擎测试")
    print("=" * 60)

    # 创建规则引擎
    print("\n注册规则：")
    engine = DeterministicRuleEngine()

    print(f"\n已注册 {len(engine.list_rules())} 条规则：")
    for rule_info in engine.list_rules():
        print(f"  📋 {rule_info['rule_id']}: {rule_info['rule_name']}")
        print(f"     依据：{rule_info['legal_source'][:50]}...")

    # 导入交易意图构建器
    from trade_intent import TradeIntentBuilder

    # ============================================
    # 测试 1：正常交易（应全部通过）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 1：正常买入交易（应全部通过）")
    print("=" * 60)

    intent_1 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(100, 1500.0)
                .with_reason("正常测试")
                .build())

    context_1 = {
        "current_price": 1520.0,       # 当前价格
        "prev_close": 1500.0,           # 昨收
        "board_type": "主板",           # 板块
        "positions": [],                # 持仓（空仓）
        "today": "2026-06-07",
        "available_cash": 500000,
        "is_related": False,            # 非关联交易
        "net_assets": 10000000000       # 净资产（100亿，避免关联交易比例过大）
    }

    summary_1 = engine.check_and_summarize(intent_1, context_1)
    print(f"\n检查结果：{summary_1['passed_count']}/{summary_1['total']} 通过")
    print(f"\n审计日志：\n{summary_1['audit_log']}")

    # ============================================
    # 测试 2：触发涨停（应被拦截）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 2：触发涨停限制（应被拦截）")
    print("=" * 60)

    intent_2 = (TradeIntentBuilder()
                .set_symbol("300750.SZ")
                .set_name("宁德时代")
                .buy(100, 240.0)        # 昨收 200，当前 240 = +20%，创业板涨停
                .with_reason("涨停测试")
                .build())

    context_2 = {
        "current_price": 240.0,
        "prev_close": 200.0,
        "board_type": "创业板",
        "positions": [],
        "today": "2026-06-07",
        "available_cash": 500000,
        "is_related": False,
        "net_assets": 10000000000
    }

    summary_2 = engine.check_and_summarize(intent_2, context_2)
    print(f"\n检查结果：{summary_2['passed_count']}/{summary_2['total']} 通过")
    print(f"拦截规则：{summary_2['blocked_rules']}")

    # ============================================
    # 测试 3：违反 T+1（应被拦截）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 3：违反 T+1 制度（应被拦截）")
    print("=" * 60)

    intent_3 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .sell(200, 1520.0)      # 卖出 200 股
                .with_reason("T+1 测试")
                .build())

    context_3 = {
        "current_price": 1520.0,
        "prev_close": 1500.0,
        "board_type": "主板",
        "positions": [
            {"symbol": "600519.SH", "buy_date": "2026-06-07", "quantity": 150}  # 今日买入 150 股
        ],
        "today": "2026-06-07",
        "available_cash": 500000,
        "is_related": False,
        "net_assets": 10000000000
    }

    summary_3 = engine.check_and_summarize(intent_3, context_3)
    print(f"\n检查结果：{summary_3['passed_count']}/{summary_3['total']} 通过")
    print(f"拦截规则：{summary_3['blocked_rules']}")

    # ============================================
    # 测试 4：关联交易需披露（应警告）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 4：关联交易超限（应警告需披露）")
    print("=" * 60)

    intent_4 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(50000, 1500.0)     # 7500 万
                .with_reason("关联交易测试")
                .build())

    context_4 = {
        "current_price": 1500.0,
        "prev_close": 1490.0,
        "board_type": "主板",
        "positions": [],
        "today": "2026-06-07",
        "available_cash": 100000000,
        "is_related": True,             # 是关联交易
        "net_assets": 5000000000        # 净资产 50 亿，7500 万/50 亿 = 1.5% < 5%，不触发
    }

    summary_4 = engine.check_and_summarize(intent_4, context_4)
    print(f"\n检查结果：{summary_4['passed_count']}/{summary_4['total']} 通过")

    print("\n" + "=" * 60)
    print("✅ 确定性规则引擎测试完成")
    print("=" * 60)