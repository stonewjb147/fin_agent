# ============================================
# 因子数据模型
# 功能：定义投资因子的标准数据结构
# 一个完整的因子包含：
#   - 元数据（名称、类型、描述）
#   - 计算逻辑（Python 代码）
#   - 验证信息（是否通过回测、夏普比率等）
# ============================================
"""
因子生产线：


提出想法 → 定义因子 → 回测验证 → 入库管理
┌─────────────────────────────────────────────────────────┐
│                    因子研发全流程                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ① 灵感产生                                              │
│     研究员发现：ROE高的公司长期收益更好                      │
│     ↓                                                   │
│  ② 因子定义（FactorDefinition 实例化）                     │
│     填写 name / code / data_requirements / parameters    │
│     ↓                                                   │
│  ③ 质量自检（is_valid）                                   │
│     检查必填字段、类型合法性、代码规范性                      │
│     ↓                                                   │
│  ④ 入库（to_json → 存入数据库）                            │
│     validation 状态 = "pending"                          │
│     ↓                                                   │
│  ⑤ 回测验证                                              │
│     用历史数据跑回测，计算夏普/年化收益/最大回撤               │
│     结果回填到 sharpe_ratio / annual_return / max_drawdown │
│     ↓                                                   │
│  ⑥ 状态更新                                              │
│     validation → "passed" 或 "failed"                    │
│     ↓                                                   │
│  ⑦ 投入使用                                              │
│     通过的因子进入实盘信号系统                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
"""

from dataclasses import dataclass, field, asdict  # 数据类装饰器
from typing import Optional, List  # 类型注解
from datetime import datetime  # 时间戳
import json  # JSON 序列化


@dataclass
class FactorDefinition:
    """
    因子定义数据类
    
    使用 @dataclass 装饰器自动生成 __init__、__repr__ 等方法
    
    属性说明：
    - name: 因子名称（英文，如 'high_roe'）
    - display_name: 因子显示名称（中文，如 '高ROE因子'）
    - description: 因子描述（一句话说明逻辑）
    - factor_type: 因子类型（基本面/技术面/情绪面/另类数据）
    - code: 因子计算代码（Python 表达式）
    - data_requirements: 所需数据字段列表
    - parameters: 因子参数（如阈值）
    - validation: 验证状态（pending/passed/failed）
    - sharpe_ratio: 回测夏普比率
    - annual_return: 年化收益率
    - max_drawdown: 最大回撤
    - created_at: 创建时间
    """
    
    # === 基本信息 ===
    name: str                              # 因子英文名
    display_name: str                      # 因子中文名
    description: str                       # 因子描述
    factor_type: str                       # 因子类型
    
    # === 计算逻辑 ===
    code: str                              # 因子代码（Python 表达式）
    data_requirements: List[str] = field(default_factory=list)  # 所需数据字段
    parameters: dict = field(default_factory=dict)              # 参数字典
    
    # === 验证信息（默认为空，验证后填充） ===
    validation: str = "pending"            # 验证状态
    sharpe_ratio: Optional[float] = None   # 夏普比率
    annual_return: Optional[float] = None  # 年化收益率
    max_drawdown: Optional[float] = None   # 最大回撤
    
    # === 元数据 ===
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    source_idea: str = ""                  # 来源想法
    
    # ============================================
    # 验证因子定义是否完整
    # ============================================
    def is_valid(self) -> bool:
        """
        检查因子定义是否完整（基本字段不为空）
        
        返回：
            True 表示因子定义有效
            False 表示缺少必要字段
        """
        # 检查必填字段
        if not self.name or len(self.name) == 0:
            return False
        if not self.code or len(self.code) == 0:
            return False
        if not self.factor_type or self.factor_type not in [
            "基本面", "技术面", "情绪面", "另类数据"
        ]:
            return False
        # 代码中必须包含 data 引用（说明因子需要数据）
        if "data" not in self.code:
            return False
        return True
    
    # ============================================
    # 转为字典（方便序列化和传给 LLM）
    # ============================================
    def to_dict(self) -> dict:
        """转为字典格式"""
        return asdict(self)
    
    # ============================================
    # 转为 JSON 字符串
    # ============================================
    def to_json(self) -> str:
        """转为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    # ============================================
    # 从 LLM 返回的 JSON 创建 FactorDefinition
    # ============================================
    @classmethod
    def from_llm_response(cls, response_json: dict) -> "FactorDefinition":
        """
        从 LLM 返回的 JSON 字典创建 FactorDefinition 实例
        
        参数：
            response_json: LLM 返回的 JSON 字典
        
        返回：
            FactorDefinition 实例
        """
        return cls(
            name=response_json.get("name", ""),
            display_name=response_json.get("display_name", ""),
            description=response_json.get("description", ""),
            factor_type=response_json.get("factor_type", "基本面"),
            code=response_json.get("code", ""),
            data_requirements=response_json.get("data_requirements", []),
            parameters=response_json.get("parameters", {}),
            source_idea=response_json.get("source_idea", "")
        )
    
    # ============================================
    # 友好的打印输出
    # ============================================
    def __repr__(self) -> str:
        """打印因子时的显示格式"""
        status_icon = {
            "pending": "⏳",
            "passed": "✅",
            "failed": "❌"
        }.get(self.validation, "❓")
        
        return (
            f"{status_icon} [{self.factor_type}] {self.display_name}\n"
            f"   名称: {self.name}\n"
            f"   描述: {self.description}\n"
            f"   代码: {self.code}"
        )


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("因子数据模型测试")
    print("=" * 60)
    
    # 创建一个测试因子
    factor = FactorDefinition(
        name="high_roe",
        display_name="高ROE因子",
        description="筛选净资产收益率大于15%的股票，ROE越高代表盈利能力越强",
        factor_type="基本面",
        code="factor = (data['roe'] > 0.15)",
        data_requirements=["roe"],
        parameters={"threshold": 0.15},
        source_idea="ROE > 15% 的股票长期表现更好"
    )
    
    # 打印因子
    print("\n因子对象：")
    print(factor)
    
    # 验证有效性
    print(f"\n因子有效性：{factor.is_valid()}")
    
    # 测试无效因子
    invalid_factor = FactorDefinition(
        name="",
        display_name="无效因子",
        description="测试",
        factor_type="基本面",
        code="",
        data_requirements=[],
        parameters={}
    )
    print(f"无效因子验证：{invalid_factor.is_valid()}（应为 False）")
    
    # 测试 JSON 序列化
    print(f"\nJSON 输出：")
    print(factor.to_json()[:300])