# safety_layer/correction_system.py
"""
CFA智能体 - 兜底纠错体系
功能：知识点修正、模型误用拦截、非CFA观点过滤、不专业内容标准化
对应脑图：兜底纠错体系
"""
import re
from typing import List, Dict, Optional

class CorrectionSystem:
    """CFA输出纠错与合规增强系统"""
    
    def __init__(self):
        # 非CFA相关术语/观点黑名单（示例，可扩展）
        self.non_cfa_terms = [
            "波浪理论", "缠论", "江恩理论", "道氏理论", "头肩顶",
            "金叉", "死叉", "主力资金", "庄家", "内幕消息",
            "稳赚", "必涨", "翻倍", "一夜暴富"
        ]
        
        # CFA标准术语映射（不规范→规范）
        self.term_mapping = {
            "股本回报率": "净资产收益率(ROE)",
            "市盈": "市盈率(P/E)",
            "现金周转": "现金流转换周期",
            "借债成本": "债务资本成本(r_d)",
            "资金成本": "加权平均资本成本(WACC)",
            # 可继续添加
        }
        
    def correct_knowledge_errors(self, answer: str, retrieved_docs: List[str]) -> dict:
        """
        知识点错误自动修正
        对比检索到的原文，检查回答中的事实性错误，并尝试纠正。
        
        Args:
            answer: 原始回答
            retrieved_docs: 检索到的文档内容列表（用于比对）
        Returns:
            dict: 包含修正后文本和修正日志
        """
        corrections = []
        corrected_answer = answer
        
        # 简单策略：如果回答中有公式，检查是否与知识库中的标准公式一致
        for i, doc in enumerate(retrieved_docs):
            # 提取知识库中的公式（以 $...$ 包裹的内容）
            doc_formulas = re.findall(r'\$.*?\$', doc)
            answer_formulas = re.findall(r'\$.*?\$', answer)
            
            for af in answer_formulas:
                if af not in doc_formulas:
                    corrections.append({
                        "type": "formula_check",
                        "suspect_formula": af,
                        "matched_doc_index": i,
                        "action": "flagged_for_review"
                    })
        
        if corrections:
            corrected_answer += "\n\n[纠错提示] 以下内容可能与CFA知识库存在差异，请核实：\n"
            for c in corrections:
                corrected_answer += f"- 公式 {c['suspect_formula']} 未在检索文档中找到匹配项。\n"
        
        return {
            "original_answer": answer,
            "corrected_answer": corrected_answer,
            "corrections": corrections
        }
    
    def intercept_model_misuse(self, answer: str) -> dict:
        """
        模型误用场景拦截
        检查是否存在明显不适用于当前场景的模型使用。
        
        Args:
            answer: 原始回答
        Returns:
            dict: 包含拦截结果和建议
        """
        misuses = []
        
        # 检查CAPM被用于非上市公司估值
        if "CAPM" in answer and ("非上市" in answer or "未上市" in answer or "初创" in answer):
            misuses.append({
                "type": "capm_unlisted",
                "message": "CAPM通常不适用于非上市公司，因为贝塔无法可靠估计。建议使用扩展模型或情景分析。"
            })
            
        # 检查久期被用于非利率风险解释
        if "久期" in answer and ("信用风险" in answer or "违约" in answer):
            misuses.append({
                "type": "duration_misuse",
                "message": "久期主要衡量利率风险，不能直接用于评估信用风险。请区分使用。"
            })
            
        corrected_answer = answer
        if misuses:
            corrected_answer += "\n\n[模型适用性提醒]\n"
            for m in misuses:
                corrected_answer += f"⚠️ {m['message']}\n"
                
        return {
            "original_answer": answer,
            "corrected_answer": corrected_answer,
            "misuses_found": misuses
        }
    
    def filter_non_cfa_views(self, answer: str) -> dict:
        """
        非CFA野观点过滤
        检测并标记/删除非CFA体系的观点和术语。
        
        Args:
            answer: 原始回答
        Returns:
            dict: 包含过滤后文本和被标记内容
        """
        filtered_terms = []
        for term in self.non_cfa_terms:
            if term in answer:
                filtered_terms.append(term)
                
        corrected_answer = answer
        if filtered_terms:
            disclaimer = (
                "\n[内容提醒] 以下回答中包含非CFA标准体系的内容（如：{}），"
                "这些观点不代表CFA教材立场，仅供对比参考。\n"
            ).format(", ".join(filtered_terms))
            corrected_answer = disclaimer + corrected_answer
            
        return {
            "original_answer": answer,
            "corrected_answer": corrected_answer,
            "non_cfa_terms_found": filtered_terms
        }
    
    def standardize_output(self, answer: str) -> dict:
        """
        输出不专业内容标准化修正
        补全缺失的免责声明、统一术语表达。
        
        Args:
            answer: 原始回答
        Returns:
            dict: 包含标准化后文本
        """
        corrected = answer
        changes = []
        
        # 1. 检查是否缺少合规声明
        if "不构成投资建议" not in answer and "教育性分析" not in answer:
            corrected += "\n\n[合规声明] 此为CFA框架下的教育性分析，不构成投资建议。"
            changes.append("added_disclaimer")
            
        # 2. 术语标准化
        for informal, formal in self.term_mapping.items():
            if informal in corrected:
                corrected = corrected.replace(informal, formal)
                changes.append(f"replaced_{informal}_with_{formal}")
                
        return {
            "original_answer": answer,
            "corrected_answer": corrected,
            "changes": changes
        }
    
    def full_pipeline(self, answer: str, retrieved_docs: Optional[List[str]] = None) -> dict:
        """
        执行完整纠错流水线
        
        Args:
            answer: 原始LLM输出
            retrieved_docs: 检索到的原始知识库片段，用于知识校验
        Returns:
            dict: 包含最终输出和各步骤日志
        """
        if retrieved_docs is None:
            retrieved_docs = []
            
        # 依次执行四个模块
        step1 = self.correct_knowledge_errors(answer, retrieved_docs)
        step2 = self.intercept_model_misuse(step1['corrected_answer'])
        step3 = self.filter_non_cfa_views(step2['corrected_answer'])
        step4 = self.standardize_output(step3['corrected_answer'])
        
        return {
            "final_output": step4['corrected_answer'],
            "steps": {
                "knowledge_correction": step1,
                "misuse_interception": step2,
                "view_filtering": step3,
                "standardization": step4
            },
            "total_corrections": (
                len(step1['corrections']) + 
                len(step2['misuses_found']) + 
                len(step3['non_cfa_terms_found']) + 
                len(step4['changes'])
            )
        }


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("兜底纠错系统测试")
    print("=" * 60)
    
    cs = CorrectionSystem()
    
    # 模拟一段可能有问题的回答
    test_answer = """
    根据DCF估值，贵州茅台的合理股价应该在2500元左右。
    我们采用了CAPM模型，假设贝塔为1.2，无风险利率2.5%。
    同时，从波浪理论的角度看，股价目前处于第三浪主升浪，建议买入。
    该公司的股本回报率高达30%，借债成本较低。
    """
    
    # 模拟检索到的知识库片段（用于对比）
    mock_docs = [
        "CAPM模型公式：$E(R_i) = R_f + \\beta_i[E(R_m) - R_f]$，适用于上市公司的权益成本估计。",
        "DCF估值需要对未来现金流进行预测，并对终值做出合理假设。"
    ]
    
    # 执行完整纠错流水线
    result = cs.full_pipeline(test_answer, mock_docs)
    
    print("\n【原始回答】")
    print(test_answer[:300])
    
    print("\n【纠错后最终输出】")
    print(result['final_output'][:500])
    
    print("\n【纠错步骤详情】")
    print(f"- 知识点检查发现可疑项: {len(result['steps']['knowledge_correction']['corrections'])}")
    print(f"- 模型误用拦截: {result['steps']['misuse_interception']['misuses_found']}")
    print(f"- 非CFA术语过滤: {result['steps']['view_filtering']['non_cfa_terms_found']}")
    print(f"- 标准化修改: {result['steps']['standardization']['changes']}")
    print(f"- 总计修正动作: {result['total_corrections']}")
    
    print("\n✅ Day8 纠错系统测试完成")