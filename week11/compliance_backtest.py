# ============================================
# 全链路合规回测引擎
# 功能：模拟多日交易，验证完整合规链路的协作能力
# 链路：规则检查 → 知识图谱查询 → 治理裁决 → 凭证签发
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import random
from datetime import datetime, timedelta
from typing import List, Dict
from collections import Counter

# 导入本周所有模块
from deterministic_rules import (
    DeterministicRuleEngine,
    DeterministicRuleResult,
    PriceLimitRule,
    T1SettlementRule,
    StampDutyRule,
    RelatedPartyRule,
    RulePriority
)
from legal_kg import LegalQueryService
from hermes_governor import HermesGovernor, FinalAction
from verifiable_credential import (
    CredentialIssuer,
    CredentialVerifier,
    CredentialStore
)

# 导入交易意图模型（从 week7 复用）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
from trade_intent import TradeIntent, TradeIntentBuilder


# ============================================
# 第 1 步：创建合规回测环境
# ============================================

class ComplianceBacktestEnv:
    """
    合规回测环境

    管理模拟交易数据、持仓记录、交易日推进
    """

    def __init__(self, initial_cash: float = 1_000_000):
        """初始化回测环境"""
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.current_day = 0
        self.positions: List[Dict] = []  # 持仓列表
        self.trade_history: List[Dict] = []  # 交易历史
        self.daily_records: List[Dict] = []  # 每日记录

    def next_day(self):
        """推进到下一个交易日，价格随机波动"""
        self.current_day += 1
        # 更新持仓的当前价格（随机波动 ±2%）
        for pos in self.positions:
            change = random.uniform(-0.02, 0.02)
            pos["current_price"] = round(pos["current_price"] * (1 + change), 2)

        print(f"\n{'=' * 60}")
        print(f"📅 第 {self.current_day} 个交易日")
        print(f"{'=' * 60}")

    def get_context(self, intent: TradeIntent) -> Dict:
        """
        根据交易意图构建上下文信息

        参数：
            intent: 交易意图

        返回：
            上下文字典（包含价格、持仓、关联方等）
        """
        # 查找该标的的持仓
        symbol_positions = [p for p in self.positions if p["symbol"] == intent.symbol]

        # 模拟当前价格和昨收价
        base_price = intent.price if intent.price > 0 else 100.0
        prev_close = base_price * random.uniform(0.95, 1.05)

        # 模拟板块类型
        board_types = ["主板", "创业板", "科创板", "主板"]
        board_type = random.choice(board_types)

        # 模拟是否关联交易（10% 概率）
        is_related = random.random() < 0.1

        return {
            "current_price": base_price,
            "prev_close": prev_close,
            "board_type": board_type,
            "positions": self.positions,
            "today": datetime.now().strftime("%Y-%m-%d"),
            "available_cash": self.cash,
            "is_related": is_related,
            "net_assets": 10_000_000_000  # 100亿净资产（模拟）
        }

    def execute_trade(self, intent: TradeIntent) -> Dict:
        """
        模拟执行交易

        参数：
            intent: 交易意图

        返回：
            执行结果字典
        """
        if intent.direction.value == "买入":
            cost = intent.total_amount
            if cost > self.cash:
                return {"success": False, "message": f"资金不足：需要 {cost:,.2f}"}

            self.cash -= cost
            # 更新持仓
            existing = [p for p in self.positions if p["symbol"] == intent.symbol]
            if existing:
                existing[0]["quantity"] += intent.quantity
            else:
                self.positions.append({
                    "symbol": intent.symbol,
                    "name": intent.name,
                    "quantity": intent.quantity,
                    "avg_cost": intent.price,
                    "current_price": intent.price,
                    "buy_date": datetime.now().strftime("%Y-%m-%d")
                })

            self.trade_history.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "买入",
                "symbol": intent.symbol,
                "name": intent.name,
                "quantity": intent.quantity,
                "price": intent.price,
                "amount": cost
            })

            return {"success": True, "message": f"买入 {intent.name} {intent.quantity} 股"}

        elif intent.direction.value == "卖出":
            existing = [p for p in self.positions if p["symbol"] == intent.symbol]
            if not existing or existing[0]["quantity"] < intent.quantity:
                return {"success": False, "message": "持仓不足"}

            revenue = intent.total_amount
            self.cash += revenue
            existing[0]["quantity"] -= intent.quantity

            self.trade_history.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "卖出",
                "symbol": intent.symbol,
                "name": intent.name,
                "quantity": intent.quantity,
                "price": intent.price,
                "amount": revenue
            })

            return {"success": True, "message": f"卖出 {intent.name} {intent.quantity} 股"}

        return {"success": False, "message": "未知操作"}

    def get_summary(self) -> Dict:
        """获取账户摘要"""
        total_assets = self.cash
        for pos in self.positions:
            total_assets += pos["quantity"] * pos["current_price"]

        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_assets": total_assets,
            "total_profit": total_assets - self.initial_cash,
            "position_count": len(self.positions),
            "trade_count": len(self.trade_history)
        }


# ============================================
# 第 2 步：随机交易意图生成器
# ============================================

def generate_random_intent(day: int) -> TradeIntent:
    """
    生成随机交易意图（用于回测）

    参数：
        day: 当前交易日

    返回：
        随机生成的 TradeIntent
    """
    # 股票池
    stocks = [
        ("600519.SH", "贵州茅台", 1500.0),
        ("000858.SZ", "五粮液", 120.0),
        ("300750.SZ", "宁德时代", 180.0),
        ("601318.SH", "中国平安", 45.0),
        ("600036.SH", "招商银行", 38.0),
        ("002415.SZ", "海康威视", 32.0),
    ]

    symbol, name, base_price = random.choice(stocks)
    price = base_price * random.uniform(0.85, 1.15)  # 价格波动 ±15%（可能触发涨跌停）

    # 随机方向
    direction = "buy" if random.random() < 0.6 else "sell"
    quantity = random.randint(100, 10000)

    # 30% 概率生成高风险交易（大额/低置信度/关联交易）
    is_risky = random.random() < 0.3

    if direction == "buy":
        intent = (TradeIntentBuilder()
                  .set_symbol(symbol)
                  .set_name(name)
                  .buy(quantity, price)
                  .with_reason(f"回测交易 Day{day} {'高风险' if is_risky else '正常'}")
                  .build())
    else:
        intent = (TradeIntentBuilder()
                  .set_symbol(symbol)
                  .set_name(name)
                  .sell(quantity, price)
                  .with_reason(f"回测交易 Day{day} {'高风险' if is_risky else '正常'}")
                  .build())

    if is_risky:
        intent.confidence = random.uniform(0.2, 0.5)

    return intent


# ============================================
# 第 3 步：全链路合规审查函数
# ============================================

def full_compliance_check(
    intent: TradeIntent,
    rule_engine: DeterministicRuleEngine,
    legal_service: LegalQueryService,
    governor: HermesGovernor,
    issuer: CredentialIssuer,
    verifier: CredentialVerifier,
    store: CredentialStore
) -> Dict:
    """
    对单笔交易执行完整的合规审查链路

    链路：
    1. 确定性规则引擎检查
    2. 法规知识图谱查询（对拦截的规则）
    3. Hermes 治理层裁决
    4. 可验证凭证签发

    参数：
        intent: 交易意图
        rule_engine: 确定性规则引擎
        legal_service: 法规查询服务
        governor: Hermes 治理引擎
        issuer: 凭证签发器
        verifier: 凭证验证器
        store: 凭证存储

    返回：
        完整的审查结果字典
    """
    # 第一步：规则引擎检查
    rule_results = rule_engine.check(intent, {})  # 先不传 context，后续补充

    # 对拦截的规则查询知识图谱
    legal_info = []
    for r in rule_results:
        if not r.passed:
            info = legal_service.check_compliance(r.rule_name, f"{intent.name} {intent.direction.value}")
            legal_info.append(info)

    # 第二步：Hermes 治理层裁决
    llm_opinion = f"建议{'买入' if intent.direction.value == '买入' else '卖出'} {intent.name} {intent.quantity} 股"
    decision, audit_report = governor.resolve_with_audit(
        rule_results,
        llm_opinion=llm_opinion,
        intent_summary=f"{intent.direction.value} {intent.name} {intent.quantity} 股"
    )

    # 第三步：签发凭证
    credential = issuer.issue(decision)
    store.save(credential)

    # 第四步：验证凭证
    verify_result = verifier.verify(credential)

    return {
        "intent": intent.to_dict(),
        "rule_results": [r.to_dict() for r in rule_results],
        "legal_info": legal_info,
        "governance_decision": decision.to_dict(),
        "credential_verified": verify_result["valid"],
        "final_action": decision.final_action
    }


# ============================================
# 第 4 步：多日合规回测主函数
# ============================================

def run_compliance_backtest(days: int = 5, trades_per_day: int = 3) -> Dict:
    """
    运行多日合规回测

    参数：
        days: 回测天数
        trades_per_day: 每天交易数

    返回：
        回测统计结果
    """
    print("=" * 60)
    print("🔍 全链路合规回测启动")
    print("=" * 60)
    print(f"回测天数：{days} 天")
    print(f"每日交易：{trades_per_day} 笔")
    print(f"总交易数：{days * trades_per_day} 笔")
    print()

    # 初始化所有模块
    print("初始化模块...")
    env = ComplianceBacktestEnv(initial_cash=1_000_000)
    rule_engine = DeterministicRuleEngine()
    legal_service = LegalQueryService()
    governor = HermesGovernor()
    issuer = CredentialIssuer()
    verifier = CredentialVerifier()
    store = CredentialStore()

    # 统计变量
    total = 0
    approved = 0
    blocked = 0
    escalated = 0
    rule_trigger_counts = Counter()
    all_results = []

    # 逐日回测
    for day in range(1, days + 1):
        env.next_day()

        for t in range(1, trades_per_day + 1):
            total += 1
            print(f"\n{'─' * 40}")
            print(f"Day{day}-Trade{t}: 生成交易意图...")

            # 生成交易意图
            intent = generate_random_intent(day)
            print(f"  标的：{intent.name}({intent.symbol})")
            print(f"  方向：{intent.direction.value}")
            print(f"  数量：{intent.quantity} | 价格：{intent.price:.2f}")
            print(f"  总金额：{intent.total_amount:,.2f}")

            # 获取上下文并重新执行规则检查
            context = env.get_context(intent)
            rule_results = rule_engine.check(intent, context)

            # 执行全链路合规审查
            result = full_compliance_check(
                intent, rule_engine, legal_service,
                governor, issuer, verifier, store
            )
            all_results.append(result)

            # 统计
            action = result["final_action"]
            if action == FinalAction.APPROVE:
                approved += 1
                # 执行交易
                exec_result = env.execute_trade(intent)
                print(f"  决策：✅ 批准 → {exec_result.get('message', '')}")
            elif action == FinalAction.BLOCK:
                blocked += 1
                print(f"  决策：🚫 拦截")
            elif action == FinalAction.ESCALATE:
                escalated += 1
                print(f"  决策：⚠️ 上报审批")

            # 统计规则触发
            for r in rule_results:
                if not r.passed:
                    rule_trigger_counts[r.rule_name] += 1

            # 简要打印拦截的规则
            blocked_rules = [r for r in rule_results if not r.passed]
            if blocked_rules:
                for r in blocked_rules:
                    print(f"    触发：{r.rule_name}（优先级 {r.priority.value}）")

    # 构建统计报告
    stats = {
        "total_trades": total,
        "approved": approved,
        "blocked": blocked,
        "escalated": escalated,
        "approval_rate": f"{approved / total * 100:.1f}%",
        "block_rate": f"{blocked / total * 100:.1f}%",
        "escalation_rate": f"{escalated / total * 100:.1f}%",
        "rule_triggers": dict(rule_trigger_counts.most_common()),
        "account_summary": env.get_summary(),
        "credentials_issued": len(store.list_all()),
        "total_trades_executed": len(env.trade_history)
    }

    return stats, all_results, env, store


# ============================================
# 第 5 步：生成合规回测报告
# ============================================

def generate_compliance_report(stats: Dict, all_results: List[Dict]) -> str:
    """
    生成合规回测的 Markdown 报告

    参数：
        stats: 统计数据
        all_results: 所有审查结果

    返回：
        Markdown 报告文本
    """
    lines = []
    lines.append("# 🔍 全链路合规回测报告")
    lines.append("")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**回测模块**：确定性规则引擎 + 法规知识图谱 + Hermes 治理层 + 可验证凭证")
    lines.append("")

    # 总体统计
    lines.append("## 一、总体统计")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 总交易数 | {stats['total_trades']} |")
    lines.append(f"| 批准执行 | {stats['approved']}（{stats['approval_rate']}）|")
    lines.append(f"| 拦截禁止 | {stats['blocked']}（{stats['block_rate']}）|")
    lines.append(f"| 上报审批 | {stats['escalated']}（{stats['escalation_rate']}）|")
    lines.append(f"| 签发凭证 | {stats['credentials_issued']} |")
    lines.append(f"| 实际执行 | {stats['total_trades_executed']} |")
    lines.append("")

    # 规则触发统计
    lines.append("## 二、规则触发统计")
    lines.append("")
    if stats["rule_triggers"]:
        lines.append("| 规则名称 | 触发次数 |")
        lines.append("|----------|----------|")
        for rule_name, count in stats["rule_triggers"].items():
            lines.append(f"| {rule_name} | {count} |")
    else:
        lines.append("*所有交易均未触发规则拦截*")
    lines.append("")

    # 账户摘要
    summary = stats["account_summary"]
    lines.append("## 三、账户摘要")
    lines.append("")
    lines.append(f"- 初始资金：{summary['initial_cash']:,.2f}")
    lines.append(f"- 当前现金：{summary['cash']:,.2f}")
    lines.append(f"- 总资产：{summary['total_assets']:,.2f}")
    lines.append(f"- 持仓数：{summary['position_count']}")
    lines.append("")

    # 拦截详情
    blocked_results = [r for r in all_results if r["final_action"] == FinalAction.BLOCK]
    if blocked_results:
        lines.append("## 四、拦截交易详情")
        lines.append("")
        for i, r in enumerate(blocked_results[:10], 1):  # 最多显示 10 条
            intent = r["intent"]
            lines.append(f"### {i}. {intent.get('direction', '')} {intent.get('name', '')}({intent.get('symbol', '')})")
            lines.append(f"- 数量：{intent.get('quantity', 0)} | 总金额：{intent.get('total_amount', 0):,.2f}")
            lines.append(f"- 决策 ID：{r['governance_decision'].get('decision_id', '')}")
            lines.append(f"- 溯源码：`{r['governance_decision'].get('trace_id', '')}`")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 CUFEI-Q 主投资智能体 · 合规审查模块自动生成*")

    return "\n".join(lines)


# ============================================
# 第 6 步：主程序
# ============================================

if __name__ == "__main__":
    # 运行 5 天回测，每天 3 笔交易
    stats, all_results, env, store = run_compliance_backtest(days=5, trades_per_day=3)

    # 打印统计摘要
    print("\n" + "=" * 60)
    print("📊 合规回测统计")
    print("=" * 60)
    print(f"总交易：{stats['total_trades']}")
    print(f"批准：{stats['approved']}（{stats['approval_rate']}）")
    print(f"拦截：{stats['blocked']}（{stats['block_rate']}）")
    print(f"上报：{stats['escalated']}（{stats['escalation_rate']}）")
    print(f"凭证：{stats['credentials_issued']} 个")
    print(f"执行：{stats['total_trades_executed']} 笔")

    if stats["rule_triggers"]:
        print(f"\n规则触发：")
        for rule, count in stats["rule_triggers"].items():
            print(f"  {rule}: {count} 次")

    # 打印账户摘要
    print(f"\n账户摘要：")
    s = stats["account_summary"]
    print(f"  总资产：{s['total_assets']:,.2f}")
    print(f"  收益：{s['total_profit']:+,.2f}")

    # 生成并保存报告
    report = generate_compliance_report(stats, all_results)

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    report_file = os.path.join(data_dir, f"compliance_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    # 导出所有凭证
    cred_file = os.path.join(data_dir, f"credentials_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    store.export_all(cred_file)

    print(f"\n✅ 合规回测报告：{report_file}")
    print(f"✅ 凭证导出：{cred_file}")
    print("\n" + "=" * 60)
    print("✅ 全链路合规回测完成")
    print("=" * 60)