# ============================================
# 飞书机器人智能体
# 功能：接收用户消息，通过 LangChain Agent 自动选择工具回复
# 可用工具：汇率查询、金融信号查询
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

# 导入我们的工具函数
from agent_tools import query_exchange_rate, query_financial_signals

# 导入 LangChain 核心组件
from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain.memory import ConversationBufferMemory

print("=" * 50)
print("🤖 飞书机器人智能体初始化")
print("=" * 50)

# ============================================
# 第 1 步：创建 DeepSeek 模型实例
# ============================================

print("\n正在连接 DeepSeek 模型...")

# 导入 Langfuse 回调处理器
from langfuse.callback import CallbackHandler

# 创建 Langfuse 回调处理器
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# 创建 DeepSeek 模型，绑定 Langfuse 回调
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]  # 关键：绑定 Langfuse 监控
)
# ============================================
# 第 2 步：定义工具列表
# ============================================
def query_exchange_rate(query: str) -> str:
    """
    解析用户输入的汇率查询，返回实时汇率（示例数据）
    """
    import re

    # 1. 尝试解析“人民币兑美元”、“美元兑人民币”等
    match = re.search(r'(人民币|CNY|美元|USD|欧元|EUR|日元|JPY|英镑|GBP)\s*(兑|对|/)\s*(人民币|CNY|美元|USD|欧元|EUR|日元|JPY|英镑|GBP)', query)
    
    if match:
        from_curr = match.group(1)
        to_curr = match.group(3)
        # 这里你可以调用真正的汇率 API
        return f"1 {from_curr} ≈ 7.25 {to_curr}（示例数据，请接入真实 API）"
    else:
        return "无法识别货币对，请使用如'人民币兑美元'的格式"

# 工具1：汇率查询
# 把我们的函数包装成 LangChain Tool
exchange_rate_tool = Tool(
    name="汇率查询",                              # 工具名称
    func=query_exchange_rate,                    # 实际执行的函数
    description=(                                # 工具描述（智能体据此判断何时调用）
        "查询两种货币之间的实时汇率。"
        "输入格式：'基础货币代码 目标货币代码'，例如 'CNY USD' 或 'USD CNY'。"
        "支持的货币代码：CNY（人民币）、USD（美元）、EUR（欧元）、JPY（日元）、GBP（英镑）等。"
        "当用户询问汇率、换算、货币兑换等问题时，必须使用此工具。"
    )
)

# 工具2：金融信号查询
# 这个工具的参数比较复杂，我们用字符串拆分的方式处理
def signal_query_wrapper(query_str: str) -> str:
    """
    信号查询的包装函数，方便 LangChain Tool 调用
    
    参数格式：
        "全部" → 查询所有信号
        "看多" → 查询所有看多信号
        "白酒" → 查询白酒相关信号
        "白酒 看多" → 查询白酒看多信号
    """
    # 解析输入字符串
    parts = query_str.strip().split()
    
    asset = ""      # 资产/板块
    direction = ""  # 方向
    
    for part in parts:
        if part in ["看多", "看空", "中性"]:
            direction = part
        else:
            asset = part
    
    return query_financial_signals(asset=asset, direction=direction, limit=5)

signal_tool = Tool(
    name="金融信号查询",
    func=signal_query_wrapper,
    description=(
        "查询最新的金融投资信号。"
        "输入格式：直接输入要查询的板块名称或信号方向。"
        "例如：输入'白酒'查询白酒板块信号，输入'看多'查询所有看多信号，输入'白酒 看多'查询白酒看多信号，输入'全部'查询所有信号。"
        "当用户询问投资机会、板块走势、市场信号、最新动态等问题时，必须使用此工具。"
    )
)

# 可用工具列表
tools = [exchange_rate_tool, signal_tool]

print(f"已加载 {len(tools)} 个工具：")
for tool in tools:
    print(f"  🔧 {tool.name}")

# ============================================
# 第 3 步：定义智能体提示词
# ============================================

react_template = """你是一个专业的金融智能助手，通过飞书为用户提供服务。

【可用工具】
{tools}

【工具名称】
{tool_names}

【回答格式】
格式一（需要使用工具时）：
Thought: 我需要使用工具来回答这个问题
Action: 工具名称
Action Input: 传给工具的输入参数
Observation: 工具返回的结果
Thought: 根据工具返回的结果，我现在可以回答了
Final Answer: 基于工具结果的最终回复（用中文，简洁友好）


格式二（不需要使用工具时，如打招呼、闲聊）：
Thought: 这是闲聊，直接回答即可
Final Answer: 友好的回复

【重要规则】

1. 用户打招呼或闲聊时，使用格式二，友好回复
2. 用户询问汇率、货币兑换时，使用"汇率查询"工具，输入格式为"CNY USD"
3. 用户询问投资信号、市场动态、板块走势时，使用"金融信号查询"工具
4. 回复要简洁，用中文，可以适当使用 emoji 让消息更生动
5. 不要编造数据，所有数据必须来自工具返回结果
特别规则：
工具名称：query_exchange_rate
描述：查询两种货币之间的汇率
参数：from_currency（源货币，如 'CNY'）, to_currency（目标货币，如 'USD'）
调用示例：query_exchange_rate(from_currency='CNY', to_currency='USD')


【对话历史】
{chat_history}

【用户问题】
{input}

{agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)

print("提示词模板创建完成")

# ============================================
# 第 4 步：创建对话记忆
# ============================================

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# ============================================
# 第 5 步：创建智能体
# ============================================

agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=False,               # 非调试模式，不打印思考过程
    handle_parsing_errors=True,  # 格式错误自动修复
    max_iterations=5             # 最多思考 5 轮
)

print("智能体创建完成")

# ============================================
# 第 6 步：处理消息的函数
# ============================================

def process_message(user_message: str) -> str:
    """
    处理用户消息，返回智能体的回复
    
    参数：
        user_message: 用户在飞书中发送的文本
    
    返回：
        智能体的回复文本
    """
    try:
        result = agent_executor.invoke({"input": user_message})
        return result.get("output", "抱歉，我暂时无法处理这条消息")
    except Exception as e:
        return f"⚠️ 处理消息时出错：{str(e)[:50]}"


# ============================================
# 第 7 步：交互式测试
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("💬 智能体交互测试（输入 quit 退出）")
    print("=" * 50)
    print()
    print("你可以尝试以下问题：")
    print("  - 美元兑人民币汇率是多少？")
    print("  - 查询一下白酒板块的最新信号")
    print("  - 有什么看多的机会？")
    print("  - 你好")
    print()
    
    while True:
        try:
            user_input = input("💬 你：").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["quit", "exit", "退出"]:
                print("👋 再见！")
                break
            
            # 处理消息
            reply = process_message(user_input)
            print(f"🤖 助手：{reply}")
            print()
            
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break