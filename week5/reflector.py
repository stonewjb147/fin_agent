# ============================================
# 反思检查器
# 功能：在 Agent 执行每一步后自动检查结果质量
# 如果结果不满足要求，自动生成改进建议
# 支持三种检查：
#   1. 搜索检查：结果是否包含具体数据
#   2. 计算检查：计算是否合理
#   3. 完整性检查：数据是否足够得出结论
# ============================================

import os  # 操作系统相关功能
from dotenv import load_dotenv  # 加载 .env 环境变量
load_dotenv()

from langchain_deepseek import ChatDeepSeek  # DeepSeek 大模型
from langchain.prompts import PromptTemplate  # 提示词模板

# ============================================
# 创建反思用的大模型实例（温度稍高，允许灵活判断）
# ============================================

# 反思模型温度设为 0.1，比执行模型稍高
# 因为反思需要一定的"判断力"而非机械执行
reflector_llm = ChatDeepSeek(
    model="deepseek-chat",                     # DeepSeek 聊天模型
    temperature=0.1,                            # 稍低温度，保持判断稳定
    api_key=os.getenv("DEEPSEEK_API_KEY")      # 从 .env 读取 API 密钥
)


# ============================================
# 反思函数1：检查搜索结果质量
# ============================================

# 定义反思提示词模板
search_reflection_template = """你是一个质量检查员。请检查以下搜索结果是否满足分析需求。

【原始搜索目标】
{goal}

【搜索关键词】
{query}

【搜索结果】
{result}

【检查标准】
1. 结果是否包含具体的数字数据（如营收金额、增长率百分比）？
2. 结果是否与搜索目标直接相关？
3. 信息是否足够新（最近一年的数据）？

【输出格式】
请严格按照以下 JSON 格式输出：

{{
  "quality": "good" 或 "poor",
  "reason": "判断理由（一句话）",
  "suggestion": "如果 quality 是 poor，给出改进后的搜索关键词；如果 quality 是 good，填 '无需改进'"
}}

JSON 输出："""

# 创建反思提示词模板
search_reflection_prompt = PromptTemplate(
    template=search_reflection_template,
    input_variables=["goal", "query", "result"]  # 三个输入参数
)


def reflect_search_result(goal: str, query: str, result: str) -> dict:
    """
    检查搜索结果质量，如果不好则建议改进搜索词
    
    参数：
        goal: 原始搜索目标，如"获取茅台2025年营收数据"
        query: 实际使用的搜索关键词
        result: 搜索返回的结果文本
    
    返回：
        字典，包含 quality（good/poor）、reason（原因）、suggestion（改进建议）
    """
    # 如果结果为空或包含错误信息
    if not result or "搜索失败" in result or "❌" in result:
        return {
            "quality": "poor",
            "reason": "搜索返回为空或失败",
            "suggestion": f"简化搜索词，使用更通用的关键词重试，如'{query.split()[0]} {query.split()[-1]}'"
        }
    
    # 如果结果太短（可能没有有效数据）
    if len(result) < 100:
        return {
            "quality": "poor",
            "reason": "搜索结果内容过短，可能没有足够信息",
            "suggestion": f"尝试更具体的搜索词，添加'数据'或'财报'等关键词"
        }
    
    try:
        # 调用 LLM 进行质量判断
        reflection_input = search_reflection_prompt.format(
            goal=goal,
            query=query,
            result=result[:1500]  # 只取前 1500 字符，避免 Token 超限
        )
        reflection_response = reflector_llm.invoke(reflection_input)
        
        # 获取 LLM 返回的文本
        reflection_text = reflection_response.content if hasattr(reflection_response, 'content') else str(reflection_response)
        
        # 清理可能的 Markdown 标记
        reflection_text = reflection_text.strip()
        if reflection_text.startswith("```json"):
            reflection_text = reflection_text[7:]
        if reflection_text.startswith("```"):
            reflection_text = reflection_text[3:]
        if reflection_text.endswith("```"):
            reflection_text = reflection_text[:-3]
        reflection_text = reflection_text.strip()
        
        # 解析 JSON
        import json
        result_dict = json.loads(reflection_text)
        return result_dict
    
    except Exception as e:
        # 如果 LLM 调用失败，默认返回需要改进
        return {
            "quality": "poor",
            "reason": f"质量检查异常：{str(e)[:50]}",
            "suggestion": f"建议重新搜索：{query}"
        }


# ============================================
# 反思函数2：检查计算结果合理性
# ============================================

def reflect_calculation_result(expression: str, result: str) -> dict:
    """
    检查计算结果是否合理
    
    参数：
        expression: 计算表达式
        result: 计算结果字符串
    
    返回：
        字典，包含 quality（good/poor）、reason（原因）、suggestion（改进建议）
    """
    # 如果计算失败
    if "失败" in result or "错误" in result or "❌" in result:
        return {
            "quality": "poor",
            "reason": "计算执行失败",
            "suggestion": f"检查表达式语法，尝试简化：{expression}"
        }
    
    # 尝试提取数字结果
    import re
    # 正则匹配：查找结果中的数字
    numbers = re.findall(r'[\d.]+', result)
    
    if numbers:
        # 如果结果是负数但期望是正数（增长率场景）
        value = float(numbers[0])
        if value < -100:
            return {
                "quality": "poor",
                "reason": f"计算结果异常（{value}），增长率通常不会低于-100%",
                "suggestion": f"检查输入数据是否正确，重新确认分子和分母"
            }
    
    # 默认通过
    return {
        "quality": "good",
        "reason": "计算结果正常",
        "suggestion": "无需改进"
    }


# ============================================
# 反思函数3：检查数据完整性
# ============================================

data_completeness_template = """你是一个数据完整性检查员。请检查当前收集的数据是否足够回答用户问题。

【用户问题】
{question}

【已收集的数据】
{collected_data}

【已执行的步骤】
{steps_summary}

【检查标准】
1. 是否同时包含两个对比对象的数据？
2. 关键指标（营收、利润、增长率）是否齐全？
3. 是否缺少行业背景或市场环境数据？

【输出格式】
{{
  "complete": true 或 false,
  "missing": "缺少的数据项（如果 complete 为 false）",
  "suggestion": "建议补充的搜索关键词（如果 complete 为 false）"
}}

JSON 输出："""

data_completeness_prompt = PromptTemplate(
    template=data_completeness_template,
    input_variables=["question", "collected_data", "steps_summary"]
)


def reflect_data_completeness(question: str, collected_data: str, steps_summary: str) -> dict:
    """
    检查已收集的数据是否足够回答用户问题
    
    参数：
        question: 用户原始问题
        collected_data: 已收集的所有数据
        steps_summary: 已执行步骤的摘要
    
    返回：
        字典，包含 complete（是否完整）、missing（缺失项）、suggestion（补充建议）
    """
    if not collected_data or len(collected_data) < 200:
        return {
            "complete": False,
            "missing": "数据量不足，需要更多搜索",
            "suggestion": "至少再执行 2 次搜索获取基础数据"
        }
    
    try:
        reflection_input = data_completeness_prompt.format(
            question=question,
            collected_data=collected_data[:2000],
            steps_summary=steps_summary
        )
        reflection_response = reflector_llm.invoke(reflection_input)
        reflection_text = reflection_response.content if hasattr(reflection_response, 'content') else str(reflection_response)
        
        reflection_text = reflection_text.strip()
        if reflection_text.startswith("```json"):
            reflection_text = reflection_text[7:]
        if reflection_text.startswith("```"):
            reflection_text = reflection_text[3:]
        if reflection_text.endswith("```"):
            reflection_text = reflection_text[:-3]
        reflection_text = reflection_text.strip()
        
        import json
        return json.loads(reflection_text)
    
    except Exception as e:
        return {
            "complete": True,  # 出错时默认通过，避免死循环
            "missing": "",
            "suggestion": ""
        }

# ============================================
# 带反思的搜索函数（供外部调用）
# ============================================

def search_with_reflection(goal: str, initial_query: str, max_retries: int = 3) -> str:
    """
    执行搜索，如果结果不好则自动换词重试
    
    这是一个便捷包装函数，封装了"搜索→检查→改进→重试"的完整循环
    
    参数：
        goal: 搜索目标描述，如"获取茅台最新营收数据"
        initial_query: 初始搜索关键词
        max_retries: 最大重试次数（默认 3 次）
    
    返回：
        最终搜索结果字符串
    """
    # 从 mcp_tools 导入注册中心
    from mcp_tools import registry
    
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
# 带反思的计算函数（供外部调用）
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
    # 从 mcp_tools 导入注册中心
    from mcp_tools import registry
    
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
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("反思检查器测试")
    print("=" * 60)
    
    # 测试1：检查好的搜索结果
    print("\n【测试1】检查好的搜索结果")
    good_result = "贵州茅台2025年实现营业收入1500亿元，同比增长16.5%，净利润800亿元"
    check = reflect_search_result("获取茅台营收", "茅台 2025 营收", good_result)
    print(f"  质量：{check.get('quality')}")
    print(f"  原因：{check.get('reason')}")
    print(f"  建议：{check.get('suggestion')}")
    
    # 测试2：检查差的搜索结果
    print("\n【测试2】检查差的搜索结果")
    poor_result = "茅台是中国著名的白酒品牌，产自贵州省仁怀市茅台镇"
    check = reflect_search_result("获取茅台营收数据", "茅台", poor_result)
    print(f"  质量：{check.get('quality')}")
    print(f"  原因：{check.get('reason')}")
    print(f"  建议：{check.get('suggestion')}")
    
    # 测试3：检查失败结果
    print("\n【测试3】检查搜索失败")
    check = reflect_search_result("获取数据", "xxx", "❌ 搜索失败")
    print(f"  质量：{check.get('quality')}")
    print(f"  建议：{check.get('suggestion')}")
    
    # 测试4：检查计算
    print("\n【测试4】检查正常计算")
    check = reflect_calculation_result("(800-650)/650*100", "计算结果：23.0769")
    print(f"  质量：{check.get('quality')}")
    
    print("\n【测试5】检查异常计算")
    check = reflect_calculation_result("(100-650)/650*100", "计算结果：-84.6154")
    print(f"  质量：{check.get('quality')}")