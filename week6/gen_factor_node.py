# ============================================
# 因子生成节点
# 功能：接收因子想法，调用 DeepSeek 生成结构化的因子定义
# 这是 LangGraph 图中"因子挖掘"的第一个节点
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 解析

# 导入因子数据模型
from factor_model import FactorDefinition

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek

# 导入提示词模板
from langchain.prompts import PromptTemplate

# 导入 Langfuse 回调（监控用）
from langfuse.callback import CallbackHandler

# ============================================
# 第 1 步：初始化 DeepSeek（绑定监控）
# ============================================

# 创建 Langfuse 回调处理器
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),       # 公钥
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),       # 私钥
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")  # 服务地址
)

# 创建 DeepSeek 模型实例
llm = ChatDeepSeek(
    model="deepseek-chat",                      # 模型名称
    temperature=0.3,                             # 温度：保留一定创造性
    api_key=os.getenv("DEEPSEEK_API_KEY"),      # API 密钥
    callbacks=[langfuse_handler]                # 绑定监控
)

# ============================================
# 第 2 步：定义因子生成的提示词
# ============================================

# 这个提示词是"因子生成"的核心——它告诉 LLM 什么是好因子、如何生成
gen_factor_template = """你是一位资深的量化研究员，擅长将投资想法转化为可计算的因子。

【任务】
根据用户的因子想法，生成一个结构化的因子定义。

【因子类型说明】
1. 基本面因子：基于财务数据（ROE、PE、PB、营收增长率等）
2. 技术面因子：基于价格和成交量（均线、RSI、MACD等）
3. 情绪面因子：基于新闻、舆情、分析师评级等
4. 另类数据因子：基于卫星图像、电商数据、招聘数据等

【代码规范】
- 因子代码必须是有效的 Python 表达式
- 数据统一放在 data 字典中，例如：data['roe']、data['close']
- 因子结果是一个布尔 Series（True=符合条件）或数值 Series
- 可以使用 pandas 的函数：shift()、rolling()、mean()、std() 等
- 示例：
  - "factor = (data['roe'] > 0.15)"  → 筛选 ROE > 15%
  - "factor = (data['close'] > data['close'].shift(20))" → 价格突破20日均线
  - "factor = (data['volume'] > data['volume'].rolling(20).mean() * 1.5)" → 放量

【输出格式】
请严格按照以下 JSON 格式输出，不要添加任何其他内容：

{{
  "name": "因子英文名（小写+下划线，如 high_roe）",
  "display_name": "因子中文名（如 高ROE因子）",
  "description": "因子逻辑的一句话描述",
  "factor_type": "基本面/技术面/情绪面/另类数据",
  "code": "factor = 因子代码表达式",
  "data_requirements": ["需要的","数据字段","列表"],
  "parameters": {{"参数名": 参数值}}
}}

【用户的想法】
{idea}

【JSON 输出】"""

# 创建提示词模板
gen_factor_prompt = PromptTemplate(
    template=gen_factor_template,
    input_variables=["idea"]  # 只需要用户的因子想法
)

# ============================================
# 第 3 步：因子生成函数
# ============================================

def generate_factor(idea: str) -> FactorDefinition:
    """
    根据因子想法，调用 DeepSeek 生成结构化的因子定义
    
    参数：
        idea: 用户的因子想法，如 "ROE > 15% 的股票长期表现更好"
    
    返回：
        FactorDefinition 对象，包含生成的因子代码和元数据
    """
    print(f"\n🔧 [因子生成节点] 正在生成因子...")
    print(f"   输入想法：{idea}")
    
    try:
        # 构建提示词
        prompt_input = gen_factor_prompt.format(idea=idea)
        
        # 调用 DeepSeek 生成因子
        response = llm.invoke(prompt_input)
        
        # 提取 LLM 返回的文本
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # 清理可能的 Markdown 代码块标记
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]  # 去掉 ```json
        if response_text.startswith("```"):
            response_text = response_text[3:]  # 去掉 ```
        if response_text.endswith("```"):
            response_text = response_text[:-3]  # 去掉结尾 ```
        response_text = response_text.strip()
        
        # 解析 JSON
        factor_data = json.loads(response_text)
        
        # 补充来源想法
        factor_data["source_idea"] = idea
        
        # 用数据类封装
        factor = FactorDefinition.from_llm_response(factor_data)
        
        # 打印生成结果
        print(f"   ✅ 因子生成成功")
        print(f"   名称：{factor.display_name}")
        print(f"   类型：{factor.factor_type}")
        print(f"   代码：{factor.code}")
        print(f"   所需数据：{', '.join(factor.data_requirements)}")
        print(f"   有效性：{factor.is_valid()}")
        
        return factor
    
    except json.JSONDecodeError as e:
        # JSON 解析失败
        print(f"   ❌ JSON 解析失败：{e}")
        print(f"   LLM 原始输出：{response_text[:200]}...")
        
        # 返回一个默认的"失败"因子
        return FactorDefinition(
            name="parse_error",
            display_name="解析失败",
            description=f"LLM 输出格式错误：{str(e)[:50]}",
            factor_type="基本面",
            code="factor = (data['close'] > 0)",
            data_requirements=["close"],
            parameters={},
            source_idea=idea
        )
    
    except Exception as e:
        # 其他异常
        print(f"   ❌ 因子生成异常：{e}")
        
        return FactorDefinition(
            name="generation_error",
            display_name="生成失败",
            description=f"异常：{str(e)[:50]}",
            factor_type="基本面",
            code="factor = (data['close'] > 0)",
            data_requirements=["close"],
            parameters={},
            source_idea=idea
        )


# ============================================
# 第 4 步：创建 LangGraph 节点函数
# ============================================

def gen_factor_node(state: dict) -> dict:
    """
    LangGraph 节点：因子生成
    
    这个函数符合 LangGraph 节点的标准接口：
    - 输入：当前状态字典
    - 输出：更新后的状态字典
    
    参数：
        state: 状态字典，必须包含 "factor_idea" 字段
    
    返回：
        更新后的状态字典，新增 "factor" 字段
    """
    # 从状态中读取因子想法
    idea = state.get("factor_idea", "")
    
    if not idea:
        # 如果没有想法，使用默认值
        idea = "ROE > 15% 的绩优股"
        state["factor_idea"] = idea
    
    # 调用生成函数
    factor = generate_factor(idea)
    
    # 将生成的因子存入状态
    state["factor"] = factor
    state["factor_code"] = factor.code
    state["factor_valid"] = factor.is_valid()
    
    return state


# ============================================
# 第 5 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 因子生成节点测试")
    print("=" * 60)
    
    # 测试 1：基本面因子
    print("\n" + "─" * 40)
    print("测试 1：基本面因子")
    print("─" * 40)
    idea_1 = "ROE > 15% 且 PE < 20 的质优股"
    factor_1 = generate_factor(idea_1)
    print(f"\n生成结果：\n{factor_1}")
    
    # 测试 2：技术面因子
    print("\n" + "─" * 40)
    print("测试 2：技术面因子")
    print("─" * 40)
    idea_2 = "股价突破 20 日均线且成交量放大 1.5 倍"
    factor_2 = generate_factor(idea_2)
    print(f"\n生成结果：\n{factor_2}")
    
    # 测试 3：情绪面因子
    print("\n" + "─" * 40)
    print("测试 3：情绪面因子")
    print("─" * 40)
    idea_3 = "最近一周新闻情绪为正面的股票"
    factor_3 = generate_factor(idea_3)
    print(f"\n生成结果：\n{factor_3}")
    
    # 测试 4：LangGraph 节点格式
    print("\n" + "─" * 40)
    print("测试 4：LangGraph 节点接口")
    print("─" * 40)
    test_state = {
        "factor_idea": "高股息率的防御型股票",
        "factor": None,
        "factor_code": "",
        "factor_valid": False
    }
    updated_state = gen_factor_node(test_state)
    print(f"\n状态更新结果：")
    print(f"  factor_code: {updated_state['factor_code']}")
    print(f"  factor_valid: {updated_state['factor_valid']}")
    
    print("\n" + "=" * 60)
    print("✅ 因子生成节点测试完成")
    print("=" * 60)