# ============================================
# CFA 智能体 - 多版本提示词测试框架
# 适配：DeepSeek + HuggingFace Embeddings
# 向量库路径：./cfa_faiss_index（在 fin_agent_projects 下）
# ============================================

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载 .env（在 fin_agent_projects 根目录）
load_dotenv(dotenv_path=project_root / ".env")

# 导入 LangChain 组件
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI  # DeepSeek 使用 OpenAI 兼容接口

print("=" * 60)
print("📚 CFA 智能体 - 提示词测试框架")
print("=" * 60)

# ============================================
# 1. 加载向量库（FAISS）
# ============================================

# 向量库路径（在 fin_agent_projects 根目录下）
INDEX_DIR = project_root / "faiss_index"

print(f"\n📁 向量库路径: {INDEX_DIR}")

if not INDEX_DIR.exists():
    print(f"❌ 向量库不存在: {INDEX_DIR}")
    print("   请先运行 build_multi_pdf_index.py 构建向量库")
    exit(1)

# 加载嵌入模型（使用你已下载的模型）
print("\n🔧 加载嵌入模型: BAAI/bge-small-zh-v1.5")
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-zh-v1.5",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

# 加载 FAISS 向量库
vectorstore = FAISS.load_local(
    str(INDEX_DIR),
    embeddings,
    allow_dangerous_deserialization=True  # FAISS 反序列化需要
)

# 创建检索器
retriever = vectorstore.as_retriever(
    search_kwargs={"k": 5}
)

print(f"✅ 向量库加载完成，包含 {vectorstore.index.ntotal} 个文档块")

# ============================================
# 2. 初始化 DeepSeek 大模型
# ============================================

print("\n🔧 初始化 DeepSeek 模型...")

# 从环境变量读取 DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not DEEPSEEK_API_KEY:
    print("❌ 未找到 DEEPSEEK_API_KEY，请在 .env 中配置")
    exit(1)

# DeepSeek 使用 OpenAI 兼容接口
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.2,
    openai_api_key=DEEPSEEK_API_KEY,
    openai_api_base=DEEPSEEK_BASE_URL,
)

print(f"✅ DeepSeek 模型初始化完成 (API: {DEEPSEEK_BASE_URL})")

# ============================================
# 3. 定义 3 个版本的提示词
# ============================================

# 版本 1：基础版
prompt_v1 = ChatPromptTemplate.from_template(
    """根据以下CFA资料回答问题：

资料：
{context}

问题：{question}

请基于以上资料给出专业回答。"""
)

# 版本 2：CFA 持证人版
prompt_v2 = ChatPromptTemplate.from_template(
    """你是CFA持证人，请严格基于以下资料回答问题。

资料：
{context}

问题：{question}

要求：
1. 仅根据资料回答，若资料不足请说明
2. 请用中文回答
3. 请列出相关的CFA知识点编号（如：CFA Level 1 - Equity - Reading 28）"""
)

# 版本 3：CFA 讲师版（分步推理）
prompt_v3 = ChatPromptTemplate.from_template(
    """你是CFA讲师，请严格按以下步骤分析：

【步骤1】从资料中找出与问题最相关的 3 个知识点
【步骤2】逐一解释每个知识点
【步骤3】综合回答用户问题

重要：若资料未覆盖某点，必须声明"资料未覆盖此内容"。

资料：
{context}

问题：{question}"""
)

print("\n✅ 3 个提示词版本已加载")

# ============================================
# 4. 测试函数
# ============================================

def test_prompt(prompt, question, version_name):
    """测试单个提示词版本"""
    print(f"\n{'─' * 60}")
    print(f"📝 测试版本：{version_name}")
    print(f"❓ 问题：{question}")
    print(f"{'─' * 60}")
    
    # 1. 从向量库检索相关文档
    docs = retriever.invoke(question)
    
    # 2. 提取上下文
    context = "\n\n".join([d.page_content for d in docs])
    
    # 3. 构建消息
    messages = prompt.format_messages(
        context=context,
        question=question
    )
    
    # 4. 调用 DeepSeek
    response = llm.invoke(messages)
    
    return response.content, docs

# ============================================
# 5. 交互式运行
# ============================================

def main():
    """主函数 - 交互式测试"""
    
    print("\n" + "=" * 60)
    print("💡 使用说明")
    print("=" * 60)
    print("输入问题后，将自动用 3 个版本的提示词测试")
    print("输入 'exit' 退出")
    print("")
    
    # 存储所有提示词版本
    prompt_versions = [
        (prompt_v1, "版本1：基础版"),
        (prompt_v2, "版本2：CFA持证人版"),
        (prompt_v3, "版本3：CFA讲师版"),
    ]
    
    while True:
        try:
            question = input("\n❓ 请输入问题: ").strip()
            if not question:
                continue
            if question.lower() in ["exit", "quit", "退出"]:
                print("\n👋 再见！")
                break
            
            print("\n" + "=" * 60)
            print(f"📋 测试问题: {question}")
            print("=" * 60)
            
            results = []
            
            # 逐个测试
            for prompt, name in prompt_versions:
                try:
                    answer, docs = test_prompt(prompt, question, name)
                    results.append({
                        "version": name,
                        "answer": answer,
                        "doc_count": len(docs)
                    })
                    
                    # 显示回答
                    print(f"\n📖 回答：")
                    print(answer[:500] + ("..." if len(answer) > 500 else ""))
                    print(f"\n📚 检索到 {len(docs)} 个相关文档块")
                    
                except Exception as e:
                    print(f"❌ 测试失败：{e}")
            
            # 对比总结
            print("\n" + "=" * 60)
            print("📊 版本对比")
            print("=" * 60)
            for r in results:
                print(f"\n📌 {r['version']}")
                print(f"   - 使用文档数：{r['doc_count']}")
                print(f"   - 回答长度：{len(r['answer'])} 字符")
                print(f"   - 回答预览：{r['answer'][:80]}...")
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")

if __name__ == "__main__":
    main()