# ============================================
# 朴素 RAG 问答脚本
# 功能：接收用户问题，检索相关文档，交给 DeepSeek 生成答案
# ============================================

# 导入向量数据库加载工具
from langchain_community.vectorstores import FAISS

# 导入嵌入模型
from langchain_community.embeddings import HuggingFaceEmbeddings

# 导入 DeepSeek 聊天模型
from langchain_deepseek import ChatDeepSeek

# 导入 RAG 链
from langchain.chains import RetrievalQA

# 导入 Prompt 模板（用于告诉模型如何回答）
from langchain.prompts import PromptTemplate

# 导入环境变量读取工具
from dotenv import load_dotenv
import os

# 加载 .env 中的 API 密钥
load_dotenv()

print("=" * 50)
print("步骤1：加载本地向量索引")
print("=" * 50)

# 加载嵌入模型（必须和构建索引时用的是同一个模型）
model_name = "BAAI/bge-small-zh-v1.5"
embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

# 从本地加载 FAISS 索引
index_dir = "../faiss_index"  #这个目录下没有faiss_index
print(f"正在从 {index_dir} 加载索引...")
vectorstore = FAISS.load_local(
    folder_path=index_dir,
    embeddings=embeddings,
    allow_dangerous_deserialization=True  # 允许加载本地文件（仅限自己创建的安全文件）
)
print("索引加载完成")

# 把向量存储转为检索器
# k=4 表示每次返回最相关的 4 个文本块
retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
print("检索器已就绪，每次返回 4 个相关文本块")

print("\n" + "=" * 50)
print("步骤2：创建 DeepSeek 大模型实例")
print("=" * 50)

# 创建 DeepSeek 聊天模型
# temperature=0 表示让模型给出最确定的答案，减少随机性
llm = ChatDeepSeek(
    model="deepseek-chat",   # DeepSeek 的聊天模型
    temperature=0,           # 温度参数，0 是最确定
    api_key=os.getenv("DEEPSEEK_API_KEY")  # 从 .env 读取密钥
)
print("DeepSeek 模型已连接")

print("\n" + "=" * 50)
print("步骤3：创建 RAG 问答链")
print("=" * 50)

# 定义提示词模板
# {context} 会被自动替换为检索到的文档内容
# {question} 会被替换为用户的问题
template = """你是一个专业的金融分析师，请根据以下年报内容回答问题。

如果年报内容中没有相关信息，请直接说"根据提供的年报内容，无法找到相关信息"，不要编造答案。

年报内容：
{context}

问题：{question}

专业回答："""

# 创建 Prompt 模板
QA_PROMPT = PromptTemplate(
    template=template,
    input_variables=["context", "question"]
)

# 创建 RetrievalQA 链
# chain_type="stuff" 表示把检索到的文档拼接在一起，一次性发给模型
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,                              # 大模型
    chain_type="stuff",                   # 链类型
    retriever=retriever,                  # 检索器
    chain_type_kwargs={"prompt": QA_PROMPT},  # 使用我们定义的提示词
    return_source_documents=True          # 让链返回引用的源文档
)
print("RAG 问答链创建完成")

print("\n" + "=" * 50)
print("步骤4：测试问答")
print("=" * 50)

# 测试问题列表
test_questions = [
    "贵州茅台2025年的净利润是多少？",
    "公司2025年的营业收入同比增长了多少？",
    "茅台2025年的分红方案是什么？"
]

# 逐个提问并打印结果
for i, question in enumerate(test_questions, 1):
    print(f"\n{'─' * 50}")
    print(f"问题 {i}：{question}")
    print(f"{'─' * 50}")
    
    # 调用 RAG 链获取答案
    result = qa_chain.invoke({"query": question})
    
    # 打印答案
    print(f"答案：{result['result']}")
    
    # 打印引用的源文档（可选，便于验证答案来源）
    print(f"\n引用来源（共 {len(result['source_documents'])} 个文档块）：")
    for j, doc in enumerate(result['source_documents'], 1):
        print(f"  来源 {j}（前80字）：{doc.page_content[:80]}...")

print("\n全部测试完成！")