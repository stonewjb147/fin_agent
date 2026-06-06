# ============================================
# 因子验证节点
# 功能：对生成的因子进行模拟回测验证
# 验证指标：夏普比率、年化收益率、最大回撤
# 验证通过标准：夏普比率 > 0.5 且 年化收益 > 5%
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 解析
import random  # 用于模拟回测数据（实际应使用真实数据）
import numpy as np  # 数值计算

# 导入因子数据模型
from factor_model import FactorDefinition

# 导入 DeepSeek
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# ============================================
# 第 1 步：初始化服务
# ============================================

# Langfuse 监控
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# DeepSeek 模型（用于分析验证结果）
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.1,                              # 验证阶段用更低温度，更保守
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# ============================================
# 第 2 步：模拟回测函数
# ============================================

def run_backtest_simulation(factor: FactorDefinition) -> dict:
    """
    执行因子回测模拟
    
    在实际生产环境中，这里应该：
    1. 加载真实股票数据
    2. 根据 factor.code 筛选股票
    3. 构建投资组合
    4. 计算真实收益
    
    为了学习目的，这里使用模拟数据。
    
    参数：
        factor: 因子定义对象
    
    返回：
        回测结果字典，包含：
        - sharpe_ratio: 夏普比率
        - annual_return: 年化收益率
        - max_drawdown: 最大回撤
        - win_rate: 胜率
        - total_trades: 总交易次数
    """
    print(f"\n📊 [回测引擎] 正在回测因子：{factor.display_name}")
    print(f"   因子代码：{factor.code}")
    
    # 根据因子代码的复杂度模拟不同质量的回测结果
    # 规则：
    #   - 代码越复杂（包含多个条件），因子质量越高
    #   - 包含 and 条件 → 更精确 → 更高夏普
    #   - 包含 rolling/mean/std → 更稳健 → 更低回撤
    
    code = factor.code
    
    # 计算代码复杂度分数
    complexity_score = 0
    if "and" in code or "&" in code:
        complexity_score += 1      # 多条件筛选加分
    if "rolling" in code:
        complexity_score += 1      # 滚动计算加分
    if "mean" in code or "std" in code:
        complexity_score += 1      # 统计函数加分
    if "shift" in code:
        complexity_score += 0.5    # 时间比较加分
    
    # 根据复杂度生成模拟结果
    # 复杂因子通常表现更好
    base_sharpe = 0.3 + (complexity_score * 0.3)  # 基础夏普
    noise = random.uniform(-0.15, 0.25)            # 随机波动
    
    sharpe_ratio = round(base_sharpe + noise, 2)
    annual_return = round(random.uniform(0.03, 0.18) + (complexity_score * 0.03), 4)
    max_drawdown = round(-random.uniform(0.05, 0.30) + (complexity_score * 0.02), 4)
    win_rate = round(random.uniform(0.40, 0.65) + (complexity_score * 0.03), 2)
    total_trades = random.randint(50, 200)
    
    # 确保指标在合理范围内
    sharpe_ratio = max(0.1, min(sharpe_ratio, 2.5))
    annual_return = max(0.01, min(annual_return, 0.30))
    max_drawdown = max(-0.35, min(max_drawdown, -0.02))
    win_rate = max(0.30, min(win_rate, 0.75))
    
    result = {
        "sharpe_ratio": sharpe_ratio,         # 夏普比率
        "annual_return": annual_return,        # 年化收益率
        "max_drawdown": max_drawdown,          # 最大回撤
        "win_rate": win_rate,                  # 胜率
        "total_trades": total_trades,          # 总交易次数
        "complexity_score": complexity_score   # 复杂度分数（调试用）
    }
    
    print(f"   夏普比率：{sharpe_ratio}")
    print(f"   年化收益：{annual_return:.2%}")
    print(f"   最大回撤：{max_drawdown:.2%}")
    print(f"   胜率：{win_rate:.0%}")
    
    return result


# ============================================
# 第 3 步：验证判断逻辑
# ============================================

def evaluate_results(backtest_result: dict) -> tuple:
    """
    根据回测结果判断因子是否通过验证
    
    通过标准：
    - 夏普比率 >= 0.5（风险调整后收益合理）
    - 年化收益 >= 5%（跑赢无风险利率）
    - 最大回撤 >= -20%（回撤在可接受范围内）
    
    参数：
        backtest_result: 回测结果字典
    
    返回：
        (是否通过, 原因说明, 改进建议)
    """
    sharpe = backtest_result.get("sharpe_ratio", 0)
    ret = backtest_result.get("annual_return", 0)
    drawdown = backtest_result.get("max_drawdown", -1)
    
    # 逐项检查
    checks = []
    passed = True
    
    # 检查1：夏普比率
    if sharpe >= 0.5:
        checks.append(f"✅ 夏普比率 {sharpe} >= 0.5，通过")
    else:
        checks.append(f"❌ 夏普比率 {sharpe} < 0.5，未通过")
        passed = False
    
    # 检查2：年化收益
    if ret >= 0.05:
        checks.append(f"✅ 年化收益 {ret:.2%} >= 5%，通过")
    else:
        checks.append(f"❌ 年化收益 {ret:.2%} < 5%，未通过")
        passed = False
    
    # 检查3：最大回撤
    if drawdown >= -0.20:
        checks.append(f"✅ 最大回撤 {drawdown:.2%} >= -20%，通过")
    else:
        checks.append(f"❌ 最大回撤 {drawdown:.2%} < -20%，未通过")
        passed = False
    
    reason = "\n".join(checks)
    
    # 生成改进建议
    if not passed:
        suggestion = "建议：添加更多筛选条件（使用 and 连接），或使用滚动统计（rolling/mean/std）来提高因子质量"
    else:
        suggestion = "因子表现优秀，可以投入使用"
    
    return passed, reason, suggestion


# ============================================
# 第 4 步：因子改进函数（验证失败时调用）
# ============================================

# 因子改进的提示词
improve_template = """你是一位量化研究员。以下是需要改进的因子。

【当前因子】
名称：{name}
代码：{code}
描述：{description}

【回测结果】
夏普比率：{sharpe_ratio}
年化收益：{annual_return}
最大回撤：{max_drawdown}

【失败原因】
{reason}

【要求】
请改进这个因子，使其通过验证（夏普 >= 0.5，年化收益 >= 5%）。
改进方向：
1. 添加 and 条件使筛选更精确
2. 使用 rolling/mean/std 使信号更稳健
3. 添加时间维度比较（shift）

【输出格式】
请输出改进后的因子想法（一句话描述）"""

improve_prompt = PromptTemplate(
    template=improve_template,
    input_variables=["name", "code", "description", "sharpe_ratio", "annual_return", "max_drawdown", "reason"]
)


def improve_factor(factor: FactorDefinition, backtest_result: dict, reason: str) -> str:
    """
    因子验证失败时，调用 LLM 生成改进后的因子想法
    
    参数：
        factor: 当前因子定义
        backtest_result: 回测结果
        reason: 失败原因
    
    返回：
        改进后的因子想法（新 idea）
    """
    print(f"\n💡 [因子改进] 正在生成改进想法...")
    
    try:
        improve_input = improve_prompt.format(
            name=factor.name,
            code=factor.code,
            description=factor.description,
            sharpe_ratio=backtest_result.get("sharpe_ratio", 0),
            annual_return=backtest_result.get("annual_return", 0),
            max_drawdown=backtest_result.get("max_drawdown", 0),
            reason=reason
        )
        
        response = llm.invoke(improve_input)
        improved_idea = response.content if hasattr(response, 'content') else str(response)
        improved_idea = improved_idea.strip()
        
        print(f"   原想法：{factor.source_idea}")
        print(f"   改进后：{improved_idea}")
        
        return improved_idea
    
    except Exception as e:
        print(f"   ⚠️ 改进生成失败：{e}")
        # 返回原始想法加上自动增强
        return f"{factor.source_idea} 且满足多条件筛选"


# ============================================
# 第 5 步：LangGraph 验证节点
# ============================================

def validate_factor_node(state: dict) -> dict:
    """
    LangGraph 节点：因子验证
    
    从状态中读取因子，执行回测，判断是否通过
    
    参数：
        state: 状态字典，必须包含 "factor" 字段（FactorDefinition 对象）
    
    返回：
        更新后的状态字典，新增验证相关字段
    """
    # 从状态中读取因子对象
    factor = state.get("factor")
    
    if factor is None:
        # 没有因子，跳过验证
        state["validation_result"] = "❌ 失败"
        state["validation_reason"] = "无因子可验证"
        state["validation_passed"] = False
        return state
    
    print(f"\n🔍 [因子验证节点] 正在验证因子：{factor.display_name}")
    
    # 第一步：基本有效性检查
    if not factor.is_valid():
        state["validation_result"] = "❌ 失败"
        state["validation_reason"] = "因子定义不完整（名称、代码或类型缺失）"
        state["validation_passed"] = False
        state["backtest_result"] = {}
        return state
    
    # 第二步：执行回测模拟
    backtest_result = run_backtest_simulation(factor)
    
    # 第三步：评估回测结果
    passed, reason, suggestion = evaluate_results(backtest_result)
    
    # 第四步：更新状态
    state["backtest_result"] = backtest_result
    state["validation_passed"] = passed
    state["validation_result"] = "✅ 通过" if passed else "❌ 失败"
    state["validation_reason"] = reason
    state["validation_suggestion"] = suggestion
    
    # 如果验证失败，生成改进想法
    if not passed:
        improved_idea = improve_factor(factor, backtest_result, reason)
        state["factor_idea"] = improved_idea  # 更新想法，准备重新生成
        state["retry_count"] = state.get("retry_count", 0) + 1  # 增加重试计数
    else:
        # 验证通过，更新因子对象的验证信息
        factor.validation = "passed"
        factor.sharpe_ratio = backtest_result.get("sharpe_ratio")
        factor.annual_return = backtest_result.get("annual_return")
        factor.max_drawdown = backtest_result.get("max_drawdown")
        state["factor"] = factor
    
    print(f"   验证结果：{state['validation_result']}")
    
    return state


# ============================================
# 第 6 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 因子验证节点测试")
    print("=" * 60)
    
    # 导入因子生成节点
    from gen_factor_node import generate_factor
    
    # 测试 1：生成并验证一个简单因子
    print("\n" + "─" * 40)
    print("测试 1：简单因子（可能不通过）")
    print("─" * 40)
    
    idea_1 = "ROE > 15%"
    factor_1 = generate_factor(idea_1)
    
    test_state_1 = {
        "factor_idea": idea_1,
        "factor": factor_1,
        "factor_code": factor_1.code,
        "factor_valid": factor_1.is_valid(),
        "validation_passed": False,
        "retry_count": 0
    }
    
    updated_state_1 = validate_factor_node(test_state_1)
    print(f"\n验证结果：{updated_state_1['validation_result']}")
    print(f"验证原因：{updated_state_1['validation_reason'][:100]}...")
    
    # 测试 2：生成并验证一个复杂因子
    print("\n" + "─" * 40)
    print("测试 2：复杂因子（更可能通过）")
    print("─" * 40)
    
    idea_2 = "ROE > 15% 且 PE < 20 且股价突破20日均线"
    factor_2 = generate_factor(idea_2)
    
    test_state_2 = {
        "factor_idea": idea_2,
        "factor": factor_2,
        "factor_code": factor_2.code,
        "factor_valid": factor_2.is_valid(),
        "validation_passed": False,
        "retry_count": 0
    }
    
    updated_state_2 = validate_factor_node(test_state_2)
    print(f"\n验证结果：{updated_state_2['validation_result']}")
    print(f"验证原因：{updated_state_2['validation_reason'][:100]}...")
    
    # 测试 3：如果失败，查看改进后的想法
    if not updated_state_1.get("validation_passed", False):
        print("\n" + "─" * 40)
        print("测试 3：失败后的改进想法")
        print("─" * 40)
        print(f"原想法：{idea_1}")
        print(f"改进后：{updated_state_1.get('factor_idea', '无')}")
    
    print("\n" + "=" * 60)
    print("✅ 因子验证节点测试完成")
    print("=" * 60)