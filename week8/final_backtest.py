# ============================================
# 最终回测验证 + 绩效报告生成
# 功能：
#   1. 运行 5 天完整回测
#   2. 计算绩效指标（收益率、夏普比率、最大回撤、胜率）
#   3. 生成 Markdown 格式的最终投资报告
#   4. 保存回测数据和报告
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import math
from datetime import datetime
from typing import List, Dict

# 导入回测引擎
from backtest_runner import BacktestEnv, execute_one_day, create_backtest_risk_engine


# ============================================
# 第 1 步：绩效指标计算
# ============================================

def calculate_performance_metrics(daily_records: List[Dict], initial_cash: float) -> Dict:
    """
    根据每日净值记录计算绩效指标

    参数：
        daily_records: 每日记录列表
        initial_cash: 初始资金

    返回：
        绩效指标字典
    """
    if not daily_records:
        return {"error": "无回测记录"}

    # 提取每日收益率
    daily_returns = []
    prev_value = initial_cash

    for record in daily_records:
        current_value = record["total_assets"]
        daily_return = (current_value - prev_value) / prev_value
        daily_returns.append(daily_return)
        prev_value = current_value

    # 总收益率
    final_value = daily_records[-1]["total_assets"]
    total_return = (final_value - initial_cash) / initial_cash
    total_return_pct = total_return * 100

    # 年化收益率（假设 252 个交易日）
    trading_days = len(daily_records)
    annualized_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 0 else 0

    # 日收益率均值和标准差
    mean_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns) if daily_returns else 0
    std_return = math.sqrt(variance) if variance > 0 else 0.0001

    # 夏普比率（假设无风险利率 3%）
    risk_free_rate = 0.03 / 252  # 日化无风险利率
    sharpe_ratio = (mean_return - risk_free_rate) / std_return * math.sqrt(252) if std_return > 0 else 0

    # 最大回撤
    peak = initial_cash
    max_drawdown = 0
    for record in daily_records:
        value = record["total_assets"]
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # 胜率（收益为正的天数占比）
    winning_days = sum(1 for r in daily_returns if r > 0)
    win_rate = winning_days / len(daily_returns) if daily_returns else 0

    # 盈亏比
    avg_win = sum(r for r in daily_returns if r > 0) / winning_days if winning_days > 0 else 0
    losing_days = len(daily_returns) - winning_days
    avg_loss = abs(sum(r for r in daily_returns if r < 0) / losing_days) if losing_days > 0 else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

    return {
        "initial_cash": initial_cash,
        "final_value": final_value,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "annualized_return_pct": annualized_return * 100,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown * 100,
        "win_rate_pct": win_rate * 100,
        "profit_loss_ratio": profit_loss_ratio,
        "trading_days": trading_days,
        "total_trades": sum(r.get("trade_count_today", 0) for r in daily_records),
        "mean_daily_return_pct": mean_return * 100,
        "std_daily_return_pct": std_return * 100
    }


# ============================================
# 第 2 步：生成 Markdown 投资报告
# ============================================

def generate_final_report(
    env: BacktestEnv,
    metrics: Dict,
    scenario_name: str = "标准市场"
) -> str:
    """
    生成最终投资绩效报告

    参数：
        env: 回测环境
        metrics: 绩效指标
        scenario_name: 场景名称

    返回：
        Markdown 格式的报告文本
    """
    lines = []

    # 标题
    lines.append("# 🤖 CUFEI-Q 主投资智能体 · 回测绩效报告")
    lines.append("")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**回测场景**：{scenario_name}")
    lines.append(f"**回测天数**：{metrics.get('trading_days', 0)} 个交易日")
    lines.append(f"**初始资金**：{metrics.get('initial_cash', 0):,.2f} 元")
    lines.append("")

    # 一、收益概览
    lines.append("## 一、收益概览")
    lines.append("")
    lines.append("| 指标 | 数值 | 评价 |")
    lines.append("|------|------|------|")
    final_val = metrics.get("final_value", 0)
    total_ret = metrics.get("total_return_pct", 0)
    ret_icon = "🔴" if total_ret > 0 else "🟢"
    lines.append(f"| 最终资产 | {final_val:,.2f} 元 | - |")
    lines.append(f"| 总收益率 | {ret_icon} {total_ret:+.2f}% | {'盈利' if total_ret > 0 else '亏损'} |")
    ann_ret = metrics.get("annualized_return_pct", 0)
    lines.append(f"| 年化收益率 | {ann_ret:+.2f}% | - |")
    lines.append("")

    # 二、风险指标
    lines.append("## 二、风险指标")
    lines.append("")
    lines.append("| 指标 | 数值 | 评价 |")
    lines.append("|------|------|------|")
    sharpe = metrics.get("sharpe_ratio", 0)
    sharpe_eval = "优秀" if sharpe > 2 else ("良好" if sharpe > 1 else ("一般" if sharpe > 0.5 else "较差"))
    lines.append(f"| 夏普比率 | {sharpe:.2f} | {sharpe_eval} |")
    max_dd = metrics.get("max_drawdown_pct", 0)
    dd_eval = "优秀" if max_dd < 5 else ("良好" if max_dd < 10 else ("一般" if max_dd < 20 else "较高"))
    lines.append(f"| 最大回撤 | {max_dd:.2f}% | {dd_eval} |")
    win_rate = metrics.get("win_rate_pct", 0)
    lines.append(f"| 胜率 | {win_rate:.1f}% | - |")
    pl_ratio = metrics.get("profit_loss_ratio", 0)
    lines.append(f"| 盈亏比 | {pl_ratio:.2f} | - |")
    lines.append("")

    # 三、每日净值
    lines.append("## 三、每日净值变化")
    lines.append("")
    lines.append("| 日期 | 总资产 | 日收益 | 累计收益 | 持仓数 | 交易数 |")
    lines.append("|------|--------|--------|----------|--------|--------|")
    prev = metrics.get("initial_cash", 0)
    for r in env.daily_records:
        day_ret = (r["total_assets"] - prev) / prev * 100
        cum_ret = (r["total_assets"] - metrics.get("initial_cash", 0)) / metrics.get("initial_cash", 0) * 100
        icon = "🔴" if day_ret > 0 else "🟢"
        lines.append(
            f"| {r['date']} | {r['total_assets']:,.2f} | "
            f"{icon} {day_ret:+.2f}% | {cum_ret:+.2f}% | "
            f"{r['position_count']} | {r['trade_count_today']} |"
        )
        prev = r["total_assets"]
    lines.append("")

    # 四、持仓明细
    lines.append("## 四、最终持仓")
    lines.append("")
    positions = env.get_positions()
    if positions:
        lines.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 盈亏 |")
        lines.append("|------|------|------|------|------|------|------|")
        for p in positions:
            icon = "🔴" if p.profit_loss > 0 else "🟢"
            lines.append(
                f"| {p.symbol} | {p.name} | {p.quantity} | {p.avg_cost:.2f} | "
                f"{p.current_price:.2f} | {p.market_value:,.2f} | "
                f"{icon} {p.profit_loss:+,.2f} |"
            )
    else:
        lines.append("*当前空仓*")
    lines.append("")

    # 五、交易记录
    lines.append("## 五、交易记录")
    lines.append("")
    if env.trade_history:
        lines.append("| 时间 | 方向 | 标的 | 数量 | 金额 |")
        lines.append("|------|------|------|------|------|")
        for t in env.trade_history:
            icon = "🔴" if t["action"] == "买入" else "🟢"
            lines.append(
                f"| {t['time']} | {icon} {t['action']} | "
                f"{t['name']}({t['symbol']}) | {t['quantity']} | {t['amount']:,.2f} |"
            )
    else:
        lines.append("*无交易记录*")
    lines.append("")

    # 六、综合评价
    lines.append("## 六、综合评价")
    lines.append("")

    # 自动评价
    evals = []
    if total_ret > 0:
        evals.append(f"✅ **正向收益**：在 {metrics.get('trading_days', 0)} 个交易日内实现了正收益")
    else:
        evals.append(f"⚠️ **负向收益**：回测期间出现亏损，需优化策略")

    if sharpe > 1:
        evals.append(f"✅ **风险调整收益良好**：夏普比率 {sharpe:.2f}，风险控制有效")
    elif sharpe > 0:
        evals.append(f"⚠️ **风险调整收益一般**：夏普比率 {sharpe:.2f}，可进一步优化")

    if max_dd < 10:
        evals.append(f"✅ **回撤控制优秀**：最大回撤仅 {max_dd:.2f}%")
    else:
        evals.append(f"⚠️ **回撤偏大**：最大回撤 {max_dd:.2f}%，需加强风控")

    for e in evals:
        lines.append(f"- {e}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本报告由 CUFEI-Q 主投资智能体自动生成，仅供参考，不构成投资建议。*")

    return "\n".join(lines)


# ============================================
# 第 3 步：完整回测执行
# ============================================

def run_final_backtest(days: int = 5, initial_cash: float = 500000) -> tuple:
    """
    运行最终完整回测

    参数：
        days: 回测天数
        initial_cash: 初始资金

    返回：
        (回测环境, 绩效指标, 报告文本)
    """
    print("=" * 60)
    print("🏆 CUFEI-Q 主投资智能体 · 最终回测")
    print("=" * 60)
    print(f"回测天数：{days} 天")
    print(f"初始资金：{initial_cash:,.2f} 元")
    print(f"开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("注意：每天会调用 LLM 和信号模块，5 天回测约需 3-5 分钟")
    print()

    # 创建回测环境
    env = BacktestEnv(initial_cash=initial_cash)
    risk_engine = create_backtest_risk_engine()

    # 逐日执行
    for day in range(1, days + 1):
        env.next_day()
        result = execute_one_day(env, risk_engine)

        print(f"\n📊 第 {day} 天完成：执行 {result['executed']} 笔 | 拦截 {result['blocked']} 笔")

    # 计算绩效指标
    print("\n📈 计算绩效指标...")
    metrics = calculate_performance_metrics(env.daily_records, initial_cash)

    # 生成报告
    print("📝 生成投资报告...")
    report = generate_final_report(env, metrics)

    return env, metrics, report


# ============================================
# 第 4 步：保存回测结果
# ============================================

def save_backtest_results(env: BacktestEnv, metrics: Dict, report: str):
    """
    保存回测结果到文件

    参数：
        env: 回测环境
        metrics: 绩效指标
        report: 报告文本
    """
    # 保存目录
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 保存 JSON 数据
    json_file = os.path.join(data_dir, f"final_backtest_{timestamp}.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "metrics": metrics,
            "daily_records": env.daily_records,
            "trade_history": env.trade_history,
            "final_positions": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "profit_loss": p.profit_loss
                }
                for p in env.get_positions()
            ]
        }, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON 数据已保存：{json_file}")

    # 保存 Markdown 报告
    md_file = os.path.join(data_dir, f"final_report_{timestamp}.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Markdown 报告已保存：{md_file}")

    return json_file, md_file


# ============================================
# 第 5 步：打印绩效摘要
# ============================================

def print_performance_summary(metrics: Dict):
    """打印格式化的绩效摘要"""
    print("\n" + "=" * 60)
    print("📊 绩效摘要")
    print("=" * 60)

    total_ret = metrics.get("total_return_pct", 0)
    icon = "🔴" if total_ret > 0 else "🟢"

    print(f"最终资产：    {metrics.get('final_value', 0):>12,.2f} 元")
    print(f"总收益率：    {icon} {total_ret:>+10.2f}%")
    print(f"年化收益率：  {metrics.get('annualized_return_pct', 0):>+10.2f}%")
    print(f"夏普比率：    {metrics.get('sharpe_ratio', 0):>12.2f}")
    print(f"最大回撤：    {metrics.get('max_drawdown_pct', 0):>10.2f}%")
    print(f"胜率：        {metrics.get('win_rate_pct', 0):>10.1f}%")
    print(f"盈亏比：      {metrics.get('profit_loss_ratio', 0):>12.2f}")
    print(f"总交易次数：  {metrics.get('total_trades', 0):>10}")


# ============================================
# 第 6 步：主程序
# ============================================

if __name__ == "__main__":
    # 运行 5 天回测
    env, metrics, report = run_final_backtest(days=5, initial_cash=500000)

    # 打印绩效
    print_performance_summary(metrics)

    # 打印净值变化
    print(env.get_daily_summary())

    # 保存结果
    json_file, md_file = save_backtest_results(env, metrics, report)

    # 打印报告预览
    print("\n" + "=" * 60)
    print("📄 投资报告预览（前 50 行）")
    print("=" * 60)
    for line in report.split("\n")[:50]:
        print(line)

    print("\n" + "=" * 60)
    print("✅ 最终回测完成！")
    print("=" * 60)
    print(f"\n📁 结果文件：")
    print(f"   数据：{json_file}")
    print(f"   报告：{md_file}")