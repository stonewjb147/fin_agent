# ============================================
# 多日回测引擎
# 功能：模拟多个交易日的完整决策闭环
# 每天执行：信号收集 → 决策生成 → 风控审批 → 交易执行
# 验证智能体能否根据持仓变化动态调整策略
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import random
from datetime import datetime, timedelta
from typing import List, Dict

# 导入主智能体
from master_agent import build_master_graph, signal_aggregation_node
from master_state import MasterState

# 导入 ETF 模拟环境
from etf_env import ETFSimEnv, ETFData

# 导入决策模块
from decision_maker import generate_trade_plan, plan_to_intents

# 导入风控模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week7"))
from risk_models import RiskEngine
from risk_rules import (
    SingleTradeLimitRule,
    TotalExposureRule,
    ConcentrationRiskRule,
    ConfidenceThresholdRule,
    DailyTradeFrequencyRule
)

# ============================================
# 第 1 步：创建多日回测环境
# ============================================

class BacktestEnv(ETFSimEnv):
    """
    多日回测环境
    
    继承自 ETFSimEnv，增加了：
    - 每日价格随机波动
    - 交易日推进
    - 回测日志
    """

    def __init__(self, initial_cash: float = 500000):
        """初始化回测环境"""
        super().__init__(initial_cash)
        self.current_day = 0                    # 当前交易日
        self.daily_records: List[Dict] = []     # 每日记录

    def next_day(self):
        """
        推进到下一个交易日
        
        模拟市场波动：
        - 每只 ETF 价格随机波动 ±3%
        - 更新持仓的当前价格
        - 每日波动独立（简单随机游走）
        """
        self.current_day += 1

        # 随机更新每只 ETF 的价格
        for etf in self.etf_list:
            # 随机涨跌 -3% 到 +3%
            change_pct = random.uniform(-0.03, 0.03)
            etf.price = round(etf.price * (1 + change_pct), 2)
            etf.change_pct = round(change_pct * 100, 1)

        # 更新持仓的当前价格
        for pos in self.positions.values():
            etf = self.etf_dict.get(pos.symbol)
            if etf:
                pos.current_price = etf.price

        print(f"\n{'=' * 60}")
        print(f"📅 第 {self.current_day} 个交易日")
        print(f"{'=' * 60}")

        # 打印当日行情
        print("\n📋 今日行情：")
        for etf in self.etf_list:
            icon = "🔴" if etf.change_pct > 0 else "🟢"
            print(f"  {icon} {etf.symbol} {etf.name}：{etf.price:.2f}（{etf.change_pct:+.1f}%）")

    def record_day(self, decision_result: Dict):
        """
        记录当日决策和账户状态

        参数：
            decision_result: 当日决策结果
        """
        summary = self.get_summary()
        record = {
            "day": self.current_day,
            "date": (datetime.now() + timedelta(days=self.current_day)).strftime("%Y-%m-%d"),
            "total_assets": summary["total_assets"],
            "cash": self.cash,
            "total_profit": summary["total_profit"],
            "total_profit_pct": summary["total_profit_pct"],
            "position_count": summary["position_count"],
            "trade_count_today": len(decision_result.get("trades", [])),
            "positions": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "quantity": p.quantity,
                    "market_value": p.market_value,
                    "profit_loss": p.profit_loss
                }
                for p in self.get_positions()
            ]
        }
        self.daily_records.append(record)

    def get_positions_text(self) -> str:
        """
        获取当前持仓的文本描述（给 LLM 看）

        返回：
            格式化的持仓描述文本
        """
        positions = self.get_positions()
        if not positions:
            return "当前空仓，无任何持仓"

        lines = ["当前持仓："]
        for p in positions:
            icon = "🔴" if p.profit_loss > 0 else "🟢"
            lines.append(
                f"  {icon} {p.name}({p.symbol})：持有 {p.quantity} 股，"
                f"成本 {p.avg_cost:.2f}，现价 {p.current_price:.2f}，"
                f"市值 {p.market_value:,.2f}，"
                f"盈亏 {p.profit_loss:+,.2f}（{p.profit_loss_pct:+.1%}）"
            )
        return "\n".join(lines)

    def get_daily_summary(self) -> str:
        """
        获取每日净值变化摘要

        返回：
            净值变化表
        """
        if not self.daily_records:
            return "暂无记录"

        lines = ["\n📈 净值变化："]
        lines.append(f"{'日期':<12} {'总资产':>12} {'收益':>10} {'收益率':>8} {'持仓数':>6}")
        lines.append("-" * 55)

        for r in self.daily_records:
            lines.append(
                f"{r['date']:<12} {r['total_assets']:>12,.2f} "
                f"{r['total_profit']:>+10,.2f} {r['total_profit_pct']:>+7.2f}% "
                f"{r['position_count']:>6}"
            )

        return "\n".join(lines)


# ============================================
# 第 2 步：创建风控引擎
# ============================================

def create_backtest_risk_engine() -> RiskEngine:
    """创建回测用风控引擎（阈值稍宽松）"""
    engine = RiskEngine()
    engine.add_rule(SingleTradeLimitRule(max_amount=200000))
    engine.add_rule(ConfidenceThresholdRule(min_confidence=0.4))
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=15))
    engine.add_rule(TotalExposureRule(max_exposure_pct=0.9))
    engine.add_rule(ConcentrationRiskRule(max_single_pct=0.5))
    return engine


# ============================================
# 第 3 步：单日决策执行函数
# ============================================

def execute_one_day(env: BacktestEnv, risk_engine: RiskEngine) -> Dict:
    """
    执行一个交易日的完整决策流程

    流程：
    1. 收集四路信号
    2. LLM 生成交易计划
    3. 转为 TradeIntent
    4. 逐笔风控检查
    5. 执行通过风控的交易
    6. 记录当日结果

    参数：
        env: 回测环境
        risk_engine: 风控引擎

    返回：
        当日决策结果字典
    """
    # 第一步：收集信号（真实调用 RAG/新闻/因子/辩论）
    print("\n📡 收集信号...")
    from signal_aggregator import aggregate_all_signals
    signals = aggregate_all_signals(f"第{env.current_day}天市场分析")

    # 第二步：LLM 生成交易计划（传入当前持仓和资金）
    print("\n🧠 生成交易计划...")
    summary = env.get_summary()
    positions_text = env.get_positions_text()

    plan = generate_trade_plan(
        rag_signals=signals.get("rag", ""),
        news_signals=signals.get("news", ""),
        factor_signals=signals.get("factor", ""),
        debate_result=signals.get("debate", ""),
        current_positions=positions_text,
        available_cash=env.cash,
        total_assets=summary["total_assets"]
    )

    # 第三步：转为 TradeIntent
    print("\n📋 转为交易意图...")
    intents = plan_to_intents(plan)

    if not intents:
        print("   今日无交易信号，保持现有持仓")
        env.record_day({"trades": []})
        return {"plan": plan, "trades": [], "executed": 0, "blocked": 0}

    # 第四步：逐笔风控检查
    print(f"\n🛡️ 风控检查（共 {len(intents)} 笔）...")
    context = {
        "total_assets": summary["total_assets"],
        "current_holdings": summary["total_assets"] - env.cash,
        "symbol_holdings": {p.symbol: p.market_value for p in env.get_positions()},
        "daily_trade_count": 0  # 每天重置
    }

    executed = 0
    blocked = 0
    trades_executed = []

    for intent in intents:
        result = risk_engine.check(intent, context)

        if result.passed:
            # 执行交易
            if intent.direction.value == "买入":
                trade_result = env.buy(intent.symbol, intent.quantity)
            else:
                trade_result = env.sell(intent.symbol, intent.quantity)

            if trade_result.get("success"):
                executed += 1
                trades_executed.append({
                    "action": intent.direction.value,
                    "symbol": intent.symbol,
                    "quantity": intent.quantity,
                    "reason": intent.reason
                })
                print(f"   ✅ {trade_result['message'][:80]}")
            else:
                blocked += 1
                print(f"   ❌ 执行失败：{trade_result.get('message', '')[:60]}")
        else:
            blocked += 1
            print(f"   ❌ 风控拦截：{result.summary[:60]}")

    # 第五步：记录当日
    env.record_day({"trades": trades_executed})

    return {
        "plan": plan,
        "trades": trades_executed,
        "executed": executed,
        "blocked": blocked
    }


# ============================================
# 第 4 步：多日回测主函数
# ============================================

def run_backtest(days: int = 3, initial_cash: float = 500000) -> BacktestEnv:
    """
    运行多日回测

    参数：
        days: 回测天数（默认 3 天）
        initial_cash: 初始资金（默认 50 万）

    返回：
        回测环境（包含所有记录）
    """
    print("=" * 60)
    print(f"🚀 多日回测启动（{days} 个交易日）")
    print("=" * 60)
    print(f"初始资金：{initial_cash:,.2f}")
    print(f"风控规则：单笔 ≤ 20万 | 置信度 ≥ 40% | 总敞口 ≤ 90% | 集中度 ≤ 50%")
    print()

    # 创建回测环境
    env = BacktestEnv(initial_cash=initial_cash)
    risk_engine = create_backtest_risk_engine()

    # 逐日执行
    for day in range(1, days + 1):
        # 推进到下一个交易日（价格波动）
        env.next_day()

        # 执行当日决策
        result = execute_one_day(env, risk_engine)

        # 打印当日摘要
        print(f"\n📊 第 {day} 天执行结果：")
        print(f"   执行：{result['executed']} 笔 | 拦截：{result['blocked']} 笔")
        s = env.get_summary()
        print(f"   总资产：{s['total_assets']:,.2f} | 收益：{s['total_profit']:+,.2f}")

        if day < days:
            print(f"\n⏸️ 等待进入下一个交易日...")
            # 实际场景中这里会等待，测试时直接继续

    return env


# ============================================
# 第 5 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 多日回测引擎测试")
    print("=" * 60)
    print()
    print("注意：每天都会调用 LLM 和信号模块，3 天回测约需 2-3 分钟")
    print()

    # 运行 3 天回测
    env = run_backtest(days=3, initial_cash=500000)

    # 打印最终结果
    print("\n" + "=" * 60)
    print("📊 回测最终结果")
    print("=" * 60)

    env.print_summary()

    # 打印净值变化
    print(env.get_daily_summary())

    # 打印交易历史
    print("\n📜 交易历史：")
    for trade in env.trade_history:
        icon = "🔴" if trade["action"] == "买入" else "🟢"
        print(f"  {icon} {trade['time']} | {trade['action']} {trade['name']} {trade['quantity']}股 | 金额 {trade['amount']:,.2f}")

    # 保存回测记录
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    record_file = os.path.join(data_dir, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(record_file, "w", encoding="utf-8") as f:
        json.dump({
            "initial_cash": env.initial_cash,
            "days": env.current_day,
            "final_summary": env.get_summary(),
            "daily_records": env.daily_records,
            "trade_history": env.trade_history
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 回测记录已保存到：{record_file}")
    print("\n" + "=" * 60)
    print("✅ 多日回测完成")
    print("=" * 60)