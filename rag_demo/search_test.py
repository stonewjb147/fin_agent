from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh")
vectorstore = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)

query = "2025年净利润"
results = vectorstore.similarity_search(query, k=2)

for i, doc in enumerate(results):
    print(f"结果 {i+1}: {doc.page_content[:300]}\n")