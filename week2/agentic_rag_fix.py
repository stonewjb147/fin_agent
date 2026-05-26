# ============================================
# Agentic RAG 脚本 —— ReAct 智能体（修正版）
# 修复：闲聊问题直接 Final Answer，无需 Action
# ============================================

from dotenv import load_dotenv
import os

load_dotenv()

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain.memory import ConversationBufferMemory

print("=" * 60)
print("Agentic RAG 智能体初始化（修正版）")
print("=" * 60)

# ============================================
# 第一步：加载嵌入模型和 FAISS 索引
# ============================================
print("\n[1/4] 正在加载嵌入模型和向量索引...")

model_name = "BAAI/bge-small-zh-v1.5"
embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

index_dir = "../faiss_index"
vectorstore = FAISS.load_local(
    folder_path=index_dir,
    embeddings=embeddings,
    allow_dangerous_deserialization=True
)
print("嵌入模型和向量索引加载完成")

# ============================================
# 第二步：创建检索工具
# ============================================
print("[2/4] 正在创建检索工具...")

def search_annual_report(query: str) -> str:
    """在茅台年报中检索相关信息"""
    docs = vectorstore.similarity_search(query, k=3)
    if not docs:
        return "年报中没有找到相关信息。"
    results = []
    for i, doc in enumerate(docs, 1):
        results.append(f"[来源{i}] {doc.page_content}")
    return "\n\n".join(results)

retrieval_tool = Tool(
    name="年报检索",
    func=search_annual_report,
    description="当用户询问贵州茅台2025年年报中的具体财务数据、营收、利润、业务情况时，必须使用此工具。输入应该是一个搜索关键词或完整问题。"
)
print("检索工具创建完成")

# ============================================
# 第三步：创建 DeepSeek 大模型
# ============================================
print("[3/4] 正在连接 DeepSeek 模型...")

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY")
)
print("DeepSeek 模型连接成功")

# ============================================
# 第四步：修正后的提示词模板（关键修改）
# ============================================
print("[4/4] 正在创建 ReAct 智能体...")

# 修正要点：
# 1. 明确区分"需要工具"和"不需要工具"的处理方式
# 2. 不需要工具时，Thought 后直接接 Final Answer
# 3. 使用更清晰的格式说明

react_template = """你是一个专业的金融分析师助手，专门分析贵州茅台2025年年报。

【可用工具】
{tools}

【工具名称】
{tool_names}

【回答格式】
请严格按照以下两种格式之一来回答：

格式一（需要使用工具时）：
Thought: 我需要查询年报数据才能回答这个问题
Action: 年报检索
Action Input: 搜索关键词
Observation: 工具返回的结果
Thought: 根据检索结果，我现在可以回答问题了
Final Answer: 基于检索结果的最终答案

格式二（不需要使用工具时，如打招呼、闲聊、询问你的能力）：
Thought: 这是一个简单的打招呼/闲聊问题，不需要查询年报，我直接回答即可
Final Answer: 你的回复内容

【重要规则】
1. 用户打招呼（如"你好"）或询问你的能力时，使用格式二，不要调用任何工具
2. 用户询问年报中的具体数据（如净利润、营收、增长率）时，使用格式一，必须调用"年报检索"工具
3. 所有财务数据必须来自检索结果，不能编造
4. 如果检索结果中没有用户要的数据，在 Final Answer 中诚实说明
5. 回答简洁专业，用中文

【对话历史】
{chat_history}

【用户问题】
{input}

{agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)
print("提示词模板创建完成（已修正）")

# ============================================
# 第五步：创建记忆和智能体
# ============================================

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

agent = create_react_agent(
    llm=llm,
    tools=[retrieval_tool],
    prompt=prompt
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=[retrieval_tool],
    memory=memory,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=10
)
print("ReAct 智能体创建完成！")

# ============================================
# 第六步：测试智能体
# ============================================
print("\n" + "=" * 60)
print("开始测试 Agentic RAG 智能体")
print("=" * 60)

# 测试问题：1 闲聊、2 和 3 需要检索、4 测试上下文记忆
test_questions = [
    "你好，请问你能帮我做什么？",
    "贵州茅台2025年的净利润是多少亿元？",
    "茅台2025年的营业收入增长情况如何？",
    "刚才说的净利润具体数字是多少？"
]

for i, question in enumerate(test_questions, 1):
    print(f"\n{'─' * 60}")
    print(f"【测试问题 {i}】{question}")
    print(f"{'─' * 60}\n")
    
    result = agent_executor.invoke({"input": question})
    
    print(f"\n【最终答案】{result['output']}")
    print(f"{'─' * 60}\n")

print("=" * 60)
print("全部测试完成！")
print("=" * 60)

# 交互循环
while True:
    user_input = input("💬 你：")
    if user_input.lower() in ['quit', 'exit', '退出']:
        print("👋 再见！")
        break
    
    result = agent_executor.invoke({"input": user_input})
    print(f"🤖 助手：{result['output']}\n")