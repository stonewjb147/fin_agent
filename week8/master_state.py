# ============================================
# 主智能体状态定义
# 整合前七周所有子模块的数据
# ============================================

from typing import TypedDict, Optional, List, Dict
from etf_env import ETFSimEnv

class MasterState(TypedDict):
    """主智能体的全局状态"""

    # === 用户输入 ===
    user_query: str              # 用户指令（如"分析市场并给出交易建议"）

    # === 模拟环境 ===
    env: Optional[ETFSimEnv]     # ETF 模拟交易环境

    # === 信号汇总（第3-6练） ===
    rag_signals: str             # RAG 研报分析结果（第3练）
    news_signals: str            # 新闻信号（第4练）
    factor_signals: str          # 因子信号（第6练）
    debate_result: str           # 辩论结论（第6练）

    # === 决策（第5练 Deep Agent） ===
    trade_plan: str              # LLM 生成的交易计划

    # === 风控（第7练） ===
    risk_passed: bool            # 风控是否通过
    risk_message: str            # 风控消息

    # === 执行 ===
    execution_results: List[Dict]  # 执行结果列表
    alert_sent: bool             # 是否发送了告警

    # === 最终输出 ===
    final_summary: str           # 最终摘要
    execution_log: List[str]     # 执行日志