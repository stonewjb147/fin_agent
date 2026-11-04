# ============================================
# CUFEI-Q 主投资智能体（完整版 v2.0）
# 整合前10练所有模块 + 第11练合规审查
#
# 完整链路（6个节点）：
#   signal_aggregation → decision → risk_check
#   → compliance_check → execute → summary
#
# 第11练插入位置：risk_check 和 execute 之间
# 作用：确保每笔交易都经过法律合规审查
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime
from langgraph.graph import StateGraph, END
from master_state import MasterState
from etf_env import ETFSimEnv

# ============================================
# 导入前10练各模块
# ============================================

# 第4练：信号汇总
from signal_aggregator import aggregate_all_signals

# 第5练：决策生成
from decision_maker import generate_trade_plan, plan_to_intents

# 第7练：风控模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
from risk_models import RiskEngine
from risk_rules import (
    SingleTradeLimitRule,
    TotalExposureRule,
    ConcentrationRiskRule,
    ConfidenceThresholdRule,
    DailyTradeFrequencyRule
)

# ============================================
# 导入第11练合规审查模块
# ============================================
from deterministic_rules import DeterministicRuleEngine
from legal_kg import LegalQueryService
from hermes_governor import HermesGovernor, FinalAction
from verifiable_credential import CredentialIssuer, CredentialVerifier, CredentialStore


# ============================================
# 第 1 步：创建风控引擎（第7练）
# ============================================

def create_risk_engine() -> RiskEngine:
    """创建风控引擎，注册5道防线"""
    engine = RiskEngine()
    engine.add_rule(SingleTradeLimitRule(max_amount=200000))
    engine.add_rule(ConfidenceThresholdRule(min_confidence=0.5))
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=10))
    engine.add_rule(TotalExposureRule(max_exposure_pct=0.8))
    engine.add_rule(ConcentrationRiskRule(max_single_pct=0.4))
    return engine

risk_engine = create_risk_engine()


# ============================================
# 第 2 步：创建合规引擎（第11练）
# ============================================

compliance_engine = DeterministicRuleEngine()
legal_service = LegalQueryService()
governor = HermesGovernor()
cred_issuer = CredentialIssuer()
cred_verifier = CredentialVerifier()
cred_store = CredentialStore()


# ============================================
# 第 3 步：定义6个节点函数
# ============================================

def signal_aggregation_node(state: MasterState) -> MasterState:
    """
    节点1：信号汇总
    收集四路信号：RAG研报、新闻信号、因子信号、辩论结论
    """
    print("\n📡 [节点1] 信号汇总...")
    query = state.get("user_query", "当前市场投资机会")
    signals = aggregate_all_signals(query)
    state["rag_signals"] = signals["rag"]
    state["news_signals"] = signals["news"]
    state["factor_signals"] = signals["factor"]
    state["debate_result"] = signals["debate"]
    state["execution_log"].append("✅ 四路信号汇总完成")
    print("   ✅ 四路信号汇总完成")
    return state


def decision_node(state: MasterState) -> MasterState:
    """
    节点2：决策生成
    LLM综合分析四路信号，生成具体交易计划
    """
    print("\n🧠 [节点2] 决策生成...")

    env = state.get("env")
    if env:
        summary = env.get_summary()
        available_cash = env.cash
        total_assets = summary["total_assets"]
        positions = env.get_positions()
        if positions:
            pos_lines = []
            for p in positions:
                pos_lines.append(
                    f"{p.name}({p.symbol})：{p.quantity}股，"
                    f"成本{p.avg_cost:.2f}，现价{p.current_price:.2f}"
                )
            positions_text = "\n".join(pos_lines)
        else:
            positions_text = "空仓"
    else:
        available_cash = 500000
        total_assets = 500000
        positions_text = "空仓"

    plan = generate_trade_plan(
        rag_signals=state["rag_signals"],
        news_signals=state["news_signals"],
        factor_signals=state["factor_signals"],
        debate_result=state["debate_result"],
        current_positions=positions_text,
        available_cash=available_cash,
        total_assets=total_assets
    )

    state["trade_plan"] = json.dumps(plan, ensure_ascii=False, indent=2)
    intents = plan_to_intents(plan)
    state["execution_log"].append(f"✅ 生成 {len(intents)} 个交易意图")
    state["trade_intents"] = [i.to_dict() for i in intents]
    print(f"   ✅ 生成 {len(intents)} 个交易意图")
    return state


def risk_check_node(state: MasterState) -> MasterState:
    """
    节点3：风控审批（第7练）
    软约束检查：仓位、集中度、置信度
    """
    print("\n🛡️ [节点3] 风控审批...")

    intents_dicts = state.get("trade_intents", [])
    if not intents_dicts:
        state["risk_passed"] = True
        state["risk_message"] = "无交易意图，跳过风控"
        state["execution_log"].append("✅ 无交易意图，跳过风控")
        return state

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
    from trade_intent import TradeIntent

    intents = []
    for d in intents_dicts:
        intent = TradeIntent(
            symbol=d.get("symbol", ""),
            name=d.get("name", ""),
            quantity=d.get("quantity", 0),
            price=d.get("price", 0),
            confidence=d.get("confidence", 0.5),
            reason=d.get("reason", "")
        )
        intents.append(intent)

    env = state.get("env")
    if env:
        summary = env.get_summary()
        context = {
            "total_assets": summary["total_assets"],
            "current_holdings": summary["total_assets"] - env.cash,
            "symbol_holdings": {p.symbol: p.market_value for p in env.get_positions()},
            "daily_trade_count": len(env.trade_history)
        }
    else:
        context = {
            "total_assets": 500000,
            "current_holdings": 0,
            "symbol_holdings": {},
            "daily_trade_count": 0
        }

    all_passed = True
    for intent in intents:
        result = risk_engine.check(intent, context)
        if not result.passed:
            all_passed = False
            state["execution_log"].append(f"❌ {intent.symbol} 风控拦截：{result.summary}")
        else:
            state["execution_log"].append(f"✅ {intent.symbol} 风控通过")

    state["risk_passed"] = all_passed
    state["risk_message"] = "全部通过" if all_passed else "存在拦截"
    print(f"   {'✅ 全部通过' if all_passed else '❌ 存在拦截'}")
    return state


def compliance_node(state: MasterState) -> MasterState:
    """
    节点4：合规审查（第11练——新增）
    
    硬约束检查：涨跌停、T+1、印花税、关联交易
    每条拦截都有法律条文引用和可验证凭证
    """
    print("\n🔍 [节点4] 合规审查（第11练）...")

    intents_dicts = state.get("trade_intents", [])
    if not intents_dicts:
        state["execution_log"].append("✅ 无交易意图，跳过合规审查")
        state["compliance_blocked"] = 0
        state["compliance_credentials"] = 0
        return state

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
    from trade_intent import TradeIntent

    env = state.get("env")
    passed_intents = []
    blocked_count = 0

    for d in intents_dicts:
        # 重建 TradeIntent 对象
        intent = TradeIntent(
            symbol=d.get("symbol", ""),
            name=d.get("name", ""),
            quantity=d.get("quantity", 0),
            price=d.get("price", 0),
            confidence=d.get("confidence", 0.5),
            reason=d.get("reason", "")
        )

        # 构建合规审查上下文
        context = {
            "current_price": d.get("price", 0),
            "prev_close": d.get("price", 0) * random_uniform(0.95, 1.05),
            "board_type": "主板",
            "positions": [],
            "today": datetime.now().strftime("%Y-%m-%d"),
            "available_cash": env.cash if env else 500000,
            "is_related": False,
            "net_assets": 10_000_000_000
        }

        # === 第11练核心链路 ===
        
        # 步骤1：确定性规则引擎检查
        rule_results = compliance_engine.check(intent, context)

        # 步骤2：对拦截的规则查询知识图谱
        for r in rule_results:
            if not r.passed:
                legal_info = legal_service.check_compliance(
                    r.rule_name,
                    f"{intent.name} {intent.direction.value}"
                )

        # 步骤3：Hermes 治理层裁决
        llm_opinion = f"建议{d.get('direction', '买入')} {d.get('name', '')} {d.get('quantity', 0)}股"
        decision, _ = governor.resolve_with_audit(
            rule_results,
            llm_opinion=llm_opinion,
            intent_summary=f"{d.get('direction', '')} {d.get('name', '')} {d.get('quantity', 0)}股"
        )

        # 步骤4：签发可验证凭证
        credential = cred_issuer.issue(decision)
        cred_store.save(credential)

        # 步骤5：验证凭证
        verify_result = cred_verifier.verify(credential)

        # 根据裁决结果决定是否放行
        if decision.final_action == FinalAction.BLOCK:
            blocked_count += 1
            state["execution_log"].append(
                f"🚫 {d.get('name', '')} 合规拦截 | "
                f"溯源码：{decision.trace_id} | "
                f"拦截规则：{[r.rule_name for r in rule_results if not r.passed]}"
            )
        else:
            passed_intents.append(d)
            state["execution_log"].append(
                f"✅ {d.get('name', '')} 合规通过 | "
                f"溯源码：{decision.trace_id} | "
                f"凭证验证：{'通过' if verify_result['valid'] else '失败'}"
            )

    # 更新状态：移除被合规拦截的交易意图
    state["trade_intents"] = passed_intents
    state["compliance_blocked"] = blocked_count
    state["compliance_credentials"] = len(cred_store.list_all())

    print(f"   ✅ 合规审查完成：{len(passed_intents)} 通过，{blocked_count} 拦截")
    return state


def execute_node(state: MasterState) -> MasterState:
    """
    节点5：执行交易
    只执行通过风控和合规审查的交易
    """
    print("\n💹 [节点5] 执行交易...")

    intents_dicts = state.get("trade_intents", [])
    env = state.get("env")

    if not env or not intents_dicts:
        state["execution_log"].append("⚠️ 无交易可执行（可能被风控或合规拦截）")
        return state

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
    from trade_intent import TradeIntent

    for d in intents_dicts:
        direction = d.get("direction", "")
        if direction == "买入":
            result = env.buy(d["symbol"], d["quantity"])
        elif direction == "卖出":
            result = env.sell(d["symbol"], d["quantity"])
        else:
            result = {"success": False, "message": f"未知方向：{direction}"}

        state["execution_results"].append(result)
        icon = "✅" if result.get("success") else "❌"
        state["execution_log"].append(f"{icon} {result.get('message', '')}")
        print(f"   {icon} {result.get('message', '')[:80]}")

    state["execution_log"].append("✅ 交易执行完成")
    return state


def summary_node(state: MasterState) -> MasterState:
    """
    节点6：生成摘要
    """
    print("\n📄 [节点6] 生成摘要...")

    env = state.get("env")
    if env:
        s = env.get_summary()
        profit_icon = "🔴" if s["total_profit"] > 0 else "🟢"
        state["final_summary"] = (
            f"初始资金：{s['initial_cash']:,.2f}\n"
            f"总资产：{s['total_assets']:,.2f}\n"
            f"收益：{profit_icon} {s['total_profit']:,.2f}（{s['total_profit_pct']:.2f}%）\n"
            f"持仓数：{s['position_count']} | 交易数：{s['trade_count']}\n"
            f"合规拦截：{state.get('compliance_blocked', 0)} 笔 | "
            f"签发凭证：{state.get('compliance_credentials', 0)} 个"
        )

    state["execution_log"].append("✅ 摘要生成完成")
    print(f"   {state['final_summary'][:120]}...")
    return state


# ============================================
# 第 4 步：辅助函数
# ============================================

def random_uniform(a, b):
    """简单的随机数生成（避免额外导入）"""
    import random
    return random.uniform(a, b)


# ============================================
# 第 5 步：条件路由
# ============================================

def risk_router(state: MasterState) -> str:
    """风控路由：通过→合规审查，拦截→跳过执行"""
    if state.get("risk_passed", False):
        return "compliance"
    else:
        return "summary"


# ============================================
# 第 6 步：构建主智能体图
# ============================================

def build_master_graph() -> StateGraph:
    """
    构建完整的主智能体 LangGraph 图（6个节点）
    
    链路：
    signal_aggregation → decision → risk_check
    → compliance → execute → summary
    """
    workflow = StateGraph(MasterState)

    # 注册6个节点
    workflow.add_node("signal_aggregation", signal_aggregation_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("risk_check", risk_check_node)
    workflow.add_node("compliance", compliance_node)      # 第11练新增
    workflow.add_node("execute", execute_node)
    workflow.add_node("summary", summary_node)

    # 设置入口
    workflow.set_entry_point("signal_aggregation")

    # 添加边
    workflow.add_edge("signal_aggregation", "decision")
    workflow.add_edge("decision", "risk_check")

    # 风控 → 合规（通过）或 摘要（拦截）
    workflow.add_conditional_edges(
        "risk_check",
        risk_router,
        {"compliance": "compliance", "summary": "summary"}
    )

    # 合规 → 执行 → 摘要
    workflow.add_edge("compliance", "execute")
    workflow.add_edge("execute", "summary")
    workflow.add_edge("summary", END)

    return workflow.compile()


# ============================================
# 第 7 步：便捷执行函数
# ============================================

def run_master_agent(user_query: str = "分析当前市场并给出 ETF 交易建议",
                     initial_cash: float = 500000):
    """
    一键运行主智能体

    参数：
        user_query: 用户指令
        initial_cash: 初始资金

    返回：
        最终状态字典
    """
    print("=" * 60)
    print("🤖 CUFEI-Q 主投资智能体 v2.0")
    print("   整合前10练 + 第11练合规审查")
    print("=" * 60)
    print(f"用户指令：{user_query}")
    print(f"初始资金：{initial_cash:,.2f}")
    print()

    env = ETFSimEnv(initial_cash=initial_cash)
    app = build_master_graph()

    initial_state = {
        "user_query": user_query,
        "env": env,
        "rag_signals": "",
        "news_signals": "",
        "factor_signals": "",
        "debate_result": "",
        "trade_plan": "",
        "trade_intents": [],
        "risk_passed": False,
        "risk_message": "",
        "execution_results": [],
        "alert_sent": False,
        "final_summary": "",
        "execution_log": [],
        "compliance_blocked": 0,
        "compliance_credentials": 0
    }

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("📝 执行日志：")
    for log in final_state["execution_log"]:
        print(f"   {log}")

    print("\n" + "=" * 60)
    print("📊 最终摘要：")
    print(final_state["final_summary"])

    print("\n" + "=" * 60)
    env.print_summary()

    return final_state


# ============================================
# 第 8 步：主程序入口
# ============================================

if __name__ == "__main__":
    run_master_agent(
        user_query="分析当前市场并给出 ETF 交易建议",
        initial_cash=500000
    )