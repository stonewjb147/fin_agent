from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh")
vectorstore = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)

# 打印前3个文档块的内容（前300字符）
for i, doc in enumerate(vectorstore.docstore._dict.values()):
    if i >= 3:
        break
    print(f"块{i+1}: {doc.page_content[:300]}\n")
