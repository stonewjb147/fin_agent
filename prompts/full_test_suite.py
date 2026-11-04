# main.py
"""
CFA智能体 - 统一入口
功能：聚合所有子模块，提供智能路由和会话接口
"""
import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.cfa_global_constraints import CFAGlobalConstraints
from rag_adapter.cfa_rag_engine import CFARAGEngine
from branch1.cfa_study_system import CFAStudySystem
from branch1.error_and_case import AdvancedStudySystem
from branch2.finacial_analysis import FinancialAnalysisAgent
from branch2.valuation_engine import ValuationAgent
from branch2.quant_models import QuantitativeAgent
from safety_layer.correction_system import CorrectionSystem

class CFAAssistant:
    """CFA智能体统一入口"""
    
    def __init__(self, persist_dir: str = "/Users/stonewjb/fin_agent_projects/faiss_index"):
        # 1. 初始化基座
        self.constraints = CFAGlobalConstraints()
        self.rag = CFARAGEngine(persist_dir=persist_dir, k=10)
        
        # 2. 初始化所有子模块
        self.study = CFAStudySystem(self.rag)
        self.advanced_study = AdvancedStudySystem(self.rag)
        self.financial = FinancialAnalysisAgent(self.rag)
        self.valuation = ValuationAgent(self.rag)
        self.quant = QuantitativeAgent(self.rag)
        
        # 3. 初始化纠错
        self.corrector = CorrectionSystem()
        
        # 4. 会话历史（简易实现）
        self.history = []
        
        print("✅ CFA智能体初始化完成，所有模块就绪。")
    
    def route(self, query: str) -> dict:
        """根据用户意图路由到对应模块"""
        q_lower = query.lower()
        
        if any(kw in q_lower for kw in ["估值", "定价", "目标价", "dcf", "市盈率"]):
            module = "valuation"
            result = self.valuation.valuation_report(
                asset_name=query[:20],
                asset_info=query
            )
            raw_answer = result.get("report", "")
        elif any(kw in q_lower for kw in ["财务分析", "财报", "杜邦", "盈利质量"]):
            module = "financial"
            result = self.financial.analyze(
                company_name=query[:20],
                company_data=query
            )
            raw_answer = result.get("report", "")
        elif any(kw in q_lower for kw in ["回归", "组合", "优化", "有效前沿", "因子模型"]):
            module = "quant"
            if "组合" in q_lower or "优化" in q_lower or "有效前沿" in q_lower:
                result = self.quant.portfolio_optimization(query)
            else:
                result = self.quant.statistical_analysis(
                    model_name=query[:30],
                    user_request=query
                )
            raw_answer = result.get("report", "")
        elif any(kw in q_lower for kw in ["易错", "案例", "避坑", "章节总结"]):
            module = "advanced_study"
            if "易错" in q_lower:
                result = self.advanced_study.error_analysis(query)
                raw_answer = result.get("analysis", "")
            elif "案例" in q_lower:
                result = self.advanced_study.dual_case(query)
                raw_answer = result.get("cases", "")
            else:
                result = self.study.chapter_summary(query)
                raw_answer = result.get("summary", "")
        else:
            # 默认知识点问答
            module = "study_qa"
            result = self.study.knowledge_qa(query)
            raw_answer = result.get("answer", "")
        
        # 纠错流水线（传入空检索列表，实际可改进）
        corrected = self.corrector.full_pipeline(raw_answer, [])
        final_answer = corrected["final_output"]
        
        # 合规检查
        validation = self.constraints.validate_response(final_answer)
        
        # 记录会话历史
        self.history.append({
            "query": query,
            "module": module,
            "answer": final_answer[:200],
            "validation": validation
        })
        
        return {
            "query": query,
            "module_used": module,
            "answer": final_answer,
            "validation": validation,
            "corrections": corrected["total_corrections"]
        }
    
    def chat(self):
        """命令行交互模式"""
        print("=" * 60)
        print("CFA智能体 - 命令行交互")
        print("输入 'exit' 退出，输入 'history' 查看会话历史")
        print("=" * 60)
        while True:
            try:
                user_input = input("\n🧑 您：")
                if user_input.lower() == "exit":
                    break
                if user_input.lower() == "history":
                    for i, h in enumerate(self.history):
                        print(f"{i+1}. [{h['module']}] {h['query'][:30]}... -> {h['answer'][:50]}...")
                    continue
                response = self.route(user_input)
                print(f"\n🤖 CFA助手（使用模块：{response['module_used']}）：")
                print(response["answer"])
                print(f"\n[合规检查: {response['validation']}] [纠错动作: {response['corrections']}次]")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"⚠️ 出现错误：{e}")

if __name__ == "__main__":
    assistant = CFAAssistant()
    assistant.chat()