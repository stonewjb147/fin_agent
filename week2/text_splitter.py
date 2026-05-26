# 导入之前用到的加载器和分块器
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

# 加载 PDF
pdf_path = "/Users/stonewjb/fin_agent_projects/data/maotai_2025.pdf"
print("正在加载 PDF...")
loader = PyPDFLoader(pdf_path)
pages = loader.load()
print(f"加载完成，共 {len(pages)} 页")

# 创建文本分块器
# chunk_size=500 表示每个文本块最多 500 个字符
# chunk_overlap=50 表示相邻两块之间有 50 个字符的重叠，防止一句话被截断
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # 每块最大字符数
    chunk_overlap=50,    # 块与块之间的重叠字符数
    separators=["\n\n", "\n", "。", "，", " ", ""]  # 优先按段落、换行、句号切割
)

# 对所有页面内容进行分块
# split_documents 返回一个列表，每个元素是一个 Document 对象
print("正在分块...")
chunks = text_splitter.split_documents(pages)
print(f"分块完成，共 {len(chunks)} 个文本块")

# 打印前三个块的内容和长度，验证分块效果
for i, chunk in enumerate(chunks[:3]):
    print(f"\n--- 第 {i+1} 块（长度：{len(chunk.page_content)} 字符） ---")
    print(chunk.page_content[:200])  # 只打印前 200 字符预览
    print("...")