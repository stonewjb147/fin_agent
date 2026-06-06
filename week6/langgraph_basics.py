# ============================================
# LangGraph 基础概念演示
# 核心三要素：
#   State（状态）：在节点之间传递的数据对象
#   Node（节点）：执行具体任务的函数
#   Edge（边）：节点之间的连接方向
#
# 类比：State 是流水线上的产品，Node 是工位，Edge 是传送带
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from typing import TypedDict, List  # 类型注解

# 导入 LangGraph 核心组件
from langgraph.graph import StateGraph, END  # StateGraph: 状态图, END: 终止节点

# ============================================
# 第 1 步：定义 State（状态）
# ============================================

# State 就是在节点之间流转的数据结构
# 它继承自 TypedDict，定义了图中有哪些数据字段
class FactorState(TypedDict):
    """
    因子挖掘流程的状态定义
    
    字段说明：
    - factor_idea: 因子想法描述（如"ROE > 15% 的股票表现更好"）
    - factor_code: 生成的因子代码（Python 表达式）
    - validation_result: 验证结果（通过/失败）
    - validation_reason: 验证原因（为什么通过或失败）
    - final_output: 最终输出的汇总信息
    """
    factor_idea: str           # 因子想法
    factor_code: str           # 因子代码
    validation_result: str     # 验证结果
    validation_reason: str     # 验证原因
    final_output: str          # 最终输出


# ============================================
# 第 2 步：定义 Node（节点函数）
# ============================================

# 节点 1：生成因子
def generate_factor(state: FactorState) -> FactorState:
    """
    节点1：因子生成器
    
    功能：读取用户的因子想法，生成对应的 Python 代码
    
    参数：
        state: 当前状态（包含 factor_idea）
    
    返回：
        更新后的状态（新增 factor_code）
    """
    print("\n🔧 [节点1] 正在生成因子代码...")
    
    # 从状态中读取因子想法
    idea = state.get("factor_idea", "")
    print(f"   输入想法：{idea}")
    
    # 模拟因子代码生成（实际会用 LLM 生成）
    # 这里先写死一个示例，周二会接入 DeepSeek
    if "ROE" in idea or "roe" in idea:
        # 如果想法包含 ROE，生成 ROE 筛选代码
        generated_code = "factor = (data['roe'] > 0.15)"
    elif "PE" in idea or "pe" in idea:
        # 如果想法包含 PE，生成 PE 筛选代码
        generated_code = "factor = (data['pe'] < 20)"
    else:
        # 默认生成一个简单因子
        generated_code = "factor = (data['close'] > data['close'].shift(20))"
    
    print(f"   生成代码：{generated_code}")
    
    # 更新状态并返回
    state["factor_code"] = generated_code
    return state


# 节点 2：验证因子
def validate_factor(state: FactorState) -> FactorState:
    """
    节点2：因子验证器
    
    功能：检查生成的因子代码是否合理
    
    参数：
        state: 当前状态（包含 factor_code）
    
    返回：
        更新后的状态（新增 validation_result 和 validation_reason）
    """
    print("\n🔍 [节点2] 正在验证因子...")
    
    # 从状态中读取因子代码
    code = state.get("factor_code", "")
    print(f"   检查代码：{code}")
    
    # 验证逻辑（实际会用回测数据验证，周四会实现）
    # 这里先做基本的语法检查
    if "=" in code and "data" in code:
        # 代码语法基本正确
        result = "✅ 通过"
        reason = "因子代码语法正确，包含数据引用和赋值操作"
    else:
        # 代码语法有问题
        result = "❌ 失败"
        reason = "因子代码缺少必要的数据引用或赋值操作"
    
    print(f"   验证结果：{result}")
    print(f"   验证原因：{reason}")
    
    # 更新状态
    state["validation_result"] = result
    state["validation_reason"] = reason
    return state


# 节点 3：输出汇总
def summarize(state: FactorState) -> FactorState:
    """
    节点3：结果汇总器
    
    功能：将前面的结果汇总成最终输出
    
    参数：
        state: 当前状态（包含所有前面节点的结果）
    
    返回：
        更新后的状态（新增 final_output）
    """
    print("\n📄 [节点3] 正在汇总结果...")
    
    # 从状态中读取各节点的输出
    idea = state.get("factor_idea", "")
    code = state.get("factor_code", "")
    result = state.get("validation_result", "")
    reason = state.get("validation_reason", "")
    
    # 构建汇总输出
    summary = f"""
╔══════════════════════════════════╗
║       因子挖掘结果汇总            ║
╠══════════════════════════════════╣
║ 因子想法：{idea[:40]}
║ 因子代码：{code[:40]}
║ 验证结果：{result}
║ 验证原因：{reason[:40]}
╚══════════════════════════════════╝
"""
    
    print(summary)
    
    # 更新状态
    state["final_output"] = summary
    return state


# ============================================
# 第 3 步：构建 Graph（图）
# ============================================

def build_factor_graph() -> StateGraph:
    """
    构建因子挖掘的 LangGraph 图
    
    图结构：
        START → generate_factor → validate_factor → summarize → END
    
    返回：
        编译好的 StateGraph 对象
    """
    # 创建状态图，传入 State 类型
    workflow = StateGraph(FactorState)
    
    # 添加节点（把函数注册为节点）
    workflow.add_node("generate", generate_factor)    # 生成节点
    workflow.add_node("validate", validate_factor)    # 验证节点
    workflow.add_node("summarize", summarize)          # 汇总节点
    
    # 添加边（定义节点之间的执行顺序）
    workflow.set_entry_point("generate")               # 入口：从 generate 开始
    workflow.add_edge("generate", "validate")          # generate → validate
    workflow.add_edge("validate", "summarize")         # validate → summarize
    workflow.add_edge("summarize", END)                # summarize → 结束
    
    # 编译图（编译后就可以执行了）
    return workflow.compile()


# ============================================
# 第 4 步：运行图
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏗️ LangGraph 基础演示：因子挖掘流程")
    print("=" * 60)
    print()
    print("图结构：")
    print("  START → generate_factor → validate_factor → summarize → END")
    print()
    
    # 构建图
    app = build_factor_graph()
    
    # 准备初始状态
    initial_state = {
        "factor_idea": "ROE > 15% 的股票长期表现更好",  # 因子想法
        "factor_code": "",                               # 待生成
        "validation_result": "",                         # 待验证
        "validation_reason": "",                         # 待填写
        "final_output": ""                               # 待汇总
    }
    
    print("初始状态：")
    print(f"  因子想法：{initial_state['factor_idea']}")
    print()
    
    # 执行图
    # invoke 方法会按照图的边依次执行所有节点
    final_state = app.invoke(initial_state)
    
    print("\n" + "=" * 60)
    print("✅ 图执行完成！")
    print("=" * 60)
    print(f"\n最终状态：")
    print(f"  因子代码：{final_state['factor_code']}")
    print(f"  验证结果：{final_state['validation_result']}")