# ============================================
# LangGraph 风控节点
# 功能：将风控引擎封装为 LangGraph 可编排的节点
# 支持"交易意图 → 风控检查 → 放行/拦截"的完整流程
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import TypedDict, Optional, List  # 类型注解

# 导入 LangGraph 核心组件
from langgraph.graph import StateGraph, END  # StateGraph: 状态图, END: 终止节点

# 导入风控相关模块
from risk_models import RiskEngine, RiskCheckResult, RiskLevel
from risk_rules import (
    SingleTradeLimitRule,         # 单笔限额
    TotalExposureRule,             # 总敞口
    ConcentrationRiskRule,         # 集中度
    ConfidenceThresholdRule,       # 置信度
    DailyTradeFrequencyRule        # 日频次
)
from risk_alert import format_alert_message, send_feishu_alert

# 导入交易意图模型
from trade_intent import TradeIntent, TradeIntentBuilder

# ============================================
# 第 1 步：定义 LangGraph 状态
# ============================================

class TradeApprovalState(TypedDict):
    """
    交易审批流程的状态定义
    
    字段说明：
    - trade_intent: 交易意图对象（TradeIntent）
    - context: 上下文信息（持仓、资产等）
    - risk_result: 风控检查结果（RiskEngineResult）
    - passed: 是否通过风控
    - alert_sent: 是否已发送告警
    - alert_message: 告警消息文本
    - final_decision: 最终决策（"执行"/"拦截"/"警告"）
    - execution_log: 执行日志列表
    """
    trade_intent: Optional[TradeIntent]     # 交易意图
    context: dict                           # 上下文信息
    risk_result: Optional[dict]             # 风控结果（序列化为字典）
    passed: bool                            # 是否通过
    alert_sent: bool                        # 是否已告警
    alert_message: str                      # 告警消息
    final_decision: str                     # 最终决策
    execution_log: List[str]                # 执行日志


# ============================================
# 第 2 步：创建全局风控引擎实例
# ============================================

def create_default_risk_engine() -> RiskEngine:
    """
    创建默认配置的风控引擎
    
    注册五道标准防线，阈值可根据需要调整
    
    返回：
        配置好的 RiskEngine 实例
    """
    # 创建引擎
    engine = RiskEngine()
    
    # 注册五道防线
    engine.add_rule(SingleTradeLimitRule(max_amount=500000))        # 单笔不超过 50 万
    engine.add_rule(ConfidenceThresholdRule(min_confidence=0.6))    # 置信度不低于 60%
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=10))   # 每天不超过 10 笔
    engine.add_rule(TotalExposureRule(max_exposure_pct=0.6))        # 总敞口不超过 60%
    engine.add_rule(ConcentrationRiskRule(max_single_pct=0.3))      # 单票不超过 30%
    
    return engine

# 全局单例（避免每次调用都重新创建）
_risk_engine = create_default_risk_engine()


# ============================================
# 第 3 步：定义 LangGraph 节点函数
# ============================================

def validate_intent_node(state: TradeApprovalState) -> TradeApprovalState:
    """
    节点1：验证交易意图是否合法
    
    检查 TradeIntent 的基本字段是否完整。
    如果意图本身无效（如缺少标的代码），直接拦截，
    不需要进入后续的风控检查。
    
    参数：
        state: 当前状态
    
    返回：
        更新后的状态
    """
    print("\n📋 [节点1] 验证交易意图...")
    
    # 从状态中获取交易意图
    intent = state.get("trade_intent")
    
    if intent is None:
        # 没有交易意图——直接拦截
        state["passed"] = False
        state["final_decision"] = "拦截"
        state["alert_message"] = "❌ 未提供有效的交易意图"
        state["execution_log"].append("❌ 交易意图为空，拦截")
        print("   ❌ 交易意图为空")
        return state
    
    # 检查基本有效性
    valid, errors = intent.is_valid()
    
    if not valid:
        # 意图本身无效——直接拦截
        state["passed"] = False
        state["final_decision"] = "拦截"
        error_text = "\n".join(f"  - {e}" for e in errors)
        state["alert_message"] = f"❌ 交易意图无效：\n{error_text}"
        state["execution_log"].append(f"❌ 交易意图无效：{len(errors)} 个字段异常")
        print(f"   ❌ 交易意图无效：{len(errors)} 个字段异常")
        for e in errors:
            print(f"      - {e}")
        return state
    
    # 意图有效
    state["execution_log"].append(f"✅ 交易意图有效：{intent.name}({intent.symbol})")
    print(f"   ✅ 交易意图有效：{intent.name}({intent.symbol})")
    return state


def risk_check_node(state: TradeApprovalState) -> TradeApprovalState:
    """
    节点2：执行风控检查
    
    调用风控引擎对所有规则进行逐一检查。
    检查结果会保存到状态中。
    
    参数：
        state: 当前状态
    
    返回：
        更新后的状态
    """
    print("\n🔍 [节点2] 执行风控检查...")
    
    # 如果前一步已经拦截，跳过风控检查
    if not state.get("passed", True):
        print("   ⏭️ 前序节点已拦截，跳过风控检查")
        return state
    
    # 获取交易意图和上下文
    intent = state.get("trade_intent")
    context = state.get("context", {})
    
    # 执行风控检查
    result = _risk_engine.check(intent, context)
    
    # 将结果存入状态（序列化为字典，方便 LangGraph 传递）
    state["risk_result"] = result.to_dict()
    state["passed"] = result.passed
    
    # 记录日志
    blocked = result.blocked_rules
    warnings = result.warning_rules
    
    if result.passed:
        state["execution_log"].append(f"✅ 风控检查通过（{result.total_rules} 条规则全部通过）")
        print(f"   ✅ 全部通过")
    else:
        state["execution_log"].append(f"❌ 风控拦截：{blocked} 条规则触发拦截，{warnings} 条警告")
        print(f"   ❌ {blocked} 条拦截，{warnings} 条警告")
    
    # 打印每条规则的检查结果
    for r in result.results:
        icon = "✅" if r.passed else "❌"
        print(f"      {icon} {r.rule_name}: {r.message[:80]}")
    
    return state


def alert_node(state: TradeApprovalState) -> TradeApprovalState:
    """
    节点3：发送告警（仅在未通过时执行）
    
    如果风控检查未通过，生成告警消息并通过飞书发送。
    如果风控通过，跳过此节点。
    
    参数：
        state: 当前状态
    
    返回：
        更新后的状态
    """
    print("\n📢 [节点3] 告警处理...")
    
    # 如果风控通过，不需要告警
    if state.get("passed", False):
        state["alert_sent"] = False
        state["execution_log"].append("✅ 风控通过，无需告警")
        print("   ✅ 风控通过，无需告警")
        return state
    
    # 获取交易意图和风控结果
    intent = state.get("trade_intent")
    risk_dict = state.get("risk_result", {})
    
    # 从字典重建风控结果对象（用于格式化消息）
    from risk_models import RiskEngineResult, RiskCheckResult as RCR, RiskLevel as RL
    
    # 重建 RiskCheckResult 列表
    results_list = []
    for r_dict in risk_dict.get("results", []):
        results_list.append(RCR(
            rule_name=r_dict.get("rule_name", ""),
            level=RL(r_dict.get("level", "通过")),
            passed=r_dict.get("passed", True),
            message=r_dict.get("message", ""),
            details=r_dict.get("details", {})
        ))
    
    # 重建 RiskEngineResult
    risk_result = RiskEngineResult(
        intent_id=risk_dict.get("intent_id", ""),
        passed=risk_dict.get("passed", True),
        risk_level=RL(risk_dict.get("risk_level", "通过")),
        total_rules=risk_dict.get("total_rules", 0),
        passed_rules=risk_dict.get("passed_rules", 0),
        blocked_rules=risk_dict.get("blocked_rules", 0),
        warning_rules=risk_dict.get("warning_rules", 0),
        results=results_list,
        summary=risk_dict.get("summary", ""),
        checked_at=risk_dict.get("checked_at", "")
    )
    
    # 格式化告警消息
    alert_msg = format_alert_message(risk_result, intent)
    state["alert_message"] = alert_msg
    
    # 发送飞书告警
    send_feishu_alert(alert_msg)
    state["alert_sent"] = True
    
    state["execution_log"].append(f"🚨 已发送告警")
    
    return state


def decision_node(state: TradeApprovalState) -> TradeApprovalState:
    """
    节点4：做出最终决策
    
    根据风控检查结果，决定是"执行"还是"拦截"。
    
    参数：
        state: 当前状态
    
    返回：
        更新后的状态
    """
    print("\n⚖️ [节点4] 最终决策...")
    
    # 判断是否通过
    passed = state.get("passed", False)
    
    if passed:
        # 风控通过——可以执行
        state["final_decision"] = "执行"
        state["execution_log"].append("✅ 最终决策：执行交易")
        print("   ✅ 最终决策：执行交易")
    else:
        # 风控拦截——禁止执行
        state["final_decision"] = "拦截"
        state["execution_log"].append("❌ 最终决策：拦截交易")
        print("   ❌ 最终决策：拦截交易")
    
    # 打印完整执行日志
    print(f"\n{'─' * 40}")
    print("📝 执行日志：")
    for log in state["execution_log"]:
        print(f"   {log}")
    
    return state


# ============================================
# 第 4 步：条件路由函数
# ============================================

def should_alert(state: TradeApprovalState) -> str:
    """
    条件路由：决定是否需要发送告警
    
    - 如果风控通过 → 直接到决策节点
    - 如果风控未通过 → 先到告警节点，再到决策节点
    
    参数：
        state: 当前状态
    
    返回：
        下一个节点名称
    """
    passed = state.get("passed", False)
    
    if passed:
        # 通过，不需要告警
        return "decision"
    else:
        # 未通过，需要告警
        return "alert"


def should_continue(state: TradeApprovalState) -> str:
    """
    条件路由：验证失败后是否继续
    
    - 如果意图有效 → 继续风控检查
    - 如果意图无效 → 直接到决策节点
    
    参数：
        state: 当前状态
    
    返回：
        下一个节点名称
    """
    passed = state.get("passed", True)
    
    if passed:
        # 意图有效，继续风控
        return "risk_check"
    else:
        # 意图无效，跳过风控直接决策
        return "decision"


# ============================================
# 第 5 步：构建完整的审批图
# ============================================

def build_approval_graph() -> StateGraph:
    """
    构建交易审批的 LangGraph 图
    
    图结构：
    
        [validate_intent]     ← 验证交易意图
              │
              ▼
        [条件判断]            ← 意图有效？
         │        │
      有效      无效
         │        │
         ▼        │
    [risk_check]  │         ← 风控检查（5道规则）
         │        │
         ▼        │
    [条件判断]    │         ← 需要告警？
     │      │     │
   通过   未通过  │
     │      │     │
     │      ▼     │
     │  [alert]   │         ← 飞书告警
     │      │     │
     │      ▼     │
     └──────┴─────┘
              │
              ▼
        [decision]            ← 最终决策
              │
              ▼
             END
    """
    # 创建状态图
    workflow = StateGraph(TradeApprovalState)
    
    # 添加四个节点
    workflow.add_node("validate_intent", validate_intent_node)  # 验证节点
    workflow.add_node("risk_check", risk_check_node)            # 风控节点
    workflow.add_node("alert", alert_node)                      # 告警节点
    workflow.add_node("decision", decision_node)                # 决策节点
    
    # 设置入口
    workflow.set_entry_point("validate_intent")
    
    # 验证节点后的条件路由
    workflow.add_conditional_edges(
        "validate_intent",   # 从验证节点出发
        should_continue,     # 条件判断函数
        {
            "risk_check": "risk_check",   # 有效 → 风控检查
            "decision": "decision"        # 无效 → 直接决策
        }
    )
    
    # 风控节点后的条件路由
    workflow.add_conditional_edges(
        "risk_check",        # 从风控节点出发
        should_alert,        # 条件判断函数
        {
            "decision": "decision",  # 通过 → 直接决策
            "alert": "alert"         # 未通过 → 告警
        }
    )
    
    # 告警后到决策
    workflow.add_edge("alert", "decision")
    
    # 决策后结束
    workflow.add_edge("decision", END)
    
    return workflow.compile()


# ============================================
# 第 6 步：便捷执行函数
# ============================================

def approve_trade(intent: TradeIntent, context: dict = None) -> TradeApprovalState:
    """
    对一笔交易执行完整的风控审批流程
    
    这是风控模块的对外接口——上游只需要调用这个函数即可。
    
    参数：
        intent: 交易意图对象
        context: 上下文信息（持仓、资产等）
    
    返回：
        包含完整审批结果的最终状态
    
    用法：
        result = approve_trade(intent, context)
        if result["final_decision"] == "执行":
            # 执行交易
            pass
        else:
            # 被拦截，查看原因
            print(result["alert_message"])
    """
    # 构建图
    app = build_approval_graph()
    
    # 准备初始状态
    initial_state = {
        "trade_intent": intent,
        "context": context or {},
        "risk_result": None,
        "passed": True,
        "alert_sent": False,
        "alert_message": "",
        "final_decision": "",
        "execution_log": []
    }
    
    # 执行图
    final_state = app.invoke(initial_state)
    
    return final_state


# ============================================
# 第 7 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏗️ LangGraph 风控审批流程测试")
    print("=" * 60)
    print()
    print("图结构：")
    print("  validate_intent → [条件] → risk_check → [条件] → alert → decision → END")
    print()
    
    # 模拟账户上下文
    context = {
        "total_assets": 1_000_000,
        "current_holdings": 350_000,
        "symbol_holdings": {
            "600519.SH": 100_000,
            "000858.SZ": 80_000
        },
        "daily_trade_count": 3
    }
    
    # ============================================
    # 测试 1：正常交易（应通过）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 1：正常小额买入（应通过全部检查）")
    print("=" * 60)
    
    intent_1 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(100, 1500.0)            # 15 万
                .from_factor("高ROE因子", 0.85)
                .with_reason("ROE持续高于行业均值")
                .build())
    
    result_1 = approve_trade(intent_1, context)
    print(f"\n📊 最终决策：{result_1['final_decision']}")
    
    # ============================================
    # 测试 2：超大额交易（应拦截）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 2：超大额买入（应被单笔限额拦截）")
    print("=" * 60)
    
    intent_2 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(10000, 1500.0)          # 1500 万
                .from_factor("测试", 0.9)
                .with_reason("超大额测试")
                .build())
    
    result_2 = approve_trade(intent_2, context)
    print(f"\n📊 最终决策：{result_2['final_decision']}")
    if result_2["alert_message"]:
        print(f"\n告警消息预览：")
        print(result_2["alert_message"][:400])
    
    # ============================================
    # 测试 3：低置信度（应拦截）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 3：低置信度交易（应被置信度门槛拦截）")
    print("=" * 60)
    
    intent_3 = (TradeIntentBuilder()
                .set_symbol("000858.SZ")
                .set_name("五粮液")
                .buy(50, 120.0)
                .from_factor("弱信号", 0.25)   # 置信度只有 25%
                .with_reason("弱信号测试")
                .build())
    
    result_3 = approve_trade(intent_3, context)
    print(f"\n📊 最终决策：{result_3['final_decision']}")
    
    # ============================================
    # 测试 4：无效意图（应拦截在第一步）
    # ============================================
    print("\n" + "=" * 60)
    print("测试 4：无效交易意图（应在验证阶段拦截）")
    print("=" * 60)
    
    # 创建一个空意图（缺少所有字段）
    intent_4 = TradeIntent()
    
    result_4 = approve_trade(intent_4, context)
    print(f"\n📊 最终决策：{result_4['final_decision']}")
    
    print("\n" + "=" * 60)
    print("✅ LangGraph 风控审批流程测试完成")
    print("=" * 60)