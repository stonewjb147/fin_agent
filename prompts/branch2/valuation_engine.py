# branch_2_research/valuation_engine.py
"""
CFA智能体 - 分支2：资产估值与定价分析引擎
功能：权益/固收/衍生品的绝对估值与相对估值分析
依赖：需先完成 Day2 的 RAG引擎（FAISS）
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

class ValuationAgent:
    """CFA估值分析智能体"""
    
    def __init__(self, rag_engine: CFARAGEngine):
        self.rag = rag_engine
        self.constraints = CFAGlobalConstraints()
        
        # ---- 估值分析提示词模板 ----
        self.valuation_template = """
【任务】CFA框架下的资产估值与定价分析

请根据检索到的CFA知识库内容和用户提供的资产信息，进行估值分析。  
严格遵循以下要求，确保分析的教育性和专业性。

【估值方法选择】
根据资产类型自动选择适当方法：
- 股票（权益）：优先使用 DCF（FCFF/FCFE）+ 相对估值（P/E、P/B 等）
- 债券（固收）：现金流折现、YTM 计算、利差分析
- 衍生品：Black-Scholes（期权）、持有成本模型（期货）、互换定价

【强制输出结构】
1. **估值对象与数据来源**
   - 明确资产名称、所用数据的时效性
2. **关键假设**
   - 列出所有重要假设（如：无风险利率、风险溢价、增长率、永续增长率等）
3. **绝对估值计算**（必须展示公式和分步计算）
   - 用 $...$ 格式呈现公式，并代入数值
4. **相对估值分析**（对于权益资产）
   - 选择可比公司，计算行业平均倍数，得出隐含估值区间
5. **敏感性分析**
   - 选取对估值影响最大的 2 个变量（如 WACC 和长期增长率），各变动 ±10%，展示估值变化表
6. **估值区间与结论**
   - 给出一个合理的估值范围（如每股 150-180 元），并说明主要不确定性
7. **模型局限性**
   - 说明所用模型在真实市场中的不足（如 DCF 对终值过于敏感、相对估值依赖市场情绪等）
8. **合规声明**
   - 必须包含“此为CFA框架下的教育性分析，不构成投资建议”

【检索到的CFA知识库内容（含目标资产数据）】
{context}

【用户提供的资产信息】
{asset_info}

请按以下格式输出：
---
# 估值分析报告：{asset_name}

## 一、估值对象与数据来源

## 二、关键假设
| 假设参数 | 取值 | 依据 |
|---------|------|------|
| ... | ... | ... |

## 三、绝对估值（DCF/DDM等）
### 模型公式
$...$
### 分步计算
...
### 结果

## 四、相对估值分析（如适用）
| 可比公司 | P/E | EV/EBITDA | ... |
|---------|-----|-----------|-----|
| ... | ... | ... | ... |
隐含估值范围：...

## 五、敏感性分析
| 变量变化 | -10% | 基准 | +10% |
|---------|------|------|------|
| WACC 变动下的估值 | ... | ... | ... |
| 增长率变动下的估值 | ... | ... | ... |

## 六、估值区间与结论
合理估值区间：...  
主要上行/下行风险：...

## 七、模型局限性
...

## 八、合规声明
此为CFA框架下的教育性分析，不构成投资建议。
"""

    def valuation_report(self, asset_name: str, asset_info: str = "") -> dict:
        """
        生成估值分析报告
        
        Args:
            asset_name: 资产名称（如"贵州茅台"）
            asset_info: 用户提供的额外信息（如关键财务数据、当前股价等）
        
        Returns:
            dict: 包含完整估值报告的字典
        """
        print(f"💹 开始估值分析：{asset_name}")
        
        # 1. 检索：获取 CFA 估值方法论 + 资产相关数据
        search_query = f"CFA 估值 DCF 相对估值 敏感性分析 {asset_name} 年报 财务"
        docs = self.rag.retriever.invoke(search_query)
        context = self.rag.format_context(docs)
        
        # 调试：输出检索到的片段数
        print(f"检索到 {len(docs)} 个相关文档片段")
        
        # 2. 构建提示词
        prompt = self.valuation_template.format(
            context=context,
            asset_info=asset_info if asset_info else f"资产名称：{asset_name}（请从检索内容中提取财务数据进行估值）",
            asset_name=asset_name
        )
        
        messages = [
            {"role": "system", "content": self.constraints.get_full_system_prompt()},
            {"role": "user", "content": prompt}
        ]
        
        # 3. 调用大模型
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=3000
        )
        
        report = response.choices[0].message.content
        
        # 4. 合规检查
        validation = self.constraints.validate_response(report)
        
        return {
            "asset": asset_name,
            "report": report,
            "validation": validation,
            "sources_count": len(docs)
        }


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("CFA估值分析引擎测试")
    print("=" * 60)
    
    # 初始化RAG（使用你的FAISS库）
    rag = CFARAGEngine(
        persist_dir="/Users/stonewjb/fin_agent_projects/faiss_index",
        k=10  # 估值需要更多数据，适当调大
    )
    
    agent = ValuationAgent(rag)
    
    # 测试：对茅台进行估值分析（假设库里有2025数据）
    print("\n【测试：贵州茅台估值分析】")
    result = agent.valuation_report(
        asset_name="南玻A",
        asset_info="请基于向量库中的2025年年报数据进行估值，无风险利率设为2.5%，市场风险溢价设为6%。"
    )
    
    print("\n报告内容（前800字）：")
    print(result["report"][:-1])
    print(f"\n引用来源数：{result['sources_count']}")
    print(f"合规检查：{result['validation']}")
    
    print("\n✅ Day6 估值引擎测试完成")