# 导入 PDF 加载器，LangChain 已经封装好了 PyPDF
from langchain_community.document_loaders import PyPDFLoader

# 导入文本分块器，用于把长文档切成小块
from langchain.text_splitter import RecursiveCharacterTextSplitter

# 第一步：指定 PDF 文件路径
# .. 表示上一级目录，因为脚本在 week2/ 里，PDF 在 data/ 里
pdf_path = "/Users/stonewjb/fin_agent_projects/data/maotai_2025.pdf"

# 第二步：创建 PDF 加载器实例
print("正在加载 PDF 文件...")
loader = PyPDFLoader(pdf_path)

# 第三步：调用 load() 方法，返回一个列表，每个元素是一页的内容
pages = loader.load()

# 打印加载了多少页
print(f"成功加载 {len(pages)} 页")

# 第四步：打印第一页的前 200 个字符，看看内容是否正确
print("\n第一页内容预览（前200字）：")
print(pages[0].page_content[:200])