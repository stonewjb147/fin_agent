# branch_1_study/cfa_study_system.py
"""
CFA智能体 - 分支1：CFA学习答疑系统
功能：知识点精准问答、章节考点总结
对应脑图：分支1：CFA学习答疑系统（核心诉求1）
依赖：需先完成 Day1 和 Day2 的模块
"""
import yaml
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from rag_adapter.cfa_rag_engine import CFARAGEngine
from config.cfa_global_constraints import CFAGlobalConstraints

# DeepSeek客户端（与Day2保持一致）
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
LLM_MODEL = "deepseek-chat"

class CFAStudySystem:
    """CFA学习答疑智能体"""
    
    def __init__(self, rag_engine: CFARAGEngine):
        """
        初始化学习答疑系统
        
        Args:
            rag_engine: 第2天构建的RAG引擎实例（已含FAISS和约束）
        """
        self.rag = rag_engine
        self.constraints = CFAGlobalConstraints()
        
        # ============================================================
        # 知识点精准问答提示词模板
        # ============================================================
        # 加载独立的 YML 提示词文件
        yml_path = os.path.join(os.path.dirname(__file__), 'prompt', 'cfa_study_system.yml')
        with open(yml_path, 'r', encoding='utf-8') as f:
            prompt_templates = yaml.safe_load(f)
        print(f"Loaded YAML content: {prompt_templates}")  # 调试行
        # 从加载的数据中获取模板
        self.qa_prompt_template = prompt_templates['knowledge_qa']
        self.summary_prompt_template = prompt_templates['chapter_summary']
    def knowledge_qa(self, question: str) -> dict:
        """
        知识点精准问答
        
        Args:
            question: CFA知识点问题，如 "什么是WACC？"
            
        Returns:
            dict: 包含回答、来源、合规检查的字典
        """
        print(f"📚 知识点问答：{question}")
        
        # 1. 检索相关CFA内容（利用已有的RAG引擎）
        docs = self.rag.retriever.invoke(question)
        context = self.rag.format_context(docs)
        
        # 2. 构建完整提示词
        full_prompt = self.qa_prompt_template.format(
            context=context,
            question=question
        )
        
        # 3. 组装消息（系统约束 + 任务提示）
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": full_prompt}
        ]
        
        # 4. 调用DeepSeek生成回答
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0  # 确定性输出
        )
        answer = response.choices[0].message.content
        
        # 5. 合规检查
        validation = self.constraints.validate_response(answer)
        
        return {
            "question": question,
            "answer": answer,
            "sources": [doc.metadata for doc in docs],
            "validation": validation
        }
    
    def chapter_summary(self, chapter_name: str) -> dict:
        """
        章节考点总结
        
        Args:
            chapter_name: 章节名称，如 "权益估值模型" 或 "Reading 30"
            
        Returns:
            dict: 包含章节总结的字典
        """
        print(f"📖 章节总结：{chapter_name}")
        
        # 1. 构造检索查询（针对章节内容优化关键词）
        search_query = f"CFA {chapter_name} 章节 考点 重点 难点 LOS"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        # 2. 构建提示词
        full_prompt = self.summary_prompt_template.format(
            context=context,
            chapter_request=f"请总结CFA课程中关于「{chapter_name}」的章节考点",
            chapter_name=chapter_name
        )
        
        # 3. 组装消息并生成
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": full_prompt}
        ]
        
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0
        )
        summary = response.choices[0].message.content
        
        return {
            "chapter": chapter_name,
            "summary": summary,
            "sources": [doc.metadata for doc in docs]
        }


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("CFA学习答疑系统 - 功能测试")
    print("=" * 60)
    
    # 初始化RAG引擎（确保FAISS向量库路径正确）
    rag_engine = CFARAGEngine(
        persist_dir="/Users/stonewjb/fin_agent_projects/faiss_index",
        k=5
    )
    
    # 创建学习答疑智能体
    study_system = CFAStudySystem(rag_engine)
    
    # 测试1：知识点精准问答
    print("\n【测试1：知识点精准问答】")
    result = study_system.knowledge_qa("什么是WACC？如何计算？")
    print(f"\n回答（前1000字）：\n{result['answer'][:5000]}...")
    print(f"\n合规检查：{result['validation']}")
    print(f"引用来源数：{len(result['sources'])}")
    
    # 测试2：章节考点总结
    print("\n【测试2：章节考点总结】")
    result = study_system.chapter_summary("权益估值模型")
    print(f"\n总结（前500字）：\n{result['summary'][:5000]}...")
    print(f"引用来源数：{len(result['sources'])}")
    
    print("\n✅ Day3 学习答疑系统测试完成")