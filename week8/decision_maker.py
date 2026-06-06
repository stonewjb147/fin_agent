# ============================================
# 决策生成模块
# 功能：LLM 综合分析四路信号，生成具体的交易计划
# 输出格式：结构化的 JSON 交易指令列表
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json
from typing import List, Dict

# 导入 DeepSeek
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# 导入信号汇总模块
from signal_aggregator import aggregate_all_signals

# 导入交易意图模型
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
from trade_intent import TradeIntent, TradeIntentBuilder, TradeDirection, IntentSource

# ============================================
# 第 1 步：初始化 DeepSeek
# ============================================

langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.3,
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# ============================================
# 第 2 步：ETF 列表（供 LLM 参考）
# ============================================

ETF_UNIVERSE = """
可用 ETF 列表：
| 代码     | 名称        | 类型   | 参考价   |
|----------|------------|--------|---------|
| 510050   | 上证50ETF   | 宽基   | 2.85    |
| 510300   | 沪深300ETF  | 宽基   | 4.12    |
| 159915   | 创业板ETF   | 宽基   | 2.35    |
| 512880   | 证券ETF     | 行业   | 0.95    |
| 512690   | 酒ETF       | 行业   | 0.78    |
| 516160   | 新能源ETF   | 行业   | 0.68    |
| 512010   | 医药ETF     | 行业   | 0.52    |
| 511010   | 国债ETF     | 债券   | 101.50  |
"""

# ============================================
# 第 3 步：决策提示词模板
# ============================================

decision_template = """你是一位专业的 ETF 投资经理。请根据以下多源信号，制定今日的交易计划。

【可用 ETF】
{etf_universe}

【RAG 研报信号】
{rag_signals}

【新闻信号】
{news_signals}

【因子信号】
{factor_signals}

【辩论结论】
{debate_result}

【当前持仓】
{current_positions}

【可用现金】
{available_cash}

【账户总资产】
{total_assets}

【任务】
1. 综合分析以上四路信号，判断当前市场状况
2. 决定今日应该买入哪些 ETF、卖出哪些 ETF
3. 每笔交易需要给出明确的理由

【风险约束】
- 单笔交易金额不超过可用现金的 20%
- 单只 ETF 持仓不超过总资产的 30%
- 至少保留 10% 现金
- 优先考虑信号置信度高的方向

【输出格式】
请严格按照以下 JSON 格式输出交易计划：

{{
  "market_analysis": "对当前市场的综合分析（100字以内）",
  "trades": [
    {{
      "action": "买入 或 卖出",
      "symbol": "ETF代码",
      "quantity": 数量（整数）,
      "reason": "交易理由（引用具体信号来源）",
      "confidence": 0.0-1.0之间的置信度
    }}
  ]
}}

如果认为当前不适合交易，trades 数组可以为空。
只输出 JSON，不要添加任何其他内容。

JSON 输出："""

decision_prompt = PromptTemplate(
    template=decision_template,
    input_variables=[
        "etf_universe", "rag_signals", "news_signals",
        "factor_signals", "debate_result",
        "current_positions", "available_cash", "total_assets"
    ]
)

# ============================================
# 第 4 步：决策生成函数
# ============================================

def generate_trade_plan(
    rag_signals: str = "",
    news_signals: str = "",
    factor_signals: str = "",
    debate_result: str = "",
    current_positions: str = "空仓",
    available_cash: float = 500000,
    total_assets: float = 500000
) -> Dict:
    """
    综合四路信号，调用 LLM 生成交易计划

    参数：
        rag_signals: RAG 研报信号
        news_signals: 新闻信号
        factor_signals: 因子信号
        debate_result: 辩论结论
        current_positions: 当前持仓描述
        available_cash: 可用现金
        total_assets: 总资产

    返回：
        包含 market_analysis 和 trades 的字典
    """
    print("\n🧠 [决策生成] 正在分析四路信号...")
    print(f"   可用现金：{available_cash:,.2f}")
    print(f"   总资产：{total_assets:,.2f}")

    try:
        # 构建提示词
        prompt_input = decision_prompt.format(
            etf_universe=ETF_UNIVERSE,
            rag_signals=rag_signals or "无 RAG 信号",
            news_signals=news_signals or "无新闻信号",
            factor_signals=factor_signals or "无因子信号",
            debate_result=debate_result or "无辩论结论",
            current_positions=current_positions,
            available_cash=f"{available_cash:,.2f}",
            total_assets=f"{total_assets:,.2f}"
        )

        # 调用 LLM
        response = llm.invoke(prompt_input)
        response_text = response.content if hasattr(response, 'content') else str(response)

        # 清理 JSON
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        # 解析 JSON
        plan = json.loads(response_text)

        # 打印分析结果
        print(f"   市场分析：{plan.get('market_analysis', '')[:100]}...")
        print(f"   交易计划：{len(plan.get('trades', []))} 笔交易")

        for t in plan.get("trades", []):
            print(f"     - {t.get('action', '')} {t.get('symbol', '')} {t.get('quantity', 0)}股")
            print(f"       理由：{t.get('reason', '')[:80]}")

        return plan

    except json.JSONDecodeError as e:
        print(f"   ❌ JSON 解析失败：{e}")
        print(f"   LLM 原始输出：{response_text[:300]}...")
        return {
            "market_analysis": "决策生成失败，LLM 输出格式异常",
            "trades": []
        }
    except Exception as e:
        print(f"   ❌ 决策生成异常：{e}")
        return {
            "market_analysis": f"决策生成异常：{str(e)[:50]}",
            "trades": []
        }


# ============================================
# 第 5 步：交易计划转为 TradeIntent 列表
# ============================================

def plan_to_intents(plan: Dict) -> List[TradeIntent]:
    """
    将 LLM 生成的交易计划转为 TradeIntent 列表

    参数：
        plan: LLM 生成的交易计划字典

    返回：
        TradeIntent 对象列表
    """
    intents = []

    for trade in plan.get("trades", []):
        action = trade.get("action", "")
        symbol = trade.get("symbol", "")
        quantity = trade.get("quantity", 0)
        reason = trade.get("reason", "")
        confidence = trade.get("confidence", 0.7)

        if not symbol or quantity <= 0:
            continue

        # ETF 参考价
        etf_prices = {
            "510050": 2.85, "510300": 4.12, "159915": 2.35,
            "512880": 0.95, "512690": 0.78, "516160": 0.68,
            "512010": 0.52, "511010": 101.50
        }
        price = etf_prices.get(symbol, 1.0)

        # 构建 TradeIntent
        builder = TradeIntentBuilder() \
            .set_symbol(symbol) \
            .set_name(symbol) \
            .with_reason(reason)

        if action == "买入":
            builder.buy(quantity, price)
        elif action == "卖出":
            builder.sell(quantity, price)
        else:
            continue

        # 来源标记为综合决策
        intent = builder.build()
        intent.source = IntentSource.MANUAL  # 综合决策
        intent.confidence = confidence

        intents.append(intent)

    return intents


# ============================================
# 第 6 步：便捷函数——一站式决策
# ============================================

def make_decision(
    available_cash: float = 500000,
    total_assets: float = 500000,
    positions_text: str = "空仓"
) -> Dict:
    """
    一站式决策函数：收集信号 → 生成计划 → 转为交易意图

    参数：
        available_cash: 可用现金
        total_assets: 总资产
        positions_text: 持仓文本描述

    返回：
        包含 plan 和 intents 的字典
    """
    # 第一步：收集信号
    print("\n" + "=" * 50)
    print("📡 第一步：收集四路信号")
    print("=" * 50)
    signals = aggregate_all_signals()

    # 第二步：生成交易计划
    print("\n" + "=" * 50)
    print("🧠 第二步：LLM 生成交易计划")
    print("=" * 50)
    plan = generate_trade_plan(
        rag_signals=signals["rag"],
        news_signals=signals["news"],
        factor_signals=signals["factor"],
        debate_result=signals["debate"],
        current_positions=positions_text,
        available_cash=available_cash,
        total_assets=total_assets
    )

    # 第三步：转为 TradeIntent
    print("\n" + "=" * 50)
    print("📋 第三步：交易计划 → TradeIntent")
    print("=" * 50)
    intents = plan_to_intents(plan)
    print(f"   生成 {len(intents)} 个交易意图")

    return {
        "plan": plan,
        "intents": intents
    }


# ============================================
# 第 7 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 决策生成模块测试")
    print("=" * 60)

    # 测试一站式决策
    result = make_decision(
        available_cash=500000,
        total_assets=500000,
        positions_text="当前空仓，无持仓"
    )

    print("\n" + "=" * 60)
    print("📊 决策结果：")
    print("=" * 60)
    print(f"市场分析：{result['plan'].get('market_analysis', '')}")
    print(f"交易数量：{len(result['intents'])} 笔")
    for i, intent in enumerate(result["intents"], 1):
        print(f"\n  交易 {i}：")
        print(f"    {intent}")

    print("\n" + "=" * 60)
    print("✅ 决策生成模块测试完成")
    print("=" * 60)