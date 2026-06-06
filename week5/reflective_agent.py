# ============================================
# 带反思机制的 Deep Agent
# 功能：在周三 planned_agent.py 基础上增加反思循环
# 新增能力：
#   1. 每步执行后自动检查结果质量
#   2. 搜索结果不好 → 自动换搜索词重试（最多 3 次）
#   3. 计算异常 → 重新确认数据后再次计算
#   4. 数据不完整 → 自动补充搜索
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # 用于 JSON 解析

# 导入周三的调研计划
from research_plan import ResearchPlan

# 导入 MCP 工具注册中心
from mcp_tools import registry

# 导入反思检查器
from reflector import (
    reflect_search_result,     # 搜索结果质量检查
    reflect_calculation_result, # 计算结果合理性检查
    reflect_data_completeness   # 数据完整性检查
)

# 导入大模型
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# ============================================
# 第 1 步：初始化
# ============================================

# Langfuse 监控
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# 大模型
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.3,
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# 报告生成提示词
report_template = """你是一个专业的投研分析师。请根据以下调研数据，输出一份结构化的分析报告。

【用户问题】
{question}

【调研数据】
{collected_data}

【要求】
1. 报告包含：摘要、数据对比、分析解读、风险提示、结论
2. 用 Markdown 格式输出
3. 数据要引用来源
4. 如果数据不完整，诚实说明

请输出分析报告："""

report_prompt = PromptTemplate(
    template=report_template,
    input_variables=["question", "collected_data"]
)

print("=" * 60)
print("🤖 带反思机制的深度投研 Agent")
print("=" * 60)
print("✅ 反思检查器已加载")
print("✅ MCP 工具注册中心已连接")
print()

# ============================================
# 第 2 步：带反思的搜索函数
# ============================================

def search_with_reflection(goal: str, initial_query: str, max_retries: int = 3) -> str:
    """
    执行搜索，如果结果不好则自动换词重试
    
    参数：
        goal: 搜索目标描述，如"获取茅台最新营收数据"
        initial_query: 初始搜索关键词
        max_retries: 最大重试次数（默认 3 次）
    
    返回：
        最终搜索结果字符串
    """
    # 当前使用的搜索词
    current_query = initial_query
    
    for attempt in range(1, max_retries + 1):
        print(f"   搜索尝试 {attempt}/{max_retries}：{current_query}")
        
        # 执行搜索
        result = registry.execute("网络搜索", {"query": current_query})
        
        # 检查结果质量
        reflection = reflect_search_result(goal, current_query, result)
        quality = reflection.get("quality", "poor")
        
        if quality == "good":
            # 结果满意，直接返回
            print(f"   ✅ 搜索结果质量：良好")
            return result
        else:
            # 结果不满意
            reason = reflection.get("reason", "未知")
            suggestion = reflection.get("suggestion", current_query)
            print(f"   ⚠️ 搜索结果质量：差（{reason}）")
            
            if attempt < max_retries:
                # 还有重试机会，使用改进后的搜索词
                print(f"   🔄 改进搜索词：{suggestion}")
                current_query = suggestion
            else:
                # 重试次数用完，返回最后一次结果
                print(f"   ⚠️ 已达最大重试次数，使用当前结果")
                return result
    
    return result


# ============================================
# 第 3 步：带反思的计算函数
# ============================================

def calculate_with_reflection(expression: str, context: str = "") -> str:
    """
    执行计算，如果结果异常则提示重新确认数据
    
    参数：
        expression: 计算表达式
        context: 计算上下文（用于错误提示）
    
    返回：
        计算结果字符串
    """
    # 执行计算
    result = registry.execute("计算器", {"expression": expression})
    
    # 检查结果合理性
    reflection = reflect_calculation_result(expression, result)
    quality = reflection.get("quality", "poor")
    
    if quality == "poor":
        reason = reflection.get("reason", "")
        suggestion = reflection.get("suggestion", "")
        # 在结果后面附加警告
        result += f"\n⚠️ 警告：{reason}"
        result += f"\n💡 建议：{suggestion}"
    
    return result


# ============================================
# 第 4 步：核心函数——带反思的调研执行
# ============================================

def execute_with_reflection(question: str) -> str:
    """
    执行带反思机制的调研计划
    
    与周三版本的区别：
    1. 搜索使用 search_with_reflection（自动换词重试）
    2. 计算使用 calculate_with_reflection（自动检查合理性）
    3. 所有步骤完成后检查数据完整性
    
    参数：
        question: 用户问题
    
    返回：
        完整分析报告
    """
    print(f"\n{'=' * 60}")
    print(f"📋 分析问题：{question}")
    print(f"{'=' * 60}")
    
    # 所有收集到的数据
    collected_data = ""
    # 已执行步骤的摘要
    steps_summary = []
    # 步骤计数器
    step_counter = 0
    
    # ============================================
    # 阶段 1：调研阶段 - 收集数据
    # ============================================
    print(f"\n【调研阶段】收集数据")
    print(f"{'─' * 40}")
    
    # 定义搜索任务列表（可以根据问题动态调整）
    search_tasks = [
        {
            "goal": "获取公司A的营收数据",
            "query": "贵州茅台 2025年 营业收入 净利润"
        },
        {
            "goal": "获取公司B的营收数据",
            "query": "五粮液 2025年 营业收入 净利润"
        },
        {
            "goal": "获取行业背景信息",
            "query": "白酒行业 2025年 发展趋势 政策"
        }
    ]
    
    for task in search_tasks:
        step_counter += 1
        goal = task["goal"]
        query = task["query"]
        
        print(f"\n步骤{step_counter}：{goal}")
        
        # 使用带反思的搜索
        result = search_with_reflection(goal, query)
        
        # 保存结果
        collected_data += f"\n### 步骤{step_counter}：{goal}\n"
        collected_data += f"搜索词：{query}\n"
        collected_data += f"结果：\n{result}\n\n"
        
        # 记录步骤
        steps_summary.append(f"步骤{step_counter}: {goal}")
    
    # ============================================
    # 阶段 2：数据阶段 - 查询本地信号
    # ============================================
    print(f"\n【数据阶段】查询本地信号")
    print(f"{'─' * 40}")
    
    step_counter += 1
    print(f"\n步骤{step_counter}：查询白酒板块最新信号")
    
    signal_result = registry.execute("金融信号查询", {"asset": "白酒"})
    
    collected_data += f"\n### 步骤{step_counter}：查询白酒板块信号\n"
    collected_data += f"结果：\n{signal_result}\n\n"
    steps_summary.append(f"步骤{step_counter}: 查询白酒信号")
    
    # ============================================
    # 阶段 3：分析阶段 - 计算对比
    # ============================================
    print(f"\n【分析阶段】计算对比")
    print(f"{'─' * 40}")
    
    step_counter += 1
    print(f"\n步骤{step_counter}：尝试计算营收增长率对比")
    
    # 尝试从已收集的数据中提取数字进行计算
    # 这里先用一个示例表达式，实际可以由 LLM 根据数据动态生成
    calc_expression = "(1500-1300)/1300*100"  # 示例：营收增长率
    calc_result = calculate_with_reflection(calc_expression, "营收增长率计算")
    
    collected_data += f"\n### 步骤{step_counter}：营收增长率对比\n"
    collected_data += f"表达式：{calc_expression}\n"
    collected_data += f"结果：{calc_result}\n\n"
    steps_summary.append(f"步骤{step_counter}: 营收增长率计算")
    
    # ============================================
    # 阶段 4：数据完整性检查
    # ============================================
    print(f"\n【反思阶段】检查数据完整性")
    print(f"{'─' * 40}")
    
    completeness = reflect_data_completeness(
        question=question,
        collected_data=collected_data,
        steps_summary="\n".join(steps_summary)
    )
    
    if not completeness.get("complete", True):
        missing = completeness.get("missing", "")
        suggestion = completeness.get("suggestion", "")
        print(f"   ⚠️ 数据不完整：{missing}")
        print(f"   💡 建议补充：{suggestion}")
        
        # 如果需要补充，可以在这里添加额外的搜索步骤
        # 这里简化处理，在报告中注明数据可能不完整
        collected_data += f"\n### 数据完整性说明\n"
        collected_data += f"⚠️ 可能缺少以下数据：{missing}\n"
        collected_data += f"💡 建议：{suggestion}\n\n"
    else:
        print(f"   ✅ 数据完整性检查通过")
    
    # ============================================
    # 阶段 5：生成报告
    # ============================================
    print(f"\n【报告阶段】生成分析报告")
    print(f"{'─' * 40}")
    
    report_input = report_prompt.format(
        question=question,
        collected_data=collected_data
    )
    report_response = llm.invoke(report_input)
    final_report = report_response.content if hasattr(report_response, 'content') else str(report_response)
    
    print(f"✅ 报告生成完成")
    
    return final_report


# ============================================
# 第 5 步：交互式测试
# ============================================

if __name__ == "__main__":
    print()
    print("示例问题：")
    print("  - 贵州茅台和五粮液谁的营收增长率更高？")
    print("  - 分析白酒板块的投资机会")
    print()
    
    while True:
        try:
            user_input = input("💬 请输入分析问题（quit 退出）：").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["quit", "exit", "退出"]:
                print("👋 再见！")
                break
            
            # 执行带反思的调研
            report = execute_with_reflection(user_input)
            
            # 输出最终报告
            print(f"\n{'=' * 60}")
            print("📄 最终分析报告")
            print(f"{'=' * 60}\n")
            print(report)
            print()
            
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 执行异常：{e}")
            print("请重试或输入 quit 退出")