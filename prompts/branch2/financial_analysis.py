# branch_2_research/financial_analysis.py
"""
CFA智能体 - 分支2：CFA专业投研分析系统（财务深度分析）
功能：对上市公司进行基于CFA财报分析框架的深度分析
依赖：需先完成 Day2 的 RAG引擎（FAISS + 嵌入模型）
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

class FinancialAnalysisAgent:
    """CFA财务分析智能体"""
    
    def __init__(self, rag_engine: CFARAGEngine):
        self.rag = rag_engine
        self.constraints = CFAGlobalConstraints()
        
        # ---- 财务深度分析提示词模板 ----
        self.analysis_template = """
【任务】CFA框架下的上市公司财务深度分析

你将作为CFA持证分析师，严格遵循以下六步标准流程，对目标公司进行深度剖析。  
所有分析必须基于【用户提供的财务数据】和【检索到的CFA知识库内容】。若数据不足，需明确指出“信息缺失”，并解释缺失对分析的影响。

【分析六步法】
### 步骤1：盈利质量评估
- 判断盈余的可持续性（剔除非经常性损益的影响）
- 分析经营现金流与净利润的匹配度
- 识别可能的会计政策选择或盈余管理迹象

### 步骤2：杜邦分析（ROE分解）
- 使用公式：$ROE = \text{{净利润率}} \times \text{{资产周转率}} \times \text{{权益乘数}}$
- 逐项计算并解释，与行业平均水平或历史趋势对比
- 指出ROE变化的主要驱动因素

### 步骤3：财务比率全景分析
- 盈利能力（如毛利率、净利率、ROA）
- 流动性（流动比率、速动比率）
- 偿债能力（资产负债率、利息保障倍数）
- 运营效率（存货周转率、应收账款周转率）
- 每个比率需给出：公式、计算结果、行业基准（如已知）、解读

### 步骤4：财务预测（简化）
- 基于历史增长率、管理层指引、行业前景，预测未来1-3年的关键指标（收入、EBITDA、净利润）
- 说明预测假设及依据

### 步骤5：风险识别
- 财务风险：杠杆水平、再融资压力、汇率敞口
- 经营风险：竞争地位、客户集中度、技术变迁
- 宏观风险：利率、监管、地缘政治

### 步骤6：综合结论
- 公司整体财务健康度评分（1-10分）
- 列出三项核心优势和三项主要风险
- 提出需要进一步深入调查的问题

【检索到的CFA知识库内容（分析框架参考）】
{context}

【用户提供的目标公司信息】
{company_data}

【分析要求】
- 每个步骤必须有明确输出，不可跳过
- 所有结论必须引用数据或CFA框架
- 请使用LaTeX格式呈现公式
【检索到的CFA知识库内容（含目标公司实际数据）】
{context}

【强制规则】
- 所有财务比率、金额、年份等具体数字必须来自上述检索内容，不得编造。
- 如果检索内容中有贵州茅台2025年数据，直接引用到报告对应部分。
- 报告末尾必须声明：“此为CFA框架下的教育性财务分析，不构成投资建议”

请按以下格式输出：
---
# {company_name} - CFA财务深度分析报告

## 一、盈利质量评估
（详细分析）

## 二、杜邦分析
### ROE分解
- 净利润率 = ...  
- 资产周转率 = ...  
- 权益乘数 = ...  
- ROE = ...  
（附对比分析）

## 三、财务比率全景
| 类别 | 比率名称 | 公式 | 计算结果 | 行业基准 | 解读 |
|------|---------|------|---------|---------|------|
| 盈利能力 | ... | ... | ... | ... | ... |
| ... | ... | ... | ... | ... | ... |

## 四、财务预测
（表格形式列出未来3年预测及关键假设）

## 五、风险识别
### 财务风险
### 经营风险
### 宏观风险

## 六、综合结论
- 财务健康度评分：X/10
- 核心优势：1. ... 2. ... 3. ...
- 主要风险：1. ... 2. ... 3. ...
- 待深入分析的问题：...

## 附录：本报告使用的CFA框架与LOS参考
- ...
"""

    def analyze(self, company_name: str, company_data: str = "") -> dict:
        """
        执行财务深度分析
        
        Args:
            company_name: 公司名称（用于报告标题）
            company_data: 用户提供的财务数据（可包含利润表、资产负债表摘要等）
                         如果为空，系统将仅依赖知识库中的范例生成教学式报告。
        
        Returns:
            dict: 包含完整分析报告的字典
        """
        print(f"📊 开始CFA财务分析：{company_name}")
        
        # 1. 检索CFA分析框架相关内容（确保模型使用正确的方法论）
        search_query = "CFA 财务分析框架 盈利质量 杜邦分析 2025 年报 财务数据"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        # 2. 构建提示词
        prompt = self.analysis_template.format(
            context=context,
            company_data=company_data if company_data else f"公司名称：{company_name}（用户未提供具体财务数据，请生成一份教学示范报告，使用通用假设数据，并标注为教学演示）",
            company_name=company_name
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        # 3. 调用大模型
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0,  # 确保严谨
            max_tokens=3000    # 财务报告较长，需放宽token限制
        )
        
        report = response.choices[0].message.content
        
        # 4. 合规检查
        validation = self.constraints.validate_response(report)
        
        return {
            "company": company_name,
            "report": report,
            "validation": validation,
            "sources_count": len(docs)
        }


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("CFA财务深度分析系统测试")
    print("=" * 60)
    
    # 初始化RAG引擎
    rag = CFARAGEngine(
        persist_dir="/Users/stonewjb/fin_agent_projects/faiss_index",
        k=5
    )
    
    agent = FinancialAnalysisAgent(rag)
    
    # 测试：无实际数据时生成教学示范报告
    print("\n【测试：生成南玻A财务分析报告】")
    result = agent.analyze(
        company_name="南玻A",
        company_data=""  # 留空，让系统生成示范
    )
    
    print("\n报告内容（前5000字）：")
    print(result["report"][:5000])
    print(f"\n... (总字数约 {len(result['report'])})")
    print(f"引用来源数：{result['sources_count']}")
    print(f"合规检查：{result['validation']}")
    
    print("\n✅ Day5 财务深度分析系统测试完成")