# ============================================
# Deep Agent - 多步推理智能体
# 功能：使用搜索 + 计算器 + 信号数据，自主规划多步骤任务
# 与之前 Agent 的区别：
#   1. 工具更强大（网络搜索 vs 单一检索）
#   2. 支持多步推理（先搜 A，再搜 B，然后对比）
#   3. 能自我纠错（发现搜索词不对，自动调整重新搜索）
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain.memory import ConversationBufferMemory

# 导入 Langfuse 回调
from langfuse.callback import CallbackHandler

# 导入我们刚创建的工具
from deep_tools import web_search, calculator, load_local_signals

# ============================================
# 第 1 步：创建 Langfuse 回调
# ============================================

langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# ============================================
# 第 2 步：创建 DeepSeek 模型
# ============================================

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# ============================================
# 第 3 步：包装工具为 LangChain Tool
# ============================================

tools = [
    Tool(
        name="网络搜索",
        func=web_search,
        description=(
            "在互联网上搜索最新信息。"
            "当需要查询实时数据、新闻、公司财报、宏观经济指标等不在本地知识库中的信息时，必须使用此工具。"
            "输入：搜索关键词或问题。"
            "例如：'贵州茅台 2025 年营收'、'五粮液最新股价'"
        )
    ),
    Tool(
        name="计算器",
        func=calculator,
        description=(
            "执行数学计算。"
            "当需要计算增长率、平均值、比例等数值时使用。"
            "输入：数学表达式。"
            "例如：'(800-650)/650*100'、'sqrt(16)'、'100*1.2/3'"
        )
    ),
    Tool(
        name="金融信号查询",
        func=load_local_signals,
        description=(
            "查询本地存储的最新金融信号数据。"
            "当需要了解当前市场对某板块的看法、信号方向（看多/看空）时使用。"
            "输入：资产或板块名称，为空则返回全部。"
            "例如：'白酒'、'新能源'"
        )
    ),
]

# ============================================
# 第 4 步：定义 Deep Agent 提示词
# ============================================

react_template = """你是一个专业的深度投研分析助手。你的任务是帮助用户完成复杂的金融分析。

【可用工具】
{tools}

【工具名称】
{tool_names}

【工作方法】
1. 先理解用户的问题，判断需要哪些信息
2. 制定分析计划：先搜索什么、再搜索什么、需要计算什么
3. 逐步执行：每次只调用一个工具，根据结果决定下一步
4. 如果搜索结果不理想，调整搜索词重新搜索
5. 最后汇总所有信息，给出专业的分析结论

【回答格式】
Thought: 我的分析计划是...现在需要先搜索...
Action: 网络搜索
Action Input: 搜索关键词
Observation: 工具返回的结果
Thought: 根据搜索结果，我还需要...然后计算...
Action: 计算器
Action Input: 数学表达式
Observation: 计算结果
Thought: 我已经收集了足够的信息，可以给出结论了
Final Answer: 专业的分析报告

【对话历史】
{chat_history}

【用户问题】
{input}

{agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)

# ============================================
# 第 5 步：创建 Agent
# ============================================

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True,               # 打印详细推理过程
    handle_parsing_errors=True,
    max_iterations=10 
   # early_stopping_method="generate"        # 最多 10 步推理
)

# ============================================23*89

# 第 6 步：交互式测试
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 Deep Agent - 深度投研分析助手")
    print("=" * 60)
    print()
    print("可用工具：")
    print("  🔍 网络搜索 - 搜索最新信息")
    print("  🧮 计算器 - 数学计算")
    print("  📊 金融信号查询 - 查看本地信号")
    print()
    print("示例问题：")
    print("  - 贵州茅台和五粮液谁的营收增长率更高？")
    print("  - 当前市场对白酒板块的看法如何？")
    print("  - 如果茅台营收增长20%，计算可能的新营收")
    print()
    
    while True:
        try:
            user_input = input("💬 你：").strip()
            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "退出"]:
                break
            
            result = agent_executor.invoke({"input": user_input})
            print(f"\n🤖 分析报告：\n{result['output']}\n")
            
        except KeyboardInterrupt:
            break