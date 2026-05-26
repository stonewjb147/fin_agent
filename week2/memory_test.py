# ============================================
# 多轮记忆测试脚本
# 功能：验证智能体是否能记住对话上下文
# 场景：连续提问，测试记忆是否保持
# ============================================

# 导入所有必要的库
from dotenv import load_dotenv
import os

# 加载 .env 中的 API 密钥
load_dotenv()

# 导入向量数据库
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

# 导入智能体核心组件
from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain.memory import ConversationBufferMemory

print("=" * 60)
print("多轮记忆测试")
print("=" * 60)

# --- 加载嵌入模型和向量索引 ---
print("\n正在加载向量索引...")
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
print("向量索引加载完成")

# --- 检索函数 ---
def search_annual_report(query: str) -> str:
    """在茅台2025年年报中检索相关信息"""
    docs = vectorstore.similarity_search(query, k=3)
    if not docs:
        return "年报中没有找到相关信息。"
    results = []
    for i, doc in enumerate(docs, 1):
        results.append(f"[来源{i}] {doc.page_content}")
    return "\n\n".join(results)

# --- 创建检索工具 ---
retrieval_tool = Tool(
    name="年报检索",
    func=search_annual_report,
    description="当用户询问贵州茅台2025年年报中的具体财务数据、营收、利润、业务情况时，必须使用此工具。输入应该是一个搜索关键词或完整问题。"
)

# --- 连接大模型 ---
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY")
)

# --- 提示词模板（和多轮记忆相关的部分已包含 chat_history） ---
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

格式二（不需要使用工具时，如打招呼、闲聊）：
Thought: 这是一个简单的打招呼/闲聊问题，不需要查询年报，我直接回答即可
Final Answer: 你的回复内容

【重要规则】
1. 用户打招呼时使用格式二，不要调用任何工具
2. 用户询问年报中的具体数据时，使用格式一，必须调用"年报检索"工具
3. 如果用户追问"刚才说的"、"那个"、"它的"等指代之前内容的词，请结合【对话历史】理解用户指的是什么
4. 所有财务数据必须来自检索结果，不能编造
5. 回答简洁专业，用中文

【对话历史】
{chat_history}

【用户问题】
{input}

{agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)

# --- 创建共享记忆（关键：多个问题共用同一个 memory 对象） ---
# 这个 memory 对象会保留在一轮对话中的所有问答
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# --- 创建智能体 ---
agent = create_react_agent(
    llm=llm,
    tools=[retrieval_tool],
    prompt=prompt
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=[retrieval_tool],
    memory=memory,          # 共享记忆，实现多轮对话
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=5
)

# ============================================
# 开始多轮记忆测试
# ============================================
print("\n" + "=" * 60)
print("场景：连续多轮对话，测试记忆是否保持")
print("=" * 60)

# 第一轮：问一个具体数据
question_1 = "贵州茅台2025年的净利润是多少？"
print(f"\n{'─' * 60}")
print(f"【第 1 轮】{question_1}")
print(f"{'─' * 60}\n")
result_1 = agent_executor.invoke({"input": question_1})
print(f"\n✅ 答案：{result_1['output']}")

# 第二轮：用代词追问，不重复"净利润"三个字
# 如果记忆有效，智能体应该知道"它"指的是净利润
question_2 = "它同比增长了多少？"
print(f"\n{'─' * 60}")
print(f"【第 2 轮】{question_2}")
print(f"注意：问题中用了代词\"它\"，智能体需要从历史中理解\"它\"指的是净利润")
print(f"{'─' * 60}\n")
result_2 = agent_executor.invoke({"input": question_2})
print(f"\n✅ 答案：{result_2['output']}")

# 第三轮：继续追问，不重复任何之前的关键词
question_3 = "这个增长率比前一年高还是低？"
print(f"\n{'─' * 60}")
print(f"【第 3 轮】{question_3}")
print(f"注意：智能体需要记住前两轮在讨论净利润增长率")
print(f"{'─' * 60}\n")
result_3 = agent_executor.invoke({"input": question_3})
print(f"\n✅ 答案：{result_3['output']}")

# 第四轮：跳转到新话题，测试记忆是否会被混淆
question_4 = "那公司的营业收入是多少？"
print(f"\n{'─' * 60}")
print(f"【第 4 轮】{question_4}")
print(f"注意：切换到营业收入话题，但\"那\"字承上")
print(f"{'─' * 60}\n")
result_4 = agent_executor.invoke({"input": question_4})
print(f"\n✅ 答案：{result_4['output']}")

# 第五轮：清空记忆，重新开始（验证记忆清空功能）
print(f"\n{'─' * 60}")
print(f"【第 5 轮】清空对话记忆，重新开始")
print(f"{'─' * 60}\n")
memory.clear()  # 清空记忆
question_5 = "你能帮我查一下分红情况吗？"
result_5 = agent_executor.invoke({"input": question_5})
print(f"\n✅ 答案：{result_5['output']}")

print("\n" + "=" * 60)
print("多轮记忆测试完成！")
print("=" * 60)

# ============================================
# 测试总结
# ============================================
print("""
📊 验证要点：
1. 第 1 轮应该正常返回净利润数据
2. 第 2 轮应该能理解"它"指的是净利润，并给出增长率
3. 第 3 轮应该能基于前两轮的增长率数据做对比
4. 第 4 轮应该正确切换到营业收入话题
5. 第 5 轮清空记忆后，不应该再引用之前的对话内容

如果以上 5 点都满足，说明多轮记忆功能正常！
""")