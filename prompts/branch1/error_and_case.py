# branch_1_study/error_and_case.py
"""
CFA智能体 - 分支1深化：易错点拆解 + 双案例拓展
功能：识别高频错误、生成应试案例和金融实务案例
依赖：需先完成 Day2 的 RAG引擎 和 Day3 的基础学习系统
"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from rag_adapter.cfa_rag_engine import CFARAGEngine
from config.cfa_global_constraints import CFAGlobalConstraints

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
LLM_MODEL = "deepseek-chat"

class AdvancedStudySystem:
    """CFA学习系统 - 高级功能"""
    
    def __init__(self, rag_engine: CFARAGEngine):
        self.rag = rag_engine
        self.constraints = CFAGlobalConstraints()
        
        # ---- 易错点拆解提示词模板 ----
        self.error_analysis_template = """
【任务】CFA易错点深度拆解

请根据检索到的CFA知识，对指定的知识点进行“考生最易犯错误”的拆解。

【分析框架 - 必须包含以下5部分】
1. **错误表象**：学生最常出现的具体错误（请给出典型错误答案示例）
2. **错误根源**：导致错误的核心原因（概念混淆？条件遗漏？计算跳步？）
3. **正确解法**：对比表格+正确计算步骤+关键条件判断逻辑
4. **记忆锚点**：一个忘不掉的口诀、类比或图像化记忆法
5. **变体练习**：一道检验是否真正掌握的改编题（附详解）

【检索到的CFA知识库内容】
{context}

【待分析知识点】
{knowledge_point}

请按以下格式输出：
---
# 易错点拆解：{knowledge_point}

## ❌ 常见错误（至少3个典型表现）
1. ...
2. ...
3. ...

## 🔍 错误根源分析
| 错误类型 | 具体表现 | 混淆来源/遗漏条件 |
|---------|---------|-----------------|
| ... | ... | ... |

## ✅ 正确理解
（对比式讲解 + 判断流程图文字描述）

## 🧠 记忆锚点
（口诀/类比/一句话总结）

## 📝 变体练习
### 题目
（设置1-2个易错陷阱）
### 解析与答案
（分步拆解）
"""
        
        # ---- 双案例生成提示词模板 ----
        self.dual_case_template = """
【任务】为CFA知识点生成双案例教学

【要求】
1. **应试案例**（Exam-Oriented）
   - 风格：仿CFA真题，包含已知条件、求解目标
   - 设置1-2个考生容易忽略的陷阱
   - 提供详细分步解析

2. **实务案例**（Real-World Application）
   - 风格：真实市场场景（如某上市公司、某次金融危机等）
   - 展示从原始信息→模型运用→决策判断的完整链条
   - **必须注明模型局限性**，并声明“此为教学案例，非真实投资建议”

【检索到的CFA知识库内容】
{context}

【知识点】
{knowledge_point}

请按以下格式输出：
---
# {knowledge_point} - 双案例教学

## 案例一：应试突破（CFA考试视角）
### 题干
### 已知条件
### 求解要求
### 🚨 陷阱提醒
### 分步详解
### 答案

## 案例二：实战应用（金融实务视角）
### 场景描述
### 原始数据/背景
### 分析过程（运用知识点）
### 结论与决策逻辑
### ⚠️ 模型局限与实务提醒

## 双案例关联总结
（两个案例如何帮助你全面掌握该知识点）
"""
    
    def error_analysis(self, knowledge_point: str) -> dict:
        """易错点拆解"""
        print(f"🔍 易错点分析：{knowledge_point}")
        
        # 检索相关内容和常见错误讨论
        search_query = f"{knowledge_point} 常见错误 易混淆 计算陷阱 注意事项"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        prompt = self.error_analysis_template.format(
            context=context,
            knowledge_point=knowledge_point
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0
        )
        
        answer = response.choices[0].message.content
        validation = self.constraints.validate_response(answer)
        
        return {
            "knowledge_point": knowledge_point,
            "analysis": answer,
            "validation": validation,
            "sources": [d.metadata for d in docs]
        }
    
    def dual_case(self, knowledge_point: str) -> dict:
        """双案例生成"""
        print(f"📚 生成双案例：{knowledge_point}")
        
        # 检索知识点内容和应用场景
        search_query = f"{knowledge_point} 计算 应用 案例分析 实务"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        prompt = self.dual_case_template.format(
            context=context,
            knowledge_point=knowledge_point
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0
        )
        
        answer = response.choices[0].message.content
        validation = self.constraints.validate_response(answer)
        
        return {
            "knowledge_point": knowledge_point,
            "cases": answer,
            "validation": validation,
            "sources": [d.metadata for d in docs]
        }


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("高级学习功能测试")
    print("=" * 60)
    
    # 初始化RAG引擎（使用你的实际FAISS路径）
    rag = CFARAGEngine(
        persist_dir="/Users/stonewjb/fin_agent_projects/faiss_index",
        k=5
    )
    
    advanced = AdvancedStudySystem(rag)
    
    # 测试1：易错点拆解
    print("\n【测试1：易错点拆解 - WACC计算】")
    res1 = advanced.error_analysis("WACC计算")
    print(res1["analysis"][:500])
    print(f"\n合规检查：{res1['validation']}")
    
    # 测试2：双案例生成
    print("\n【测试2：双案例 - 杜邦分析】")
    res2 = advanced.dual_case("杜邦分析")
    print(res2["cases"][:500])
    print(f"\n合规检查：{res2['validation']}")
    
    print("\n✅ Day4 高级学习功能测试完成")