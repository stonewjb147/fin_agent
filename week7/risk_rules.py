# ============================================
# 具体风控规则实现
# 包含四道核心防线：
#   1. 单笔交易金额上限
#   2. 总风险敞口控制
#   3. 持仓集中度限制
#   4. 交易置信度门槛
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入风控基础模型
from risk_models import RiskRule, RiskCheckResult, RiskLevel

# 导入交易意图模型
from trade_intent import TradeIntent

from typing import Dict, Any  # 类型注解


# ============================================
# 规则1：单笔交易金额上限
# ============================================

class SingleTradeLimitRule(RiskRule):
    """
    单笔交易金额上限规则
    
    限制每一笔交易的总金额不能超过设定的阈值。
    这是最基础的风险控制——避免单笔交易过大。
    
    示例：
        rule = SingleTradeLimitRule(max_amount=500000)  # 单笔最多 50 万
    """
    
    def __init__(self, max_amount: float = 500000):
        """
        初始化规则
        
        参数：
            max_amount: 单笔最大金额（元），默认 50 万
        """
        self.max_amount = max_amount
    
    @property
    def rule_name(self) -> str:
        """规则名称"""
        return "单笔交易金额上限"
    
    @property
    def description(self) -> str:
        """规则描述"""
        return f"单笔交易金额不能超过 {self.max_amount:,.0f} 元"
    
    def check(self, intent: TradeIntent, context: Dict[str, Any] = None) -> RiskCheckResult:
        """
        检查单笔交易金额是否超限
        
        参数：
            intent: 交易意图
            context: 上下文（本规则不需要）
        
        返回：
            检查结果
        """
        # 获取交易总金额
        amount = intent.total_amount
        
        # 判断是否超限
        if amount > self.max_amount:
            # 超限——拦截
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.BLOCK,
                passed=False,
                message=(
                    f"❌ 单笔交易金额 {amount:,.0f} 元 "
                    f"超过上限 {self.max_amount:,.0f} 元"
                ),
                details={
                    "limit": self.max_amount,       # 限额
                    "actual": amount,                # 实际金额
                    "excess": amount - self.max_amount,  # 超出金额
                    "excess_pct": f"{(amount/self.max_amount - 1)*100:.1f}%"  # 超出比例
                }
            )
        else:
            # 在限额内——通过
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message=(
                    f"✅ 单笔交易金额 {amount:,.0f} 元 "
                    f"在限额 {self.max_amount:,.0f} 元以内"
                ),
                details={
                    "limit": self.max_amount,
                    "actual": amount,
                    "usage_pct": f"{amount/self.max_amount*100:.1f}%"  # 使用比例
                }
            )


# ============================================
# 规则2：总风险敞口控制
# ============================================

class TotalExposureRule(RiskRule):
    """
    总风险敞口控制规则
    
    限制所有持仓的总市值占账户总资产的比例。
    防止过度投资，保留一定的现金缓冲。
    
    示例：
        rule = TotalExposureRule(max_exposure_pct=0.6)  # 最多持仓 60%
    """
    
    def __init__(self, max_exposure_pct: float = 0.6):
        """
        初始化规则
        
        参数：
            max_exposure_pct: 最大持仓比例，默认 0.6（60%）
        """
        self.max_exposure_pct = max_exposure_pct
    
    @property
    def rule_name(self) -> str:
        """规则名称"""
        return "总风险敞口控制"
    
    @property
    def description(self) -> str:
        """规则描述"""
        return f"总持仓市值不得超过总资产的 {self.max_exposure_pct:.0%}"
    
    def check(self, intent: TradeIntent, context: Dict[str, Any] = None) -> RiskCheckResult:
        """
        检查总风险敞口是否超限
        
        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - current_holdings: 当前持仓总市值
                - total_assets: 账户总资产
        
        返回：
            检查结果
        """
        if context is None:
            context = {}
        
        # 从上下文获取当前持仓和总资产
        current_holdings = context.get("current_holdings", 0)   # 当前持仓市值
        total_assets = context.get("total_assets", 1_000_000)   # 总资产（默认 100 万）
        
        # 如果总资产为 0，无法计算
        if total_assets <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.WARNING,
                passed=False,
                message="⚠️ 总资产信息异常，无法计算风险敞口",
                details={"current_holdings": current_holdings, "total_assets": total_assets}
            )
        
        # 计算当前敞口比例
        current_exposure = current_holdings / total_assets
        
        # 如果是买入，计算交易后的敞口
        if intent.direction.value == "买入":
            new_holdings = current_holdings + intent.total_amount
            new_exposure = new_holdings / total_assets
            
            if new_exposure > self.max_exposure_pct:
                # 超限——拦截
                return RiskCheckResult(
                    rule_name=self.rule_name,
                    level=RiskLevel.BLOCK,
                    passed=False,
                    message=(
                        f"❌ 交易后总敞口将达到 {new_exposure:.1%}，"
                        f"超过上限 {self.max_exposure_pct:.0%}"
                    ),
                    details={
                        "max_exposure": f"{self.max_exposure_pct:.0%}",
                        "current_exposure": f"{current_exposure:.1%}",
                        "new_exposure": f"{new_exposure:.1%}",
                        "current_holdings": current_holdings,
                        "intent_amount": intent.total_amount,
                        "total_assets": total_assets
                    }
                )
            else:
                # 在限额内——通过
                return RiskCheckResult(
                    rule_name=self.rule_name,
                    level=RiskLevel.PASS,
                    passed=True,
                    message=(
                        f"✅ 交易后总敞口 {new_exposure:.1%}，"
                        f"在限额 {self.max_exposure_pct:.0%} 以内"
                    ),
                    details={
                        "current_exposure": f"{current_exposure:.1%}",
                        "new_exposure": f"{new_exposure:.1%}",
                        "remaining": f"{self.max_exposure_pct - new_exposure:.1%}"
                    }
                )
        else:
            # 卖出不检查敞口（卖出会降低敞口）
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message=f"✅ 卖出操作不增加敞口，当前敞口 {current_exposure:.1%}",
                details={"current_exposure": f"{current_exposure:.1%}"}
            )


# ============================================
# 规则3：持仓集中度限制
# ============================================

class ConcentrationRiskRule(RiskRule):
    """
    持仓集中度限制规则
    
    限制单一标的的持仓占总持仓的比例。
    防止"把鸡蛋放在一个篮子里"。
    
    示例：
        rule = ConcentrationRiskRule(max_single_pct=0.3)  # 单一标的最多 30%
    """
    
    def __init__(self, max_single_pct: float = 0.3):
        """
        初始化规则
        
        参数：
            max_single_pct: 单一标的最大占比，默认 0.3（30%）
        """
        self.max_single_pct = max_single_pct
    
    @property
    def rule_name(self) -> str:
        """规则名称"""
        return "持仓集中度限制"
    
    @property
    def description(self) -> str:
        """规则描述"""
        return f"单一标的持仓不得超过总持仓的 {self.max_single_pct:.0%}"
    
    def check(self, intent: TradeIntent, context: Dict[str, Any] = None) -> RiskCheckResult:
        """
        检查持仓集中度是否超限
        
        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - current_holdings: 当前总持仓市值
                - symbol_holdings: 该标的当前持仓市值
                - total_assets: 总资产
        
        返回：
            检查结果
        """
        if context is None:
            context = {}
        
        # 从上下文获取数据
        current_holdings = context.get("current_holdings", 0)
        symbol_holdings = context.get("symbol_holdings", {}).get(intent.symbol, 0)
        total_assets = context.get("total_assets", 1_000_000)
        
        # 如果是卖出，不检查（卖出会降低集中度）
        if intent.direction.value == "卖出":
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message="✅ 卖出操作不增加集中度",
                details={}
            )
        
        # 计算交易后该标的的持仓
        new_symbol_holdings = symbol_holdings + intent.total_amount
        
        # 计算交易后总持仓
        new_total_holdings = current_holdings + intent.total_amount
        
        # 计算集中度
        if new_total_holdings > 0:
            concentration = new_symbol_holdings / new_total_holdings
            
            if concentration > self.max_single_pct:
                # 超限——拦截
                return RiskCheckResult(
                    rule_name=self.rule_name,
                    level=RiskLevel.BLOCK,
                    passed=False,
                    message=(
                        f"❌ {intent.name} 持仓集中度将达到 {concentration:.1%}，"
                        f"超过上限 {self.max_single_pct:.0%}"
                    ),
                    details={
                        "symbol": intent.symbol,
                        "max_concentration": f"{self.max_single_pct:.0%}",
                        "actual_concentration": f"{concentration:.1%}",
                        "symbol_holdings": new_symbol_holdings,
                        "total_holdings": new_total_holdings
                    }
                )
            else:
                # 在限额内——通过
                return RiskCheckResult(
                    rule_name=self.rule_name,
                    level=RiskLevel.PASS,
                    passed=True,
                    message=(
                        f"✅ {intent.name} 持仓集中度 {concentration:.1%}，"
                        f"在限额 {self.max_single_pct:.0%} 以内"
                    ),
                    details={
                        "concentration": f"{concentration:.1%}",
                        "remaining": f"{self.max_single_pct - concentration:.1%}"
                    }
                )
        else:
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message="✅ 总持仓为 0，集中度检查通过"
            )


# ============================================
# 规则4：交易置信度门槛
# ============================================

class ConfidenceThresholdRule(RiskRule):
    """
    交易置信度门槛规则
    
    要求交易信号的置信度必须达到一定水平才能执行。
    防止低质量的信号触发交易。
    
    示例：
        rule = ConfidenceThresholdRule(min_confidence=0.6)  # 置信度至少 60%
    """
    
    def __init__(self, min_confidence: float = 0.6):
        """
        初始化规则
        
        参数：
            min_confidence: 最低置信度，默认 0.6（60%）
        """
        self.min_confidence = min_confidence
    
    @property
    def rule_name(self) -> str:
        """规则名称"""
        return "交易置信度门槛"
    
    @property
    def description(self) -> str:
        """规则描述"""
        return f"交易置信度必须 ≥ {self.min_confidence:.0%}"
    
    def check(self, intent: TradeIntent, context: Dict[str, Any] = None) -> RiskCheckResult:
        """
        检查交易置信度是否达标
        
        参数：
            intent: 交易意图
            context: 上下文（本规则不需要）
        
        返回：
            检查结果
        """
        confidence = intent.confidence
        
        if confidence < self.min_confidence:
            # 置信度不足——拦截
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.BLOCK,
                passed=False,
                message=(
                    f"❌ 交易置信度 {confidence:.0%} "
                    f"低于门槛 {self.min_confidence:.0%}"
                ),
                details={
                    "threshold": f"{self.min_confidence:.0%}",
                    "actual": f"{confidence:.0%}",
                    "gap": f"{self.min_confidence - confidence:.0%}"
                }
            )
        else:
            # 置信度达标——通过
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message=(
                    f"✅ 交易置信度 {confidence:.0%} "
                    f"达到门槛 {self.min_confidence:.0%}"
                ),
                details={
                    "threshold": f"{self.min_confidence:.0%}",
                    "actual": f"{confidence:.0%}"
                }
            )


# ============================================
# 规则5：日交易频次限制
# ============================================

class DailyTradeFrequencyRule(RiskRule):
    """
    日交易频次限制规则
    
    限制每天最多执行的交易次数，防止过度交易。
    
    示例：
        rule = DailyTradeFrequencyRule(max_daily_trades=10)
    """
    
    def __init__(self, max_daily_trades: int = 10):
        """
        初始化规则
        
        参数：
            max_daily_trades: 每日最大交易次数，默认 10 次
        """
        self.max_daily_trades = max_daily_trades
    
    @property
    def rule_name(self) -> str:
        """规则名称"""
        return "日交易频次限制"
    
    @property
    def description(self) -> str:
        """规则描述"""
        return f"每日最多执行 {self.max_daily_trades} 笔交易"
    
    def check(self, intent: TradeIntent, context: Dict[str, Any] = None) -> RiskCheckResult:
        """
        检查当日交易次数是否超限
        
        参数：
            intent: 交易意图
            context: 必须包含以下字段：
                - daily_trade_count: 当日已执行交易数
        
        返回：
            检查结果
        """
        if context is None:
            context = {}
        
        # 获取当日已执行交易数
        daily_count = context.get("daily_trade_count", 0)
        
        if daily_count >= self.max_daily_trades:
            # 超限——拦截
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.BLOCK,
                passed=False,
                message=(
                    f"❌ 今日已执行 {daily_count} 笔交易，"
                    f"达到上限 {self.max_daily_trades} 笔"
                ),
                details={
                    "max_daily": self.max_daily_trades,
                    "current": daily_count
                }
            )
        else:
            # 在限额内——通过
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message=(
                    f"✅ 今日已执行 {daily_count} 笔，"
                    f"还可执行 {self.max_daily_trades - daily_count} 笔"
                ),
                details={
                    "remaining": self.max_daily_trades - daily_count
                }
            )


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("风控规则测试")
    print("=" * 60)
    
    # 导入风控引擎和交易意图
    from risk_models import RiskEngine
    from trade_intent import TradeIntentBuilder
    
    # 创建风控引擎并注册所有规则
    print("\n注册风控规则...")
    engine = RiskEngine()
    engine.add_rule(SingleTradeLimitRule(max_amount=500000))         # 单笔最多 50 万
    engine.add_rule(ConfidenceThresholdRule(min_confidence=0.6))     # 置信度 ≥ 60%
    engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=10))    # 每日最多 10 笔
    engine.add_rule(TotalExposureRule(max_exposure_pct=0.6))         # 总敞口 ≤ 60%
    engine.add_rule(ConcentrationRiskRule(max_single_pct=0.3))       # 集中度 ≤ 30%
    
    print(f"\n已注册 {len(engine.list_rules())} 条规则：")
    for name, desc in engine.list_rules():
        print(f"  📋 {name}: {desc}")
    
    # 模拟账户上下文
    context = {
        "total_assets": 1_000_000,          # 总资产 100 万
        "current_holdings": 400_000,         # 当前持仓 40 万
        "symbol_holdings": {                 # 各标的持仓
            "600519.SH": 150_000,            # 茅台 15 万
            "000858.SZ": 100_000             # 五粮液 10 万
        },
        "daily_trade_count": 3               # 今日已交易 3 笔
    }
    
    # 测试 1：正常的买入交易（应通过所有检查）
    print("\n" + "=" * 60)
    print("测试 1：正常小额买入（应通过）")
    print("=" * 60)
    
    intent_1 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(100, 1500.0)           # 买入 15 万
                .from_factor("高ROE因子", 0.85)
                .with_reason("ROE超预期，盈利能力突出")
                .build())
    
    print(intent_1)
    result_1 = engine.check(intent_1, context)
    print(f"\n📊 风控结果：{result_1.summary}")
    for r in result_1.results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} {r.rule_name}: {r.message[:80]}")
    
    # 测试 2：超大额交易（应触发单笔限额）
    print("\n" + "=" * 60)
    print("测试 2：超大额买入（应触发单笔限额）")
    print("=" * 60)
    
    intent_2 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(5000, 1500.0)          # 买入 750 万
                .from_factor("高ROE因子", 0.9)
                .with_reason("重仓茅台")
                .build())
    
    print(intent_2)
    result_2 = engine.check(intent_2, context)
    print(f"\n📊 风控结果：{result_2.summary}")
    for r in result_2.results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} {r.rule_name}: {r.message[:80]}")
    
    # 测试 3：低置信度交易（应触发置信度门槛）
    print("\n" + "=" * 60)
    print("测试 3：低置信度交易（应触发置信度门槛）")
    print("=" * 60)
    
    intent_3 = (TradeIntentBuilder()
                .set_symbol("000858.SZ")
                .set_name("五粮液")
                .buy(100, 120.0)
                .from_factor("弱信号", 0.35)  # 置信度只有 35%
                .with_reason("试试看")
                .build())
    
    print(intent_3)
    result_3 = engine.check(intent_3, context)
    print(f"\n📊 风控结果：{result_3.summary}")
    for r in result_3.results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} {r.rule_name}: {r.message[:80]}")
    
    # 测试 4：集中度过高（应触发集中度限制）
    print("\n" + "=" * 60)
    print("测试 4：集中度过高（应触发集中度限制）")
    print("=" * 60)
    
    # 模拟高集中度的上下文
    high_conc_context = {
        "total_assets": 1_000_000,
        "current_holdings": 500_000,
        "symbol_holdings": {"600519.SH": 400_000},  # 茅台已经占了 80%
        "daily_trade_count": 1
    }
    
    intent_4 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(200, 1500.0)          # 再买 30 万茅台
                .from_factor("高ROE因子", 0.8)
                .with_reason("继续加仓茅台")
                .build())
    
    print(intent_4)
    result_4 = engine.check(intent_4, high_conc_context)
    print(f"\n📊 风控结果：{result_4.summary}")
    for r in result_4.results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} {r.rule_name}: {r.message[:80]}")
    
    print("\n" + "=" * 60)
    print("✅ 风控规则测试完成")
    print("=" * 60)