# ============================================
# 嵌入向量生成与 FAISS 索引存储脚本
# 功能：把 PDF 文本块转为向量，保存为本地索引文件
# ============================================

# 导入文本加载和分块工具
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

# 导入 HuggingFace 的嵌入模型（轻量级中文模型，仅 100MB）
from langchain_community.embeddings import HuggingFaceEmbeddings

# 导入 FAISS 向量数据库
from langchain_community.vectorstores import FAISS

import os  # 用于路径操作

print("=" * 50)
print("步骤1：加载 PDF 并分块")
print("=" * 50)

# 指定 PDF 文件路径
pdf_path = "/Users/stonewjb/fin_agent_projects/data/maotai_2025.pdf"

# 加载 PDF
loader = PyPDFLoader(pdf_path)
pages = loader.load()
print(f"已加载 {len(pages)} 页")

# 分块
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,       # 每块 500 个字符
    chunk_overlap=50,     # 块之间重叠 50 个字符
    separators=["\n\n", "\n", "。", "，", " ", ""]
)
chunks = text_splitter.split_documents(pages)
print(f"已切分为 {len(chunks)} 个文本块")

print("\n" + "=" * 50)
print("步骤2：加载中文嵌入模型")
print("=" * 50)

# 使用 BAAI 的中文小模型，适合 8GB 内存的 Mac
# model_name 指定 HuggingFace 上的模型名称
# model_kwargs 里的 device='cpu' 强制使用 CPU 推理
model_name = "BAAI/bge-small-zh-v1.5"
print(f"正在加载模型：{model_name}")
print("（首次运行会下载约 100MB 的模型文件，请耐心等待）")

embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={'device': 'cpu'},           # 使用 CPU，不占用额外显存
    encode_kwargs={'normalize_embeddings': True}  # 向量归一化，提升检索质量
)
print("模型加载完成")

print("\n" + "=" * 50)
print("步骤3：生成向量并构建 FAISS 索引")
print("=" * 50)

# from_documents 方法会自动：
# 1. 把每个文本块用嵌入模型转成向量
# 2. 把所有向量放入 FAISS 索引
# 这一步在你的 8GB Mac 上大概需要 2-5 分钟
print(f"正在为 {len(chunks)} 个文本块生成向量...")
vectorstore = FAISS.from_documents(
    documents=chunks,
    embedding=embeddings
)
print("向量索引构建完成")

print("\n" + "=" * 50)
print("步骤4：保存向量索引到本地文件")
print("=" * 50)

# 创建索引存储目录
index_dir = "../faiss_index"
os.makedirs(index_dir, exist_ok=True)

# 保存 FAISS 索引到本地
# save_local 会生成两个文件：index.faiss 和 index.pkl
vectorstore.save_local(index_dir)
print(f"索引已保存到：{index_dir}/")
print(f"生成的文件：")
for f in os.listdir(index_dir):
    fpath = os.path.join(index_dir, f)
    size_kb = os.path.getsize(fpath) / 1024
    print(f"  - {f} ({size_kb:.1f} KB)")

print("\n" + "=" * 50)
print("步骤5：测试检索功能")
print("=" * 50)

# 做一个简单的相似度搜索测试
test_query = "2025年净利润"
print(f"测试查询：'{test_query}'")
results = vectorstore.similarity_search(test_query, k=3)

for i, doc in enumerate(results):
    print(f"\n--- 检索结果 {i+1} ---")
    print(doc.page_content[:200])
    print("...")

print("\n全部完成！")