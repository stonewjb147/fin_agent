# ============================================
# CUFEI-Q 主投资智能体（完整版）
# 整合：信号汇总 → 决策生成 → 风控审批 → 执行 → 摘要
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, END
from master_state import MasterState
from etf_env import ETFSimEnv

# 导入信号汇总
from signal_aggregator import aggregate_all_signals

# 导入决策生成
from decision_maker import generate_trade_plan, plan_to_intents

# 导入风控模块
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
# 创建全局风控引擎
# ============================================

def create_risk_engine() -> RiskEngine:
    """创建风控引擎"""
    engine = RiskEngine()
    engine.add_rule(SingleTradeLimitRule(max_amount=200000))       # 单笔最多 20 万
    engine.add_rule(ConfidenceThresholdRule(min_confidence=0.5))   # 置信度 ≥ 50%
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=10))
    engine.add_rule(TotalExposureRule(max_exposure_pct=0.8))
    engine.add_rule(ConcentrationRiskRule(max_single_pct=0.4))
    return engine

risk_engine = create_risk_engine()

# ============================================
# 节点函数
# ============================================

def signal_aggregation_node(state: MasterState) -> MasterState:
    """节点1：信号汇总"""
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
    """节点2：决策生成"""
    print("\n🧠 [节点2] 决策生成...")

    env = state.get("env")
    if env:
        summary = env.get_summary()
        available_cash = env.cash
        total_assets = summary["total_assets"]

        # 构建持仓描述
        positions = env.get_positions()
        if positions:
            pos_lines = []
            for p in positions:
                pos_lines.append(f"{p.name}({p.symbol})：{p.quantity}股，成本{p.avg_cost:.2f}，现价{p.current_price:.2f}")
            positions_text = "\n".join(pos_lines)
        else:
            positions_text = "空仓"
    else:
        available_cash = 500000
        total_assets = 500000
        positions_text = "空仓"

    # 生成交易计划
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

    # 转为 TradeIntent 列表
    intents = plan_to_intents(plan)
    state["execution_log"].append(f"✅ 生成 {len(intents)} 个交易意图")

    # 存储到状态中（序列化）
    state["trade_intents"] = [i.to_dict() for i in intents]

    print(f"   ✅ 生成 {len(intents)} 个交易意图")
    return state


def risk_check_node(state: MasterState) -> MasterState:
    """节点3：风控审批"""
    print("\n🛡️ [节点3] 风控审批...")

    intents_dicts = state.get("trade_intents", [])
    if not intents_dicts:
        state["risk_passed"] = True
        state["risk_message"] = "无交易意图，跳过风控"
        state["execution_log"].append("✅ 无交易意图，跳过风控")
        return state

    # 导入 TradeIntent
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
    from trade_intent import TradeIntent

    # 重建 TradeIntent 对象
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

    # 构建风控上下文
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
        context = {"total_assets": 500000, "current_holdings": 0, "symbol_holdings": {}, "daily_trade_count": 0}

    # 逐笔检查
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


def execute_node(state: MasterState) -> MasterState:
    """节点4：执行交易"""
    print("\n💹 [节点4] 执行交易...")

    intents_dicts = state.get("trade_intents", [])
    env = state.get("env")

    if not env or not intents_dicts:
        state["execution_log"].append("⚠️ 无交易可执行")
        return state

    # 重建 TradeIntent
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
    from trade_intent import TradeIntent

    for d in intents_dicts:
        # 判断买卖方向
        if d.get("direction", "") == "买入" or d.get("direction", "") == "买入":
            result = env.buy(d["symbol"], d["quantity"])
        elif d.get("direction", "") == "卖出":
            result = env.sell(d["symbol"], d["quantity"])
        else:
            result = {"success": False, "message": f"未知方向：{d.get('direction', '')}"}

        state["execution_results"].append(result)
        icon = "✅" if result.get("success") else "❌"
        state["execution_log"].append(f"{icon} {result.get('message', '')}")
        print(f"   {icon} {result.get('message', '')[:80]}")

    state["execution_log"].append(f"✅ 交易执行完成")
    return state


def summary_node(state: MasterState) -> MasterState:
    """节点5：生成摘要"""
    print("\n📄 [节点5] 生成摘要...")

    env = state.get("env")
    if env:
        s = env.get_summary()
        profit_icon = "🔴" if s["total_profit"] > 0 else "🟢"
        state["final_summary"] = (
            f"初始资金：{s['initial_cash']:,.2f}\n"
            f"总资产：{s['total_assets']:,.2f}\n"
            f"收益：{profit_icon} {s['total_profit']:,.2f}（{s['total_profit_pct']:.2f}%）\n"
            f"持仓数：{s['position_count']} | 交易数：{s['trade_count']}"
        )

    state["execution_log"].append("✅ 摘要生成完成")
    print(f"   {state['final_summary'][:100]}...")
    return state


# ============================================
# 条件路由
# ============================================

def risk_router(state: MasterState) -> str:
    """风控路由"""
    if state.get("risk_passed", False):
        return "execute"
    else:
        return "summary"


# ============================================
# 构建主图
# ============================================

def build_master_graph() -> StateGraph:
    """构建主智能体图"""
    workflow = StateGraph(MasterState)

    workflow.add_node("signal_aggregation", signal_aggregation_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("risk_check", risk_check_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("summary", summary_node)

    workflow.set_entry_point("signal_aggregation")
    workflow.add_edge("signal_aggregation", "decision")
    workflow.add_edge("decision", "risk_check")

    workflow.add_conditional_edges(
        "risk_check",
        risk_router,
        {"execute": "execute", "summary": "summary"}
    )

    workflow.add_edge("execute", "summary")
    workflow.add_edge("summary", END)

    return workflow.compile()


# ============================================
# 测试
# ============================================

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("🤖 CUFEI-Q 主投资智能体（完整版）")
    print("=" * 60)

    env = ETFSimEnv(initial_cash=500000)
    app = build_master_graph()

    initial_state = {
        "user_query": "分析当前市场并给出 ETF 交易建议",
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
        "execution_log": []
    }

    print("\n⏳ 开始执行完整决策流程...")
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

    print("\n" + "=" * 60)
    print("✅ 主智能体完整流程测试完成")
    print("=" * 60)