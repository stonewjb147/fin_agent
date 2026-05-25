from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

PDF_PATH = Path(__file__).resolve().parent.parent / "maotai_2025.PDF"

loader = PyPDFLoader(str(PDF_PATH))
documents = loader.load()

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
)
chunks = splitter.split_documents(documents)

print(chunks[0].page_content)
