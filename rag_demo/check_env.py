# check_env.py
import sys
print("Python路径:", sys.executable)
print("Python版本:", sys.version)

try:
    from langchain_openai import ChatOpenAI
    print("✅ langchain_openai")
except Exception as e:
    print("❌ langchain_openai", e)

try:
    from langchain_community.document_loaders import PyPDFLoader
    print("✅ langchain_community")
except Exception as e:
    print("❌ langchain_community", e)

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    print("✅ langchain.text_splitter")
except Exception as e:
    print("❌ langchain.text_splitter", e)

try:
    import faiss
    print("✅ faiss", faiss.__version__)
except Exception as e:
    print("❌ faiss", e)

try:
    import torch
    print("✅ torch", torch.__version__)
except Exception as e:
    print("❌ torch", e)

try:
    from sentence_transformers import SentenceTransformer
    print("✅ sentence_transformers")
except Exception as e:
    print("❌ sentence_transformers", e)

try:
    import pypdf
    print("✅ pypdf")
except Exception as e:
    print("❌ pypdf", e)

print("环境检查完成")