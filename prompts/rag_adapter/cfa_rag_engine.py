# rag_adapter/cfa_rag_engine.py
# rag_adapter/cfa_rag_engine.py
"""
CFA智能体 - RAG适配层（DeepSeek + FAISS + bge-small-zh-v1.5）
功能：连接CFA向量库，实现检索增强生成。
依赖：pip install langchain langchain-community faiss-cpu sentence-transformers openai
"""
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
# 使用FAISS向量库
from langchain_community.vectorstores import FAISS
# 使用新版HuggingFace嵌入
from langchain_community.embeddings import HuggingFaceEmbeddings
from config.cfa_global_constraints import CFAGlobalConstraints

# ---------- DeepSeek 大模型配置 ----------
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
LLM_MODEL = "deepseek-chat"

# ---------- 本地嵌入模型配置 ----------
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

class CFARAGEngine:
    def __init__(self, persist_dir="./faiss_index", k=10):
        # 1. 加载本地嵌入模型
        print(f"正在加载嵌入模型: {EMBEDDING_MODEL_NAME} ...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )

        # 2. 加载本地FAISS向量库（确认路径下有 index.faiss 和 index.pkl）
        print(f"正在加载FAISS向量库: {persist_dir}")
        self.vectorstore = FAISS.load_local(
            persist_dir,
            self.embeddings,
            allow_dangerous_deserialization=True  # 信任本地文件
        )
        self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": k})

        # 3. 加载全局约束
        self.constraints = CFAGlobalConstraints()
        self.system_prompt = self.constraints.get_full_system_prompt()
        self.k = k
        print("✅ RAG 引擎初始化完成。")

    def format_context(self, docs):
        """格式化检索到的文档，添加来源标注"""
        if not docs:
            return "（CFA知识库中未检索到相关内容）"
        parts = []
        for i, doc in enumerate(docs, 1):
            src = doc.metadata.get('source', '未知')
            ch = doc.metadata.get('chapter', '未知')
            parts.append(f"[参考{i}] 来源:{src} | 章节:{ch}\n{doc.page_content}")
        return "\n\n".join(parts)

    def ask(self, question: str) -> dict:
        # 1. 检索
        docs = self.retriever.invoke(question)
        context = self.format_context(docs)

        # 2. 构建消息
        user_message = f"""
【检索到的CFA知识库内容】
{context}

【用户问题】
{question}

请严格依据上述检索内容回答，不要使用外部知识。
"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]

        # 3. 调用DeepSeek
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0
        )
        answer = response.choices[0].message.content

        # 4. 合规检查
        check = self.constraints.validate_response(answer)

        return {
            "question": question,
            "answer": answer,
            "sources": [d.metadata for d in docs],
            "validation": check
        }

# 测试
if __name__ == "__main__":
    # 请确保 FAISS 向量库目录存在，例如 "./cfa_knowledge_base"
    engine = CFARAGEngine(persist_dir="./faiss_index", k=10)
    res = engine.ask("什么是sunk costS？")
    print("回答：", res["answer"][:1000])
    print("来源数：", len(res["sources"]))
    print("合规：", res["validation"])