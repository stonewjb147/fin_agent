# branch_2_research/quant_models.py
"""
CFA智能体 - 分支2：CFA统计模型 + 投资组合理论分析
功能：回归/时序/假设检验应用，投资组合构建与优化
依赖：Day2 RAG引擎
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

class QuantitativeAgent:
    """CFA定量分析与组合管理智能体"""
    
    def __init__(self, rag_engine: CFARAGEngine):
        self.rag = rag_engine
        self.constraints = CFAGlobalConstraints()
        
        # ---- 统计模型分析提示词 ----
        self.stats_template = """
【任务】CFA统计模型实操应用

请基于检索到的CFA知识库内容和用户提供的数据描述，进行统计模型分析。

【分析框架】
1. **模型选择理由**
   - 为什么选择该模型（如OLS回归、Logistic回归、ARIMA等）
2. **模型设定**
   - 数学表达式（用 $...$ 格式）
   - 变量定义与数据来源
3. **假设检验**
   - 模型必须满足的经典假设（如线性、无异方差、无自相关）
   - 检验方法（t检验、F检验、Durbin-Watson等）
4. **结果解读**
   - 系数估计与显著性
   - 模型拟合优度（R²、调整R²）
   - 经济意义与统计意义的区分
5. **局限性**
   - 数据频率、样本量、结构变化等限制
6. **应用场景**
   - 该模型在真实金融决策中的使用方式（如预测收益、风控）

【检索到的CFA知识库内容】
{context}

【用户请求】
{user_request}

请按以下格式输出：
---
# 统计模型分析：{model_name}

## 一、模型选择理由

## 二、模型设定
公式：$...$
变量说明：...

## 三、假设检验
| 假设 | 检验方法 | 结果 | 结论 |
|------|---------|------|------|
| ... | ... | ... | ... |

## 四、结果解读
- 系数表
- 拟合优度
- 经济含义

## 五、局限性

## 六、应用场景
"""

        # ---- 投资组合优化提示词 ----
        self.portfolio_template = """
【任务】CFA投资组合理论分析与优化

请基于检索到的CFA知识库内容和用户需求，进行投资组合构建与优化分析。

【分析步骤】
1. **资产池与输入参数**
   - 列出考虑的资产及其预期收益、标准差、相关系数矩阵
2. **有效前沿构建**
   - 使用马科维茨均值-方差优化
   - 描述最小方差组合、最大夏普比率组合
3. **约束条件**
   - 权重限制、卖空限制、行业集中度等
4. **优化结果**
   - 最优权重表
   - 组合预期收益与风险
5. **敏感性分析**
   - 输入参数微小变化对最优权重的影响
6. **模型局限性**
   - 估计误差敏感性、历史收益不代表未来等
7. **合规声明**

【检索到的CFA知识库内容】
{context}

【用户需求】
{user_request}

请按以下格式输出：
---
# 投资组合优化分析

## 一、资产池与输入参数
| 资产 | 预期收益 | 标准差 | 
|------|---------|--------|
| ... | ... | ... |
相关系数矩阵：...

## 二、有效前沿
- 最小方差组合：权重...，收益...，风险...
- 最大夏普比率组合：权重...，收益...，风险...
（可附有效前沿数据点表格）

## 三、约束条件

## 四、优化结果（推荐组合）
| 资产 | 权重 |
|------|------|
| ... | ... |

## 五、敏感性分析

## 六、模型局限性

## 七、合规声明
此为CFA框架下的教育性分析，不构成投资建议。
"""
    
    def statistical_analysis(self, model_name: str, user_request: str) -> dict:
        """统计模型分析"""
        print(f"📈 统计模型分析：{model_name}")
        
        search_query = f"CFA 统计模型 {model_name} 回归 假设检验 应用"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        prompt = self.stats_template.format(
            context=context,
            user_request=user_request,
            model_name=model_name
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=2000
        )
        
        report = response.choices[0].message.content
        validation = self.constraints.validate_response(report)
        
        return {
            "model": model_name,
            "report": report,
            "validation": validation,
            "sources": len(docs)
        }
    
    def portfolio_optimization(self, user_request: str) -> dict:
        """投资组合优化"""
        print(f"📊 投资组合优化分析")
        
        search_query = f"CFA 投资组合 马科维茨 有效前沿 Black-Litterman 风险预算"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        prompt = self.portfolio_template.format(
            context=context,
            user_request=user_request
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=2000
        )
        
        report = response.choices[0].message.content
        validation = self.constraints.validate_response(report)
        
        return {
            "report": report,
            "validation": validation,
            "sources": len(docs)
        }


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("量化分析与组合管理测试")
    print("=" * 60)
    
    rag = CFARAGEngine(
        persist_dir="/Users/stonewjb/fin_agent_projects/faiss_index",
        k=6
    )
    
    agent = QuantitativeAgent(rag)
    
    # 测试1：统计模型
    print("\n【测试1：Fama-French三因子模型回归分析】")
    res1 = agent.statistical_analysis(
        model_name="Fama-French三因子模型",
        user_request="请用贵州茅台2020-2025年月度收益数据，演示如何用Fama-French三因子模型进行回归，并解读结果。"
    )
    print(res1["report"][:500])
    print(f"合规：{res1['validation']}")
    
    # 测试2：投资组合优化
    print("\n【测试2：构建最小方差组合】")
    res2 = agent.portfolio_optimization(
        user_request="从沪深300中选取5只股票，假设预期收益和协方差矩阵，演示如何构建最小方差组合，并展示有效前沿。"
    )
    print(res2["report"][:-1])
    print(f"合规：{res2['validation']}")
    
    print("\n✅ Day7 量化模型与组合分析测试完成")