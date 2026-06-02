# ============================================
# 金融信号结构化数据模型
# 功能：定义从新闻中提取的投资信号的标准格式
# 每个信号包含：方向、资产、强度、置信度、摘要、来源
# ============================================

# 导入类型注解所需的库
from typing import Optional, List
from datetime import datetime
import json

# ============================================
# FinancialSignal 类：一条金融信号的完整定义
# ============================================
class FinancialSignal:
    """
    金融信号数据类
    
    属性说明：
    - direction: 信号方向，"看多"、"看空"或"中性"
    - asset: 涉及的资产或板块，如"白酒板块"、"新能源"、"A股"
    - strength: 信号强度，"高"、"中"、"低"
    - confidence: 置信度，0.0 到 1.0 之间的浮点数
    - summary: 信号一句话摘要，不超过 50 字
    - keywords: 关键触发词列表
    - source_title: 来源新闻标题
    - source_topic: 新闻所属主题编号
    - timestamp: 信号生成时间
    """
    
    def __init__(
        self,
        direction: str,          # 信号方向
        asset: str,              # 涉及资产/板块
        strength: str,           # 信号强度
        confidence: float,       # 置信度（0.0-1.0）
        summary: str,            # 一句话摘要
        keywords: List[str],     # 关键词列表
        source_title: str,       # 来源新闻标题
        source_topic: int,       # 来源主题编号
        timestamp: Optional[str] = None  # 时间戳（可选，默认当前时间）
    ):
        # 保存所有属性
        self.direction = direction
        self.asset = asset
        self.strength = strength
        self.confidence = confidence
        self.summary = summary
        self.keywords = keywords
        self.source_title = source_title
        self.source_topic = source_topic
        
        # 如果没传时间戳，自动使用当前时间
        if timestamp is None:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            self.timestamp = timestamp
    
    # ============================================
    # 验证信号是否有效
    # ============================================
    def is_valid(self) -> bool:
        """
        检查信号是否完整有效
        
        返回：
            True 如果信号所有必要字段都合法
            False 如果有任何字段不符合要求
        """
        # 方向必须是三者之一
        if self.direction not in ["看多", "看空", "中性"]:
            return False
        
        # 资产不能为空
        if not self.asset or len(self.asset) == 0:
            return False
        
        # 强度必须是三者之一
        if self.strength not in ["高", "中", "低"]:
            return False
        
        # 置信度必须在 0 到 1 之间
        if not (0.0 <= self.confidence <= 1.0):
            return False
        
        # 摘要不能为空
        if not self.summary or len(self.summary) == 0:
            return False
        
        # 关键词至少有一个
        if not self.keywords or len(self.keywords) == 0:
            return False
        
        return True
    
    # ============================================
    # 将信号转换为字典（方便存 JSON）
    # ============================================
    def to_dict(self) -> dict:
        """
        把信号对象转为 Python 字典
        
        返回：
            包含所有字段的字典
        """
        return {
            "direction": self.direction,
            "asset": self.asset,
            "strength": self.strength,
            "confidence": self.confidence,
            "summary": self.summary,
            "keywords": self.keywords,
            "source_title": self.source_title,
            "source_topic": self.source_topic,
            "timestamp": self.timestamp,
            "is_valid": self.is_valid()  # 同时保存验证结果
        }
    
    # ============================================
    # 将信号转换为 JSON 字符串
    # ============================================
    def to_json(self) -> str:
        """
        把信号转为 JSON 字符串
        
        返回：
            格式化的 JSON 字符串，ensure_ascii=False 保证中文正常显示
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    # ============================================
    # 字符串表示（print 时显示的内容）
    # ============================================
    def __repr__(self) -> str:
        """信号的简短描述"""
        return f"<FinancialSignal {self.direction} {self.asset} 强度={self.strength} 置信度={self.confidence}>"


# ============================================
# 测试代码：创建一条示例信号并验证
# ============================================
if __name__ == "__main__":
    # 创建一条示例信号
    test_signal = FinancialSignal(
        direction="看多",
        asset="白酒板块",
        strength="高",
        confidence=0.85,
        summary="茅台2025年净利润超预期增长20%，带动白酒板块看多情绪",
        keywords=["茅台", "净利润", "超预期", "白酒"],
        source_title="贵州茅台2025年净利润突破800亿",
        source_topic=0
    )
    
    # 打印信号
    print("示例信号：")
    print(test_signal.to_json())
    print()
    
    # 验证有效性
    print(f"信号有效性：{test_signal.is_valid()}")
    
    # 测试无效信号
    invalid_signal = FinancialSignal(
        direction="暴涨",      # 无效方向
        asset="",               # 空资产
        strength="极高",        # 无效强度
        confidence=1.5,         # 置信度超出范围
        summary="",
        keywords=[],
        source_title="测试",
        source_topic=0
    )
    print(f"\n无效信号测试：{invalid_signal.is_valid()}（应为 False）")