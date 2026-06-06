# ============================================
# 交易意图数据模型
# 功能：定义上游智能体发起的交易请求的标准格式
# 所有需要执行的交易都必须包装成 TradeIntent
# 风控引擎只接受 TradeIntent 格式的输入
# ============================================

from dataclasses import dataclass, field, asdict  # 数据类装饰器
from typing import Optional, List  # 类型注解
from datetime import datetime  # 时间戳
from enum import Enum  # 枚举类型
import json  # JSON 序列化


# ============================================
# 枚举类型定义
# ============================================

class TradeDirection(str, Enum):
    """交易方向枚举"""
    BUY = "买入"       # 买入
    SELL = "卖出"      # 卖出
    HOLD = "持有"      # 持有（不操作）


class AssetType(str, Enum):
    """资产类型枚举"""
    STOCK = "股票"          # 股票
    ETF = "ETF"             # ETF 基金
    BOND = "债券"           # 债券
    FUND = "基金"           # 普通基金


class IntentSource(str, Enum):
    """交易意图来源枚举"""
    FACTOR = "因子信号"          # 第7练：因子挖掘
    DEBATE = "辩论结论"          # 第8练：圆桌辩论
    NEWS = "新闻信号"            # 第4练：情报守望者
    RAG = "研报分析"             # 第3练：智能投研
    MANUAL = "人工指令"          # 人工输入


@dataclass
class TradeIntent:
    """
    交易意图数据类
    
    这是风控引擎的唯一输入格式。
    任何上游模块想要执行交易，都必须先生成一个 TradeIntent。
    
    属性说明：
    - intent_id: 意图唯一标识（自动生成）
    - symbol: 交易标的代码（如 600519.SH）
    - name: 交易标的名称（如 贵州茅台）
    - direction: 交易方向（买入/卖出/持有）
    - asset_type: 资产类型
    - quantity: 交易数量（股/份）
    - price: 预估价格
    - total_amount: 预估总金额（quantity × price）
    - source: 意图来源（哪个模块发起的）
    - confidence: 置信度（0.0-1.0）
    - reason: 交易理由（一句话说明）
    - supporting_evidence: 支撑证据列表
    - risk_score: 风险评分（由风控引擎填充）
    - created_at: 创建时间
    """
    
    # === 基本信息 ===
    intent_id: str = ""                           # 意图 ID（自动生成）
    symbol: str = ""                               # 交易标的代码
    name: str = ""                                 # 交易标的名称
    direction: TradeDirection = TradeDirection.HOLD  # 交易方向
    asset_type: AssetType = AssetType.STOCK        # 资产类型
    
    # === 交易细节 ===
    quantity: int = 0                              # 交易数量
    price: float = 0.0                             # 预估价格
    total_amount: float = 0.0                      # 预估总金额
    
    # === 来源信息 ===
    source: IntentSource = IntentSource.MANUAL     # 意图来源
    confidence: float = 0.0                        # 置信度（0-1）
    reason: str = ""                               # 交易理由
    
    # === 证据支撑 ===
    supporting_evidence: List[str] = field(default_factory=list)  # 支撑证据列表
    
    # === 风控信息（由风控引擎填充） ===
    risk_score: int = 0                            # 风险评分（0-100）
    risk_checks_passed: bool = True                # 是否通过风控检查
    risk_check_details: List[str] = field(default_factory=list)  # 风控检查详情
    
    # === 元数据 ===
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    # ============================================
    # 初始化后自动计算总金额和生成 ID
    # ============================================
    def __post_init__(self):
        """
        在数据类初始化后自动调用
        用于自动计算总金额和生成意图 ID
        """
        # 自动计算总金额
        if self.total_amount == 0.0 and self.quantity > 0:
            self.total_amount = round(self.quantity * self.price, 2)
        
        # 自动生成意图 ID
        if not self.intent_id:
            self.intent_id = f"INT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id(self) % 10000:04d}"
    
    # ============================================
    # 验证交易意图是否合法
    # ============================================
    def is_valid(self) -> tuple:
        """
        检查交易意图的基本字段是否合法
        
        返回：
            (是否有效, 错误信息列表)
        """
        errors = []
        
        # 标的代码不能为空
        if not self.symbol:
            errors.append("交易标的代码不能为空")
        
        # 标的名称不能为空
        if not self.name:
            errors.append("交易标的名称不能为空")
        
        # 交易数量必须大于 0
        if self.quantity <= 0:
            errors.append(f"交易数量必须大于 0（当前：{self.quantity}）")
        
        # 价格必须大于 0
        if self.price <= 0:
            errors.append(f"价格必须大于 0（当前：{self.price}）")
        
        # 总金额必须大于 0
        if self.total_amount <= 0:
            errors.append(f"总金额必须大于 0（当前：{self.total_amount}）")
        
        # 置信度必须在 0-1 之间
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"置信度必须在 0-1 之间（当前：{self.confidence}）")
        
        # 交易理由不能为空
        if not self.reason:
            errors.append("交易理由不能为空")
        
        return len(errors) == 0, errors
    
    # ============================================
    # 转为字典
    # ============================================
    def to_dict(self) -> dict:
        """转为字典格式"""
        d = asdict(self)
        # 枚举类型转为字符串
        d["direction"] = self.direction.value
        d["asset_type"] = self.asset_type.value
        d["source"] = self.source.value
        return d
    
    # ============================================
    # 转为 JSON
    # ============================================
    def to_json(self) -> str:
        """转为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    # ============================================
    # 友好的打印输出
    # ============================================
    def __repr__(self) -> str:
        """打印时的显示格式"""
        dir_icon = {"买入": "🔴", "卖出": "🟢", "持有": "⚪"}
        icon = dir_icon.get(self.direction.value, "❓")
        
        return (
            f"{icon} [{self.direction.value}] {self.name}({self.symbol})\n"
            f"   数量: {self.quantity} | 价格: {self.price:.2f} | 总金额: {self.total_amount:,.2f}\n"
            f"   来源: {self.source.value} | 置信度: {self.confidence:.0%}\n"
            f"   理由: {self.reason[:80]}"
        )


# ============================================
# 交易意图构建器（Builder 模式，方便创建）
# ============================================

class TradeIntentBuilder:
    """
    交易意图构建器
    
    使用 Builder 模式，让创建 TradeIntent 更直观
    
    用法：
        intent = (TradeIntentBuilder()
                  .set_symbol("600519.SH")
                  .set_name("贵州茅台")
                  .buy(100, 1500.0)
                  .from_factor("ROE因子", 0.85)
                  .with_reason("ROE超预期")
                  .build())
    """
    
    def __init__(self):
        """初始化构建器，设置默认值"""
        self._symbol = ""
        self._name = ""
        self._direction = TradeDirection.HOLD
        self._asset_type = AssetType.STOCK
        self._quantity = 0
        self._price = 0.0
        self._source = IntentSource.MANUAL
        self._confidence = 0.0
        self._reason = ""
        self._evidence = []
    
    def set_symbol(self, symbol: str) -> "TradeIntentBuilder":
        """设置交易标的代码"""
        self._symbol = symbol
        return self
    
    def set_name(self, name: str) -> "TradeIntentBuilder":
        """设置交易标的名称"""
        self._name = name
        return self
    
    def buy(self, quantity: int, price: float) -> "TradeIntentBuilder":
        """设置为买入"""
        self._direction = TradeDirection.BUY
        self._quantity = quantity
        self._price = price
        return self
    
    def sell(self, quantity: int, price: float) -> "TradeIntentBuilder":
        """设置为卖出"""
        self._direction = TradeDirection.SELL
        self._quantity = quantity
        self._price = price
        return self
    
    def from_factor(self, factor_name: str, confidence: float) -> "TradeIntentBuilder":
        """设置来源为因子信号"""
        self._source = IntentSource.FACTOR
        self._confidence = confidence
        self._evidence.append(f"因子信号：{factor_name}")
        return self
    
    def from_debate(self, winner: str, confidence: float) -> "TradeIntentBuilder":
        """设置来源为辩论结论"""
        self._source = IntentSource.DEBATE
        self._confidence = confidence
        self._evidence.append(f"辩论结论：{winner}获胜")
        return self
    
    def from_news(self, signal_summary: str, confidence: float) -> "TradeIntentBuilder":
        """设置来源为新闻信号"""
        self._source = IntentSource.NEWS
        self._confidence = confidence
        self._evidence.append(f"新闻信号：{signal_summary}")
        return self
    
    def with_reason(self, reason: str) -> "TradeIntentBuilder":
        """设置交易理由"""
        self._reason = reason
        return self
    
    def with_evidence(self, evidence: str) -> "TradeIntentBuilder":
        """添加支撑证据"""
        self._evidence.append(evidence)
        return self
    
    def build(self) -> TradeIntent:
        """构建 TradeIntent 对象"""
        return TradeIntent(
            symbol=self._symbol,
            name=self._name,
            direction=self._direction,
            asset_type=self._asset_type,
            quantity=self._quantity,
            price=self._price,
            source=self._source,
            confidence=self._confidence,
            reason=self._reason,
            supporting_evidence=self._evidence
        )


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("交易意图数据模型测试")
    print("=" * 60)
    
    # 测试 1：使用 Builder 创建买入意图
    print("\n【测试 1】使用 Builder 创建交易意图")
    intent_1 = (TradeIntentBuilder()
                .set_symbol("600519.SH")
                .set_name("贵州茅台")
                .buy(100, 1500.0)
                .from_factor("高ROE因子", 0.85)
                .with_reason("茅台ROE持续高于行业平均，盈利能力强")
                .with_evidence("ROE=25%，行业平均=12%")
                .build())
    
    print(intent_1)
    valid, errors = intent_1.is_valid()
    print(f"   有效性：{valid}")
    
    # 测试 2：创建卖出意图
    print("\n【测试 2】创建卖出意图")
    intent_2 = (TradeIntentBuilder()
                .set_symbol("000858.SZ")
                .set_name("五粮液")
                .sell(200, 120.0)
                .from_debate("空头", 0.72)
                .with_reason("消费降级趋势下高端白酒承压")
                .build())
    
    print(intent_2)
    
    # 测试 3：无效意图
    print("\n【测试 3】无效意图验证")
    intent_3 = TradeIntent()  # 所有字段都为空
    valid, errors = intent_3.is_valid()
    print(f"   有效性：{valid}")
    if errors:
        for err in errors:
            print(f"   ❌ {err}")
    
    # 测试 4：JSON 序列化
    print("\n【测试 4】JSON 输出")
    print(intent_1.to_json()[:400])