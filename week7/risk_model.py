# ============================================
# 风控规则接口和结果模型
# 功能：定义风控规则的标准接口和检查结果格式
# 所有风控规则必须实现 RiskRule 接口
# ============================================

from dataclasses import dataclass, field, asdict  # 数据类
from typing import List, Optional  # 类型注解
from datetime import datetime  # 时间戳
from enum import Enum  # 枚举
from abc import ABC, abstractmethod  # 抽象基类
import json  # JSON 序列化

# 导入交易意图模型
from trade_intent import TradeIntent


# ============================================
# 风控检查结果等级
# ============================================

class RiskLevel(str, Enum):
    """风险等级枚举"""
    PASS = "通过"         # 通过检查
    WARNING = "警告"      # 有风险但可放行
    BLOCK = "拦截"        # 触发拦截，禁止交易


@dataclass
class RiskCheckResult:
    """
    单条风控规则的检查结果
    
    属性：
    - rule_name: 规则名称
    - level: 风险等级（通过/警告/拦截）
    - passed: 是否通过
    - message: 检查结果描述
    - details: 详细信息（如当前值 vs 阈值）
    """
    rule_name: str                          # 规则名称
    level: RiskLevel = RiskLevel.PASS       # 风险等级
    passed: bool = True                     # 是否通过
    message: str = ""                       # 结果描述
    details: dict = field(default_factory=dict)  # 详细信息
    
    def to_dict(self) -> dict:
        """转为字典"""
        d = asdict(self)
        d["level"] = self.level.value
        return d


# ============================================
# 风控规则抽象接口
# ============================================

class RiskRule(ABC):
    """
    风控规则抽象基类
    
    所有具体的风控规则都必须继承这个类，
    并实现 check() 方法。
    
    这样做的好处：
    1. 新增规则只需新建一个类，不改引擎代码
    2. 所有规则有统一的调用接口
    3. 引擎可以通过遍历规则列表来执行全部检查
    """
    
    @property
    @abstractmethod
    def rule_name(self) -> str:
        """规则名称（每个规则必须定义）"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """规则描述（每个规则必须定义）"""
        pass
    
    @abstractmethod
    def check(self, intent: TradeIntent, context: dict = None) -> RiskCheckResult:
        """
        执行风控检查
        
        参数：
            intent: 交易意图对象
            context: 上下文信息（如当前持仓、账户总资产等）
        
        返回：
            RiskCheckResult 对象
        """
        pass
    
    def __repr__(self) -> str:
        return f"<RiskRule: {self.rule_name}>"


# ============================================
# 风控引擎
# ============================================

@dataclass
class RiskEngineResult:
    """
    风控引擎的整体检查结果
    
    汇总所有规则的检查结果，给出最终判断
    
    属性：
    - intent_id: 交易意图 ID
    - passed: 是否通过所有检查
    - risk_level: 最高风险等级
    - total_rules: 总规则数
    - passed_rules: 通过的规则数
    - blocked_rules: 拦截的规则数
    - warning_rules: 警告的规则数
    - results: 每条规则的详细结果
    - summary: 汇总描述
    - checked_at: 检查时间
    """
    intent_id: str = ""                             # 意图 ID
    passed: bool = True                             # 是否通过
    risk_level: RiskLevel = RiskLevel.PASS          # 最高风险等级
    total_rules: int = 0                            # 总规则数
    passed_rules: int = 0                           # 通过数
    blocked_rules: int = 0                          # 拦截数
    warning_rules: int = 0                          # 警告数
    results: List[RiskCheckResult] = field(default_factory=list)  # 各规则结果
    summary: str = ""                               # 汇总描述
    checked_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    def to_dict(self) -> dict:
        """转为字典"""
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        d["results"] = [r.to_dict() for r in self.results]
        return d
    
    def to_json(self) -> str:
        """转为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class RiskEngine:
    """
    风控引擎
    
    管理所有风控规则，对交易意图执行全面检查
    
    用法：
        engine = RiskEngine()
        engine.add_rule(SingleTradeLimitRule(500000))
        engine.add_rule(ConfidenceThresholdRule(0.6))
        result = engine.check(trade_intent)
    """
    
    def __init__(self):
        """初始化引擎"""
        self._rules: List[RiskRule] = []  # 规则列表
    
    def add_rule(self, rule: RiskRule) -> None:
        """
        添加一条风控规则
        
        参数：
            rule: 实现了 RiskRule 接口的规则对象
        """
        self._rules.append(rule)
        print(f"✅ 风控规则已注册：{rule.rule_name}")
    
    def list_rules(self) -> List[str]:
        """列出所有已注册的规则名称"""
        return [(rule.rule_name, rule.description) for rule in self._rules]
    
    def check(self, intent: TradeIntent, context: dict = None) -> RiskEngineResult:
        """
        执行所有风控检查
        
        参数：
            intent: 交易意图
            context: 上下文信息（可选）
        
        返回：
            RiskEngineResult 汇总结果
        """
        if context is None:
            context = {}
        
        # 初始化汇总结果
        result = RiskEngineResult(
            intent_id=intent.intent_id,
            total_rules=len(self._rules)
        )
        
        # 逐条执行规则
        for rule in self._rules:
            # 执行单条规则检查
            check_result = rule.check(intent, context)
            result.results.append(check_result)
            
            # 统计
            if check_result.passed:
                result.passed_rules += 1
            else:
                if check_result.level == RiskLevel.BLOCK:
                    result.blocked_rules += 1
                    # 更新最高风险等级
                    if result.risk_level != RiskLevel.BLOCK:
                        result.risk_level = RiskLevel.BLOCK
                elif check_result.level == RiskLevel.WARNING:
                    result.warning_rules += 1
                    if result.risk_level == RiskLevel.PASS:
                        result.risk_level = RiskLevel.WARNING
        
        # 判断是否通过
        if result.blocked_rules > 0:
            result.passed = False
            result.summary = f"❌ 风控拦截：{result.blocked_rules} 条规则触发拦截"
        elif result.warning_rules > 0:
            result.passed = True  # 警告级别仍放行
            result.summary = f"⚠️ 风控警告：{result.warning_rules} 条规则触发警告，已放行"
        else:
            result.passed = True
            result.summary = f"✅ 风控通过：全部 {result.total_rules} 条规则检查通过"
        
        return result


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("风控模型测试")
    print("=" * 60)
    
    # 创建一个简单的测试规则
    class TestRule(RiskRule):
        """测试用规则：金额不能超过 100 万"""
        
        @property
        def rule_name(self) -> str:
            return "测试金额限制"
        
        @property
        def description(self) -> str:
            return "单笔交易金额不能超过 100 万元"
        
        def check(self, intent: TradeIntent, context: dict = None) -> RiskCheckResult:
            # 检查逻辑
            limit = 1_000_000  # 100 万限额
            if intent.total_amount > limit:
                return RiskCheckResult(
                    rule_name=self.rule_name,
                    level=RiskLevel.BLOCK,
                    passed=False,
                    message=f"交易金额 {intent.total_amount:,.0f} 超过限额 {limit:,.0f}",
                    details={"limit": limit, "actual": intent.total_amount}
                )
            return RiskCheckResult(
                rule_name=self.rule_name,
                level=RiskLevel.PASS,
                passed=True,
                message=f"交易金额 {intent.total_amount:,.0f} 在限额内"
            )
    
    # 测试引擎
    print("\n创建风控引擎...")
    engine = RiskEngine()
    engine.add_rule(TestRule())
    
    print(f"\n已注册规则：{engine.list_rules()}")
    
    # 测试 1：正常交易
    print("\n【测试 1】正常金额交易（应通过）")
    from trade_intent import TradeIntentBuilder
    intent_1 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(100, 1500.0)
                .with_reason("测试")
                .build())
    print(intent_1)
    result_1 = engine.check(intent_1)
    print(f"结果：{result_1.summary}")
    
    # 测试 2：超额交易
    print("\n【测试 2】超额交易（应拦截）")
    intent_2 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(10000, 1500.0)  # 1500 万
                .with_reason("测试")
                .build())
    print(intent_2)
    result_2 = engine.check(intent_2)
    print(f"结果：{result_2.summary}")