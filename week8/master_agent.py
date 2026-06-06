# ============================================
# CUFEI-Q 主投资智能体（框架版）
# 整合前七周所有模块的 LangGraph 图
# 今天先搭建框架，周二到周四逐步填充节点逻辑
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, END
from master_state import MasterState
from etf_env import ETFSimEnv

# ============================================
# 节点函数（今天先用占位实现，后续填充）
# ============================================

def signal_aggregation_node(state: MasterState) -> MasterState:
    """节点1：信号汇总——收集 RAG/新闻/因子/辩论 的所有信号"""
    print("\n📡 [节点1] 信号汇总...")
    state["rag_signals"] = "RAG 信号：白酒板块估值合理，有上行空间（占位，周三接入真实数据）"
    state["news_signals"] = "新闻信号：新能源板块政策利好，短期看多（占位）"
    state["factor_signals"] = "因子信号：低PE因子表现优异，建议关注价值股（占位）"
    state["debate_result"] = "辩论结论：多头胜出，市场整体偏乐观（占位）"
    state["execution_log"].append("✅ 信号汇总完成")
    print("   ✅ 信号汇总完成（占位数据）")
    return state

def decision_node(state: MasterState) -> MasterState:
    """节点2：决策生成——LLM 综合所有信号生成交易计划"""
    print("\n🧠 [节点2] 决策生成...")
    state["trade_plan"] = "交易计划：买入酒ETF 5000 股，买入新能源ETF 3000 股（占位，周三接入 LLM）"
    state["execution_log"].append("✅ 交易计划生成完成")
    print("   ✅ 交易计划生成完成（占位数据）")
    return state

def risk_check_node(state: MasterState) -> MasterState:
    """节点3：风控审批——检查交易计划是否合规"""
    print("\n🛡️ [节点3] 风控审批...")
    state["risk_passed"] = True
    state["risk_message"] = "风控检查通过（占位，周三接入真实风控）"
    state["execution_log"].append("✅ 风控审批通过")
    print("   ✅ 风控审批通过（占位）")
    return state

def execute_node(state: MasterState) -> MasterState:
    """节点4：执行交易——在模拟环境中执行交易"""
    print("\n💹 [节点4] 执行交易...")
    env = state.get("env")
    if env:
        r = env.buy("512690", 5000)
        state["execution_results"].append(r)
        r2 = env.buy("516160", 3000)
        state["execution_results"].append(r2)
    state["execution_log"].append("✅ 交易执行完成")
    print("   ✅ 交易执行完成")
    return state

def summary_node(state: MasterState) -> MasterState:
    """节点5：生成摘要"""
    print("\n📄 [节点5] 生成摘要...")
    env = state.get("env")
    if env:
        s = env.get_summary()
        state["final_summary"] = f"总资产：{s['total_assets']:,.2f}，收益：{s['total_profit']:,.2f}"
    state["execution_log"].append("✅ 摘要生成完成")
    print(f"   ✅ 摘要：{state['final_summary']}")
    return state

# ============================================
# 条件路由
# ============================================

def risk_router(state: MasterState) -> str:
    """风控路由：通过→执行，拦截→跳过执行直接摘要"""
    if state.get("risk_passed", False):
        return "execute"
    else:
        return "summary"

# ============================================
# 构建主智能体图
# ============================================

def build_master_graph() -> StateGraph:
    """构建 CUFEI-Q 主智能体的 LangGraph 图"""
    workflow = StateGraph(MasterState)

    # 添加节点
    workflow.add_node("signal_aggregation", signal_aggregation_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("risk_check", risk_check_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("summary", summary_node)

    # 设置入口
    workflow.set_entry_point("signal_aggregation")

    # 添加边
    workflow.add_edge("signal_aggregation", "decision")
    workflow.add_edge("decision", "risk_check")

    # 条件路由
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
    print("=" * 60)
    print("🤖 CUFEI-Q 主投资智能体（框架测试）")
    print("=" * 60)
    print("\n图结构：")
    print("  signal_aggregation → decision → risk_check → [条件] → execute → summary → END")
    print()

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
        "risk_passed": False,
        "risk_message": "",
        "execution_results": [],
        "alert_sent": False,
        "final_summary": "",
        "execution_log": []
    }

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("📝 执行日志：")
    for log in final_state["execution_log"]:
        print(f"   {log}")

    env.print_summary()

    print("\n" + "=" * 60)
    print("✅ 主智能体框架测试完成")
    print("=" * 60)