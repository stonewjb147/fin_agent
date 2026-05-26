# ============================================
# Agentic RAG 交互式问答脚本
# 功能：在终端中持续对话，输入 quit 退出
# ============================================

from dotenv import load_dotenv
import os
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain.memory import ConversationBufferMemory

# 加载环境变量
load_dotenv()

# 加载嵌入模型和索引
print("正在初始化智能体...")
model_name = "BAAI/bge-small-zh-v1.5"
embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)
vectorstore = FAISS.load_local(
    folder_path="../faiss_index",
    embeddings=embeddings,
    allow_dangerous_deserialization=True
)

# 检索函数
def search_annual_report(query: str) -> str:
    docs = vectorstore.similarity_search(query, k=3)
    if not docs:
        return "年报中没有找到相关信息。"
    results = []
    for i, doc in enumerate(docs, 1):
        results.append(f"[来源{i}] {doc.page_content}")
    return "\n\n".join(results)

# 工具
retrieval_tool = Tool(
    name="年报检索",
    func=search_annual_report,
    description="当用户询问贵州茅台2022年年报中的具体数据时使用"
)

# 大模型
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY")
)

# 提示词
react_template = """你是一个专业的金融分析师助手，专门分析贵州茅台2022年年报。

你可以使用以下工具：
{tools}

工具名称：{tool_names}

请严格按照以下格式思考和行动：
Question: 用户的问题
Thought: 思考是否需要使用工具
Action: 工具名称（如果需要）
Action Input: 搜索关键词
Observation: 工具返回结果
Thought: 根据结果组织答案
Final Answer: 最终答案（中文）

{chat_history}

Question: {input}
Thought: {agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)

# 记忆
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# 智能体
agent = create_react_agent(llm=llm, tools=[retrieval_tool], prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=[retrieval_tool],
    memory=memory,
    verbose=False,  # 交互模式关掉详细日志，界面更干净
    handle_parsing_errors=True,
    max_iterations=5
)

print("智能体初始化完成！输入你的问题，输入 'quit' 退出。\n")

# 交互循环
while True:
    user_input = input("💬 你：")
    if user_input.lower() in ['quit', 'exit', '退出']:
        print("👋 再见！")
        break
    
    result = agent_executor.invoke({"input": user_input})
    print(f"🤖 助手：{result['output']}\n")