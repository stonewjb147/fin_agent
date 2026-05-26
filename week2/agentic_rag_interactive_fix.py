# ============================================
# Agentic RAG 交互式问答脚本（升级版）
# 功能：
#   - 持续对话，输入问题即可查询年报
#   - 支持命令：/help 帮助、/history 查看历史、/clear 清空记忆、/quit 退出
#   - 优雅的界面和错误处理
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.memory import ConversationBufferMemory
from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek

# ============================================
# 初始化智能体
# ============================================
print("🔄 正在初始化智能体...")
print()

# 加载嵌入模型和向量索引
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

# 检索函数
def search_annual_report(query: str) -> str:
    """在茅台2025年年报中检索相关信息"""
    docs = vectorstore.similarity_search(query, k=3)
    if not docs:
        return "年报中没有找到相关信息。"
    results_list = []
    for i, doc in enumerate(docs, 1):
        results_list.append(f"[来源{i}] {doc.page_content}")
    return "\n\n".join(results_list)

# 检索工具
retrieval_tool = Tool(
    name="年报检索",
    func=search_annual_report,
    description="当用户询问贵州茅台2025年年报中的具体财务数据、营收、利润、业务情况时，必须使用此工具。输入应该是一个搜索关键词或完整问题。"
)

# 大模型
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY")
)

# 提示词模板
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
3. 如果用户追问"刚才说的"、"那个"、"它的"等指代之前内容的词，请结合【对话历史】理解
4. 所有财务数据必须来自检索结果，不能编造
5. 如果检索结果中没有用户要的数据，诚实说明
6. 回答简洁专业，用中文，数字保留两位小数

【对话历史】
{chat_history}

【用户问题】
{input}

{agent_scratchpad}"""

prompt = PromptTemplate.from_template(react_template)

# 对话记忆
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# 创建智能体
agent = create_react_agent(llm=llm, tools=[retrieval_tool], prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=[retrieval_tool],
    memory=memory,
    verbose=False,
    handle_parsing_errors=True,
    max_iterations=5
)

print("✅ 智能体初始化完成！")
print()

# ============================================
# 帮助信息
# ============================================
def print_help():
    """打印帮助信息"""
    print("""
╔══════════════════════════════════════════════════════════╗
║           📊 茅台年报智能问答助手 - 使用说明              ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  直接输入问题即可查询贵州茅台2025年年报中的信息。          ║
║                                                          ║
║  支持的命令：                                             ║
║    /help      - 显示此帮助信息                            ║
║    /history   - 查看当前对话历史                          ║
║    /clear     - 清空对话记忆，开始新话题                   ║
║    /quit      - 退出程序                                  ║
║                                                          ║
║  示例问题：                                               ║
║    · 贵州茅台2025年的净利润是多少？                        ║
║    · 营业收入同比增长了多少？                              ║
║    · 公司的分红方案是什么？                                ║
║    · 前五大股东是谁？                                     ║
║                                                          ║
║  多轮对话：                                               ║
║    你可以连续提问，助手会记住上下文。                      ║
║    例如先问"净利润多少"，再问"它增长了多少"。              ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

def print_history():
    """打印对话历史"""
    history = memory.load_memory_variables({})
    messages = history.get("chat_history", [])
    if not messages:
        print("📝 当前没有对话历史。")
        return
    
    print("\n📝 对话历史：")
    print("-" * 50)
    for msg in messages:
        # msg 可能是 HumanMessage 或 AIMessage 对象
        msg_type = type(msg).__name__
        msg_content = msg.content if hasattr(msg, 'content') else str(msg)
        
        if "Human" in msg_type:
            print(f"💬 你：{msg_content}")
        elif "AI" in msg_type:
            print(f"🤖 助手：{msg_content}")
    print("-" * 50)
    print()

# ============================================
# 交互循环
# ============================================
print_help()

# 问题计数器
question_count = 0

while True:
    try:
        # 获取用户输入
        user_input = input("💬 你：").strip()
        
        # 处理空输入
        if not user_input:
            continue
        
        # 处理命令
        if user_input == "/quit":
            print("👋 再见！")
            break
        
        elif user_input == "/help":
            print_help()
            continue
        
        elif user_input == "/history":
            print_history()
            continue
        
        elif user_input == "/clear":
            memory.clear()
            print("🧹 对话记忆已清空，可以开始新话题。")
            print()
            continue
        
        # 正常问题：调用智能体
        question_count += 1
        print(f"🤔 正在分析（第 {question_count} 个问题）...")
        print()
        
        result = agent_executor.invoke({"input": user_input})
        answer = result['output']
        
        print(f"🤖 助手：{answer}")
        print()
        
    except KeyboardInterrupt:
        print("\n\n👋 检测到中断信号，再见！")
        break
    
    except Exception as e:
        # 如果智能体出错了，不要让程序崩溃
        print(f"⚠️ 出错了：{e}")
        print("   请尝试重新提问，或输入 /clear 清空记忆后重试。")
        print()

# ============================================
# 退出时显示统计
# ============================================
print()
print(f"📊 本次会话共回答了 {question_count} 个问题。")
print("感谢使用茅台年报智能问答助手！")