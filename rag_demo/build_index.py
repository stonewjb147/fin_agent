import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter  # 修正这里
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# 1. 设置离线模式（关键！防止它再去联网）
os.environ["HF_HUB_OFFLINE"] = "1"

# 2. 加载 PDF（请确保这个路径下有PDF文件）
pdf_path = "/Users/stonewjb/fin_agent_projects/rag_demo/maotai_2025.pdf"  # 换成你的实际文件名
if not os.path.exists(pdf_path):
    print(f"错误：找不到文件 {pdf_path}")
    exit(1)

print("正在加载 PDF...")
loader = PyPDFLoader(pdf_path)
docs = loader.load()

# 3. 切分文本
print("正在切分文本...")
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    length_function=len,
)
splits = text_splitter.split_documents(docs)

# 4. 加载本地模型（指向你手动下载的模型文件夹）
model_path = "/Users/stonewjb/fin_agent_projects/rag_demo/models/bge-small-zh"
if not os.path.exists(model_path):
    print(f"错误：找不到模型文件夹 {model_path}")
    print("请先手动下载模型并放置到正确位置。")
    exit(1)

print("正在加载本地模型...")
embeddings = HuggingFaceEmbeddings(
    model_name=model_path,
    model_kwargs={'device': 'cpu'}  # Intel Mac 只能用 CPU
)

# 5. 构建向量库
print("正在构建向量库（这可能需要几分钟，风扇可能会转）...")
vectorstore = FAISS.from_documents(splits, embeddings)

# 6. 保存
vectorstore.save_local("faiss_index")
print("✅ 成功！向量库已保存在 faiss_index 文件夹里。")
