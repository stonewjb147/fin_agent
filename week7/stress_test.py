# ============================================
# 风控系统压力测试
# 功能：批量生成随机交易意图，测试风控引擎表现
# 统计指标：
#   - 通过率 / 拦截率 / 警告率
#   - 各规则的触发频率
#   - 平均检查耗时
#   - 误拦分析（正常交易被拦截的比例）
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random  # 随机数生成
import time    # 计时
from collections import Counter  # 计数器
from typing import List, Dict    # 类型注解

# 导入风控模块
from risk_models import RiskEngine, RiskCheckResult, RiskLevel
from risk_rules import (
    SingleTradeLimitRule,
    TotalExposureRule,
    ConcentrationRiskRule,
    ConfidenceThresholdRule,
    DailyTradeFrequencyRule
)
from trade_intent import TradeIntent, TradeIntentBuilder


# ============================================
# 第 1 步：创建风控引擎
# ============================================

def create_engine(
    single_limit: float = 500000,    # 单笔限额
    min_confidence: float = 0.6,     # 最低置信度
    max_daily: int = 10,             # 日频次上限
    max_exposure: float = 0.6,       # 总敞口上限
    max_concentration: float = 0.3   # 集中度上限
) -> RiskEngine:
    """
    创建可配置的风控引擎
    
    参数：
        single_limit: 单笔交易金额上限（元）
        min_confidence: 最低置信度
        max_daily: 每日最多交易次数
        max_exposure: 总敞口上限
        max_concentration: 单一标的上限
    
    返回：
        配置好的 RiskEngine
    """
    engine = RiskEngine()
    engine.add_rule(SingleTradeLimitRule(max_amount=single_limit))
    engine.add_rule(ConfidenceThresholdRule(min_confidence=min_confidence))
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=max_daily))
    engine.add_rule(TotalExposureRule(max_exposure_pct=max_exposure))
    engine.add_rule(ConcentrationRiskRule(max_single_pct=max_concentration))
    return engine


# ============================================
# 第 2 步：随机交易意图生成器
# ============================================

def generate_random_intent(is_normal: bool = True) -> TradeIntent:
    """
    生成随机交易意图
    
    参数：
        is_normal: True 生成正常交易，False 生成高风险交易
    
    返回：
        TradeIntent 对象
    """
    # 股票池
    stocks = [
        ("600519.SH", "贵州茅台", 1500.0),
        ("000858.SZ", "五粮液", 120.0),
        ("300750.SZ", "宁德时代", 180.0),
        ("601318.SH", "中国平安", 45.0),
        ("000333.SZ", "美的集团", 55.0),
        ("600036.SH", "招商银行", 38.0),
        ("002415.SZ", "海康威视", 32.0),
        ("600276.SH", "恒瑞医药", 48.0),
    ]
    
    # 随机选股
    symbol, name, base_price = random.choice(stocks)
    price = base_price * random.uniform(0.9, 1.1)  # 价格在 90%-110% 之间波动
    
    if is_normal:
        # 正常交易：金额在 1万 - 40万，置信度在 0.6 - 0.95
        quantity = random.randint(50, 2000)
        confidence = random.uniform(0.6, 0.95)
    else:
        # 高风险交易：金额在 30万 - 200万，置信度在 0.2 - 0.8
        quantity = random.randint(2000, 10000)
        confidence = random.uniform(0.2, 0.8)
    
    # 随机方向（70% 买入，30% 卖出）
    direction = "buy" if random.random() < 0.7 else "sell"
    
    # 构建意图
    if direction == "buy":
        intent = (TradeIntentBuilder()
                  .set_symbol(symbol)
                  .set_name(name)
                  .buy(quantity, price)
                  .from_factor("压力测试因子", confidence)
                  .with_reason(f"压力测试-{'正常' if is_normal else '高风险'}")
                  .build())
    else:
        intent = (TradeIntentBuilder()
                  .set_symbol(symbol)
                  .set_name(name)
                  .sell(quantity, price)
                  .from_factor("压力测试因子", confidence)
                  .with_reason(f"压力测试-{'正常' if is_normal else '高风险'}")
                  .build())
    
    return intent


# ============================================
# 第 3 步：压力测试执行函数
# ============================================

def run_stress_test(
    engine: RiskEngine,
    num_normal: int = 70,     # 正常交易数量
    num_risky: int = 30,      # 高风险交易数量
    context: dict = None      # 账户上下文
) -> Dict:
    """
    执行压力测试
    
    参数：
        engine: 风控引擎
        num_normal: 正常交易数量
        num_risky: 高风险交易数量
        context: 账户上下文
    
    返回：
        测试统计结果字典
    """
    print("=" * 60)
    print(f"🧪 风控系统压力测试")
    print("=" * 60)
    print(f"正常交易：{num_normal} 笔")
    print(f"高风险交易：{num_risky} 笔")
    print(f"总计：{num_normal + num_risky} 笔")
    print()
    
    # 统计变量
    total_passed = 0          # 总通过数
    total_blocked = 0         # 总拦截数
    total_warning = 0         # 总警告数
    
    normal_passed = 0         # 正常交易通过数
    normal_blocked = 0        # 正常交易拦截数（这些是潜在误拦）
    
    risky_passed = 0          # 高风险交易通过数（这些是潜在漏拦）
    risky_blocked = 0         # 高风险交易拦截数
    
    rule_trigger_counts = Counter()  # 各规则触发次数
    total_time = 0.0          # 总耗时
    results_list = []         # 所有结果
    
    # 生成所有交易意图
    all_intents = []
    for _ in range(num_normal):
        all_intents.append(("正常", generate_random_intent(is_normal=True)))
    for _ in range(num_risky):
        all_intents.append(("高风险", generate_random_intent(is_normal=False)))
    
    # 随机打乱顺序
    random.shuffle(all_intents)
    
    # 逐笔检查
    for i, (label, intent) in enumerate(all_intents, 1):
        # 计时
        start = time.time()
        result = engine.check(intent, context)
        elapsed = time.time() - start
        total_time += elapsed
        
        # 统计
        if result.passed:
            total_passed += 1
        else:
            if result.risk_level == RiskLevel.BLOCK:
                total_blocked += 1
            elif result.risk_level == RiskLevel.WARNING:
                total_warning += 1
        
        # 按标签统计
        if label == "正常":
            if result.passed:
                normal_passed += 1
            else:
                normal_blocked += 1
        else:  # 高风险
            if result.passed:
                risky_passed += 1
            else:
                risky_blocked += 1
        
        # 统计各规则触发情况
        for r in result.results:
            if not r.passed:
                rule_trigger_counts[r.rule_name] += 1
        
        # 保存结果
        results_list.append({
            "index": i,
            "label": label,
            "symbol": intent.symbol,
            "amount": intent.total_amount,
            "confidence": intent.confidence,
            "passed": result.passed,
            "blocked_rules": result.blocked_rules
        })
        
        # 每 20 笔打印一次进度
        if i % 20 == 0:
            print(f"  进度：{i}/{len(all_intents)}")
    
    # 计算统计数据
    total = num_normal + num_risky
    avg_time = total_time / total * 1000  # 转为毫秒
    
    stats = {
        "total": total,
        "total_passed": total_passed,
        "total_blocked": total_blocked,
        "total_warning": total_warning,
        "pass_rate": f"{total_passed / total * 100:.1f}%",
        "block_rate": f"{total_blocked / total * 100:.1f}%",
        
        "normal_count": num_normal,
        "normal_passed": normal_passed,
        "normal_blocked": normal_blocked,
        "normal_pass_rate": f"{normal_passed / num_normal * 100:.1f}%",
        "false_positive_rate": f"{normal_blocked / num_normal * 100:.1f}%",  # 误拦率
        
        "risky_count": num_risky,
        "risky_passed": risky_passed,
        "risky_blocked": risky_blocked,
        "risky_block_rate": f"{risky_blocked / num_risky * 100:.1f}%",
        "false_negative_rate": f"{risky_passed / num_risky * 100:.1f}%",     # 漏拦率
        
        "rule_triggers": dict(rule_trigger_counts.most_common()),
        "avg_check_time_ms": f"{avg_time:.1f}",
        "total_time_seconds": f"{total_time:.1f}"
    }
    
    return stats


# ============================================
# 第 4 步：打印压力测试报告
# ============================================

def print_report(stats: Dict) -> None:
    """
    打印格式化的压力测试报告
    
    参数：
        stats: 测试统计数据
    """
    print("\n" + "=" * 60)
    print("📊 压力测试报告")
    print("=" * 60)
    
    # 总体统计
    print(f"\n📈 总体统计：")
    print(f"   总交易数：{stats['total']} 笔")
    print(f"   通过：{stats['total_passed']} 笔（{stats['pass_rate']}）")
    print(f"   拦截：{stats['total_blocked']} 笔（{stats['block_rate']}）")
    print(f"   警告：{stats['total_warning']} 笔")
    
    # 正常交易统计
    print(f"\n✅ 正常交易（{stats['normal_count']} 笔）：")
    print(f"   通过：{stats['normal_passed']} 笔（{stats['normal_pass_rate']}）")
    print(f"   误拦：{stats['normal_blocked']} 笔（误拦率 {stats['false_positive_rate']}）")
    
    # 高风险交易统计
    print(f"\n⚠️ 高风险交易（{stats['risky_count']} 笔）：")
    print(f"   拦截：{stats['risky_blocked']} 笔（拦截率 {stats['risky_block_rate']}）")
    print(f"   漏拦：{stats['risky_passed']} 笔（漏拦率 {stats['false_negative_rate']}）")
    
    # 规则触发统计
    print(f"\n📋 各规则触发次数：")
    for rule_name, count in stats['rule_triggers'].items():
        bar = "█" * (count // 2)
        print(f"   {rule_name}: {count} 次 {bar}")
    
    # 性能统计
    print(f"\n⏱️ 性能统计：")
    print(f"   平均检查耗时：{stats['avg_check_time_ms']} ms")
    print(f"   总耗时：{stats['total_time_seconds']} 秒")
    
    # 评价
    print(f"\n📝 综合评价：")
    
    # 误拦率评价
    false_positive = float(stats['false_positive_rate'].replace('%', ''))
    if false_positive < 5:
        print(f"   ✅ 误拦率 {stats['false_positive_rate']} — 优秀（<5%）")
    elif false_positive < 15:
        print(f"   ⚠️ 误拦率 {stats['false_positive_rate']} — 偏高，建议调高阈值")
    else:
        print(f"   ❌ 误拦率 {stats['false_positive_rate']} — 过高，需要大幅调整")
    
    # 漏拦率评价
    false_negative = float(stats['false_negative_rate'].replace('%', ''))
    if false_negative < 15:
        print(f"   ✅ 漏拦率 {stats['false_negative_rate']} — 优秀（<15%）")
    elif false_negative < 30:
        print(f"   ⚠️ 漏拦率 {stats['false_negative_rate']} — 偏高，建议降低阈值")
    else:
        print(f"   ❌ 漏拦率 {stats['false_negative_rate']} — 过高，需要大幅调整")


# ============================================
# 第 5 步：阈值调优建议
# ============================================

def suggest_threshold_adjustments(stats: Dict) -> List[str]:
    """
    根据压力测试结果，给出阈值调优建议
    
    参数：
        stats: 测试统计数据
    
    返回：
        建议列表
    """
    suggestions = []
    
    false_positive = float(stats['false_positive_rate'].replace('%', ''))
    false_negative = float(stats['false_negative_rate'].replace('%', ''))
    rule_triggers = stats['rule_triggers']
    
    # 误拦率过高 → 放宽阈值
    if false_positive > 10:
        if rule_triggers.get("单笔交易金额上限", 0) > 10:
            suggestions.append("💡 建议提高「单笔交易金额上限」阈值（如从 50 万提到 80 万）")
        if rule_triggers.get("交易置信度门槛", 0) > 10:
            suggestions.append("💡 建议降低「交易置信度门槛」（如从 60% 降到 50%）")
        if rule_triggers.get("持仓集中度限制", 0) > 10:
            suggestions.append("💡 建议放宽「持仓集中度限制」（如从 30% 提到 40%）")
    
    # 漏拦率过高 → 收紧阈值
    if false_negative > 20:
        if rule_triggers.get("单笔交易金额上限", 0) < 5:
            suggestions.append("⚠️ 建议降低「单笔交易金额上限」阈值（如从 50 万降到 30 万）")
        if rule_triggers.get("交易置信度门槛", 0) < 5:
            suggestions.append("⚠️ 建议提高「交易置信度门槛」（如从 60% 提到 70%）")
        if rule_triggers.get("总风险敞口控制", 0) < 5:
            suggestions.append("⚠️ 建议收紧「总风险敞口控制」（如从 60% 降到 50%）")
    
    if not suggestions:
        suggestions.append("✅ 当前阈值设置合理，无需调整")
    
    return suggestions


# ============================================
# 第 6 步：运行完整压力测试
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 风控系统压力测试工具")
    print("=" * 60)
    
    # 创建默认阈值引擎
    print("\n使用默认阈值：")
    print("   单笔限额：50 万")
    print("   置信度门槛：60%")
    print("   日频次上限：10 笔")
    print("   总敞口上限：60%")
    print("   集中度上限：30%")
    
    engine = create_engine(
        single_limit=500000,
        min_confidence=0.6,
        max_daily=10,
        max_exposure=0.6,
        max_concentration=0.3
    )
    
    # 模拟账户上下文
    context = {
        "total_assets": 1_000_000,
        "current_holdings": 400_000,
        "symbol_holdings": {
            "600519.SH": 120_000,
            "000858.SZ": 100_000,
            "300750.SZ": 80_000
        },
        "daily_trade_count": 4
    }
    
    # 执行压力测试
    stats = run_stress_test(
        engine=engine,
        num_normal=70,      # 70 笔正常交易
        num_risky=30,       # 30 笔高风险交易
        context=context
    )
    
    # 打印报告
    print_report(stats)
    
    # 阈值调优建议
    print(f"\n🔧 阈值调优建议：")
    suggestions = suggest_threshold_adjustments(stats)
    for s in suggestions:
        print(f"   {s}")
    
    print("\n" + "=" * 60)
    print("✅ 压力测试完成")
    print("=" * 60)