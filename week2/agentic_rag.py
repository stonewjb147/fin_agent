# ============================================
# Agentic RAG 脚本 —— ReAct 智能体
# 功能：智能体可以自主决定是否需要检索年报内容
# 如果问题是闲聊（如"你好"），直接回答，不检索
# 如果问题需要年报数据（如"净利润"），自动检索后回答
# ============================================

# --- 导入基础依赖 ---
from dotenv import load_dotenv  # 读取 .env 文件中的环境变量
import os                       # 操作系统路径相关

# 加载环境变量（DeepSeek API 密钥）
load_dotenv()

# --- 导入向量数据库相关 ---
from langchain_community.vectorstores import FAISS           # FAISS 向量数据库
from langchain_community.embeddings import HuggingFaceEmbeddings  # 嵌入模型

# --- 导入 LangChain 智能体核心组件 ---
from langchain.agents import create_react_agent, AgentExecutor  # 创建 ReAct 智能体
from langchain.tools import Tool                                # 工具定义
from langchain.prompts import PromptTemplate                    # 提示词模板
from langchain_deepseek import ChatDeepSeek                     # DeepSeek 大模型
from langchain.memory import ConversationBufferMemory           # 对话记忆（多轮）

print("=" * 60)
print("Agentic RAG 智能体初始化")
print("=" * 60)

# ============================================
# 第一步：加载嵌入模型和 FAISS 索引
# ============================================
print("\n[1/5] 正在加载嵌入模型...")

# 使用和之前完全相同的模型
model_name = "BAAI/bge-small-zh-v1.5"
embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)
print("嵌入模型加载完成")

# 加载本地 FAISS 索引
print("[2/5] 正在加载向量索引...")
index_dir = "../faiss_index"
vectorstore = FAISS.load_local(
    folder_path=index_dir,
    embeddings=embeddings,
    allow_dangerous_deserialization=True  # 允许加载本地文件
)
print("向量索引加载完成")

# ============================================
# 第二步：创建检索工具
# ============================================
print("[3/5] 正在创建检索工具...")

def search_annual_report(query: str) -> str:
    """
    在茅台年报中检索相关信息。
    这个函数会被智能体自动调用。
    
    参数:
        query: 用户的问题或搜索关键词
    
    返回:
        检索到的相关文本内容（拼接成一个字符串）
    """
    # 使用 FAISS 进行相似度搜索，返回最相关的 3 个文本块
    docs = vectorstore.similarity_search(query, k=3)
    
    # 如果没有找到相关内容
    if not docs:
        return "年报中没有找到相关信息。"
    
    # 把检索到的所有文本块拼接起来，用换行分隔
    results = []
    for i, doc in enumerate(docs, 1):
        results.append(f"[来源{i}] {doc.page_content}")
    
    # 用两个换行连接所有结果
    return "\n\n".join(results)

# 将检索函数包装成 LangChain 工具
# Tool 是智能体可以调用的"能力单元"
retrieval_tool = Tool(
    name="年报检索",                          # 工具名称（智能体会看到）
    func=search_annual_report,               # 工具对应的函数
    description="当用户询问贵州茅台2025年年报中的具体数据时（如财务数据、营收、利润、业务情况等），必须使用此工具进行检索。输入应该是一个搜索关键词或完整问题。"  # 工具描述（帮助智能体判断何时调用）
)
print("检索工具创建完成")

# ============================================
# 第三步：创建 DeepSeek 大模型
# ============================================
print("[4/5] 正在连接 DeepSeek 模型...")

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,  # 温度 0，让回答更准确、稳定
    api_key=os.getenv("DEEPSEEK_API_KEY")
)
print("DeepSeek 模型连接成功")

# ============================================
# 第四步：定义智能体的提示词模板
# ============================================

# 这是 ReAct 智能体的核心提示词
# 它告诉智能体如何思考、何时使用工具、如何回答
# 注意：ReAct 格式要求必须包含这些特定的变量
react_template = """你是一个专业的金融分析师助手，专门分析贵州茅台年报，请务必使用年报检索工具。

你可以使用以下工具：
{tools}

工具名称：{tool_names}

请必须严格按照以下格式思考和行动：

Question: 用户的问题
Thought: 我应该思考如何回答这个问题。如果问题涉及年报中的具体数据，我需要使用年报检索工具，否则直接回答。
Action: 要使用的工具名称，必须是 [{tool_names}] 中的一个，不能是别的工具名称。
Action Input: 传给工具的输入（必须是简单直接的字符串，不能是复杂的句子或问题）
Observation: 工具返回的结果
...（Thought/Action/Action Input/Observation 可以重复多次）
Thought: 我现在知道最终答案了
Final Answer: 基于工具返回的信息给出的最终答案，用中文回答

重要规则：
1. 如果用户只是打招呼（如"你好"），直接用 Final Answer 回复，不需要使用工具
2. 如果用户问年报中的具体数据（如净利润、营收、增长率），必须使用"年报检索"工具
3. 如果用户问年报中没有的内容，诚实地说"年报中没有相关信息"
4. 不要编造数据，所有数据必须来自检索结果
5. 回答要专业、简洁

开始！

{chat_history}

Question: {input}
Thought: {agent_scratchpad}"""

# 创建提示词模板对象
prompt = PromptTemplate.from_template(react_template)

print("提示词模板创建完成")

# ============================================
# 第五步：添加对话记忆（支持多轮对话）
# ============================================

# ConversationBufferMemory 会记住对话历史
# memory_key="chat_history" 要和提示词中的 {chat_history} 对应
memory = ConversationBufferMemory(
    memory_key="chat_history",  # 记忆的键名
    return_messages=True        # 返回消息格式（而不是纯文本）
)
print("对话记忆初始化完成")

# ============================================
# 第六步：创建 ReAct 智能体
# ============================================
print("[5/5] 正在创建 ReAct 智能体...")

# 智能体可以使用的工具列表
# 这里只有一个工具，后续练习可以加更多
tools = [retrieval_tool]

# 创建 ReAct 智能体
agent = create_react_agent(
    llm=llm,              # 大模型
    tools=tools,          # 可用工具列表
    prompt=prompt         # 提示词模板
)

# 创建智能体执行器
# AgentExecutor 负责管理智能体的运行循环
agent_executor = AgentExecutor(
    agent=agent,                    # 智能体
    tools=tools,                    # 工具
    memory=memory,                  # 记忆
    verbose=True,                   # 打印详细执行过程（便于调试学习）
    handle_parsing_errors=True,     # 如果模型输出格式有误，自动修复
    max_iterations=5                # 最多思考 5 轮，防止无限循环
)
print("ReAct 智能体创建完成！")

# ============================================
# 第七步：测试智能体
# ============================================
print("\n" + "=" * 60)
print("开始测试 Agentic RAG 智能体")
print("=" * 60)

# 测试问题列表
# 问题 1 和 2 需要检索，问题 3 是闲聊不需要检索
test_questions = [
    "贵州茅台2025年的净利润是多少亿元？",
    "茅台2025年的营业收入增长情况如何？",
    "你好，请问你能帮我做什么？"
]

# 逐个测试
for i, question in enumerate(test_questions, 1):
    print(f"\n{'─' * 60}")
    print(f"【测试问题 {i}】{question}")
    print(f"{'─' * 60}\n")
    
    # 调用智能体
    result = agent_executor.invoke({"input": question})
    
    print(f"\n【最终答案】{result['output']}")
    print(f"{'─' * 60}\n")

print("=" * 60)
print("全部测试完成！")
print("=" * 60)