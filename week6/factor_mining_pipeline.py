# ============================================
# 因子挖掘完整流程（LangGraph 闭环）
# 流程：生成 → 验证 → 通过则输出，失败则重新生成（最多3次）
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import TypedDict, Optional  # 类型注解

# 导入 LangGraph 核心组件
from langgraph.graph import StateGraph, END

# 导入因子数据模型
from factor_model import FactorDefinition

# 导入节点函数
from gen_factor_node import gen_factor_node    # 生成节点
from validate_factor_node import validate_factor_node  # 验证节点

# ============================================
# 第 1 步：定义状态
# ============================================

class MiningState(TypedDict):
    """
    因子挖掘流程的状态定义
    
    字段说明：
    - factor_idea: 因子想法（会在重试时更新）
    - original_idea: 原始想法（保留用户输入）
    - factor: 因子对象（FactorDefinition 实例）
    - factor_code: 因子代码
    - factor_valid: 因子定义是否有效
    - backtest_result: 回测结果字典
    - validation_passed: 验证是否通过
    - validation_result: 验证结果文本
    - validation_reason: 验证原因
    - validation_suggestion: 改进建议
    - retry_count: 重试次数
    - max_retries: 最大重试次数
    - final_output: 最终输出
    """
    factor_idea: str
    original_idea: str
    factor: Optional[FactorDefinition]
    factor_code: str
    factor_valid: bool
    backtest_result: dict
    validation_passed: bool
    validation_result: str
    validation_reason: str
    validation_suggestion: str
    retry_count: int
    max_retries: int
    final_output: str


# ============================================
# 第 2 步：定义路由函数
# ============================================

def should_retry(state: MiningState) -> str:
    """
    条件路由函数：决定验证后是输出还是重新生成
    
    逻辑：
    - 如果验证通过 → 进入 "summarize" 节点（输出结果）
    - 如果验证失败且重试次数未超 → 进入 "generate" 节点（重新生成）
    - 如果验证失败且重试次数已超 → 进入 "summarize" 节点（输出失败结果）
    
    参数：
        state: 当前状态
    
    返回：
        "generate" 或 "summarize"
    """
    # 获取验证结果和重试次数
    passed = state.get("validation_passed", False)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    
    if passed:
        # 验证通过，输出结果
        print(f"\n✅ 因子验证通过！进入输出阶段")
        return "summarize"
    
    if retry_count < max_retries:
        # 还有重试机会，重新生成
        print(f"\n🔄 验证失败，第 {retry_count}/{max_retries} 次重试...")
        return "generate"
    
    # 重试次数用完
    print(f"\n⚠️ 已达最大重试次数 {max_retries}，输出最终结果")
    return "summarize"


# ============================================
# 第 3 步：汇总输出节点
# ============================================

def summarize_node(state: MiningState) -> MiningState:
    """
    汇总节点：生成最终的因子挖掘报告
    
    参数：
        state: 当前状态
    
    返回：
        更新后的状态
    """
    print(f"\n📄 [汇总节点] 正在生成最终报告...")
    
    # 从状态中读取信息
    original_idea = state.get("original_idea", "")
    factor = state.get("factor")
    passed = state.get("validation_passed", False)
    retry_count = state.get("retry_count", 0)
    backtest = state.get("backtest_result", {})
    reason = state.get("validation_reason", "")
    
    # 构建报告
    lines = []
    lines.append("=" * 60)
    lines.append("📊 因子挖掘最终报告")
    lines.append("=" * 60)
    lines.append(f"原始想法：{original_idea}")
    lines.append(f"重试次数：{retry_count}")
    lines.append("")
    
    if factor:
        lines.append(f"因子名称：{factor.display_name}")
        lines.append(f"因子类型：{factor.factor_type}")
        lines.append(f"因子代码：{factor.code}")
        lines.append(f"因子描述：{factor.description}")
        lines.append("")
    
    lines.append(f"验证结果：{'✅ 通过' if passed else '❌ 未通过'}")
    lines.append(f"验证详情：{reason[:200]}")
    
    if backtest:
        lines.append("")
        lines.append("回测指标：")
        lines.append(f"  夏普比率：{backtest.get('sharpe_ratio', 'N/A')}")
        lines.append(f"  年化收益：{backtest.get('annual_return', 0):.2%}")
        lines.append(f"  最大回撤：{backtest.get('max_drawdown', 0):.2%}")
    
    lines.append("")
    if passed:
        lines.append("✅ 该因子通过验证，可以进行实盘测试")
    else:
        lines.append(f"⚠️ 该因子经过 {retry_count} 次重试后仍未通过验证")
        lines.append("   建议：尝试完全不同的因子方向，或降低验证标准")
    
    report = "\n".join(lines)
    print(report)
    
    # 更新状态
    state["final_output"] = report
    return state


# ============================================
# 第 4 步：构建完整的因子挖掘图
# ============================================

def build_mining_graph() -> StateGraph:
    """
    构建因子挖掘的完整 LangGraph 图
    
    图结构：
                    ┌──────────────┐
                    │   generate   │ ←──────┐
                    │  因子生成节点  │        │
                    └──────┬───────┘        │
                           │                │
                           ▼                │
                    ┌──────────────┐        │
                    │  validate    │        │
                    │  因子验证节点  │        │
                    └──────┬───────┘        │
                           │                │
                           ▼                │
                    ┌──────────────┐        │
                    │ should_retry │        │
                    │  条件路由     │        │
                    └──┬────────┬──┘        │
                       │        │           │
              通过/次数用完   失败且可重试 ──┘
                       │
                       ▼
                    ┌──────────────┐
                    │  summarize   │
                    │  结果汇总节点  │
                    └──────┬───────┘
                           │
                           ▼
                          END
    """
    # 创建状态图
    workflow = StateGraph(MiningState)
    
    # 添加节点
    workflow.add_node("generate", gen_factor_node)       # 生成节点
    workflow.add_node("validate", validate_factor_node)   # 验证节点
    workflow.add_node("summarize", summarize_node)        # 汇总节点
    
    # 设置入口
    workflow.set_entry_point("generate")
    
    # 添加普通边
    workflow.add_edge("generate", "validate")             # 生成 → 验证
    
    # 添加条件边（关键：根据验证结果决定下一步）
    workflow.add_conditional_edges(
        "validate",           # 从验证节点出发
        should_retry,         # 路由函数
        {
            "generate": "generate",     # 如果需要重试 → 回到生成节点
            "summarize": "summarize"    # 如果不需要重试 → 汇总节点
        }
    )
    
    # 汇总后结束
    workflow.add_edge("summarize", END)
    
    return workflow.compile()


# ============================================
# 第 5 步：测试完整流程
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏗️ 因子挖掘完整流程测试")
    print("=" * 60)
    print()
    print("图结构：")
    print("  generate → validate → [条件判断] → summarize")
    print("                          ↑                    │")
    print("                          └── 失败重试 ────────┘")
    print()
    
    # 构建图
    app = build_mining_graph()
    
    # 测试 1：简单因子（可能需要重试）
    print("\n" + "=" * 60)
    print("测试 1：简单因子")
    print("=" * 60)
    
    initial_state_1 = {
        "factor_idea": "ROE > 15%",
        "original_idea": "ROE > 15%",
        "factor": None,
        "factor_code": "",
        "factor_valid": False,
        "backtest_result": {},
        "validation_passed": False,
        "validation_result": "",
        "validation_reason": "",
        "validation_suggestion": "",
        "retry_count": 0,
        "max_retries": 3,
        "final_output": ""
    }
    
    final_state_1 = app.invoke(initial_state_1)
    
    # 测试 2：复杂因子（更可能一次通过）
    print("\n" + "=" * 60)
    print("测试 2：复杂因子")
    print("=" * 60)
    
    initial_state_2 = {
        "factor_idea": "ROE > 15% 且 PE < 20 且股价突破 20 日均线 且成交量放大",
        "original_idea": "多条件筛选的质优股",
        "factor": None,
        "factor_code": "",
        "factor_valid": False,
        "backtest_result": {},
        "validation_passed": False,
        "validation_result": "",
        "validation_reason": "",
        "validation_suggestion": "",
        "retry_count": 0,
        "max_retries": 3,
        "final_output": ""
    }
    
    final_state_2 = app.invoke(initial_state_2)
    
    print("\n" + "=" * 60)
    print("✅ 因子挖掘完整流程测试完成")
    print("=" * 60)