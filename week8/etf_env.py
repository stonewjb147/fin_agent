# ============================================
# ETF 模拟交易环境
# 功能：模拟 ETF 交易，支持买入/卖出/持仓管理/收益计算
# 无真实资金风险，用于验证投资策略
# ============================================

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import random

@dataclass
class Position:
    """单笔持仓记录"""
    symbol: str          # ETF 代码
    name: str            # ETF 名称
    quantity: int        # 持有数量
    avg_cost: float      # 平均成本价
    current_price: float # 当前价格

    @property
    def market_value(self) -> float:
        """当前市值"""
        return self.quantity * self.current_price

    @property
    def profit_loss(self) -> float:
        """浮动盈亏"""
        return (self.current_price - self.avg_cost) * self.quantity

    @property
    def profit_loss_pct(self) -> float:
        """盈亏百分比"""
        return (self.current_price - self.avg_cost) / self.avg_cost if self.avg_cost > 0 else 0

@dataclass
class ETFData:
    """单只 ETF 的行情数据"""
    symbol: str
    name: str
    price: float
    change_pct: float     # 当日涨跌幅
    volume: int            # 成交量
    category: str          # 分类（宽基/行业/债券）

class ETFSimEnv:
    """
    ETF 模拟交易环境

    支持的操作：
    - 查看行情
    - 买入/卖出
    - 查看持仓
    - 计算收益
    """

    def __init__(self, initial_cash: float = 1_000_000):
        """
        初始化模拟环境

        参数：
            initial_cash: 初始资金（默认 100 万）
        """
        self.initial_cash = initial_cash        # 初始资金
        self.cash = initial_cash                 # 当前现金
        self.positions: Dict[str, Position] = {} # 持仓字典
        self.trade_history: List[Dict] = []      # 交易历史
        self._generate_market_data()              # 生成模拟行情

    def _generate_market_data(self):
        """生成模拟 ETF 行情数据"""
        self.etf_list = [
            ETFData("510050", "上证50ETF",     2.85,  0.5,  5000000, "宽基"),
            ETFData("510300", "沪深300ETF",     4.12, -0.3,  8000000, "宽基"),
            ETFData("159915", "创业板ETF",      2.35,  1.2,  6000000, "宽基"),
            ETFData("512880", "证券ETF",        0.95,  2.1,  12000000, "行业"),
            ETFData("512690", "酒ETF",          0.78,  3.5,  9000000, "行业"),
            ETFData("516160", "新能源ETF",      0.68, -1.8,  7000000, "行业"),
            ETFData("512010", "医药ETF",        0.52, -0.9,  5000000, "行业"),
            ETFData("511010", "国债ETF",       101.50, 0.05, 2000000, "债券"),
        ]
        self.etf_dict = {etf.symbol: etf for etf in self.etf_list}

    def get_quote(self, symbol: str) -> Optional[ETFData]:
        """查询 ETF 行情"""
        return self.etf_dict.get(symbol)

    def get_all_quotes(self) -> List[ETFData]:
        """获取所有 ETF 行情"""
        return self.etf_list

    def buy(self, symbol: str, quantity: int) -> Dict:
        """
        买入 ETF

        参数：
            symbol: ETF 代码
            quantity: 买入数量（股）

        返回：
            交易结果字典
        """
        etf = self.etf_dict.get(symbol)
        if not etf:
            return {"success": False, "message": f"未找到 ETF：{symbol}"}

        if quantity <= 0:
            return {"success": False, "message": "数量必须大于 0"}

        cost = etf.price * quantity
        if cost > self.cash:
            return {
                "success": False,
                "message": f"资金不足：需要 {cost:,.2f}，可用 {self.cash:,.2f}"
            }

        # 扣除现金
        self.cash -= cost

        # 更新持仓
        if symbol in self.positions:
            pos = self.positions[symbol]
            total_cost = pos.avg_cost * pos.quantity + cost
            pos.quantity += quantity
            pos.avg_cost = total_cost / pos.quantity
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                name=etf.name,
                quantity=quantity,
                avg_cost=etf.price,
                current_price=etf.price
            )

        # 记录交易
        trade = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "买入",
            "symbol": symbol,
            "name": etf.name,
            "quantity": quantity,
            "price": etf.price,
            "amount": cost,
            "cash_after": self.cash
        }
        self.trade_history.append(trade)

        return {"success": True, "message": f"买入 {etf.name} {quantity} 股，花费 {cost:,.2f}", "trade": trade}

    def sell(self, symbol: str, quantity: int) -> Dict:
        """
        卖出 ETF

        参数：
            symbol: ETF 代码
            quantity: 卖出数量（股）

        返回：
            交易结果字典
        """
        pos = self.positions.get(symbol)
        if not pos:
            return {"success": False, "message": f"未持有 {symbol}"}

        if quantity <= 0:
            return {"success": False, "message": "数量必须大于 0"}

        if quantity > pos.quantity:
            return {"success": False, "message": f"持仓不足：持有 {pos.quantity}，卖出 {quantity}"}

        etf = self.etf_dict.get(symbol)
        price = etf.price if etf else pos.current_price
        revenue = price * quantity

        # 增加现金
        self.cash += revenue

        # 更新持仓
        pos.quantity -= quantity
        if pos.quantity == 0:
            del self.positions[symbol]

        # 记录交易
        trade = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "卖出",
            "symbol": symbol,
            "name": pos.name,
            "quantity": quantity,
            "price": price,
            "amount": revenue,
            "cash_after": self.cash
        }
        self.trade_history.append(trade)

        return {"success": True, "message": f"卖出 {pos.name} {quantity} 股，获得 {revenue:,.2f}", "trade": trade}

    def get_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self.positions.values())

    def get_total_assets(self) -> float:
        """计算总资产（现金 + 持仓市值）"""
        market_value = sum(p.market_value for p in self.positions.values())
        return self.cash + market_value

    def get_summary(self) -> Dict:
        """获取账户摘要"""
        total_assets = self.get_total_assets()
        total_profit = total_assets - self.initial_cash
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_assets": total_assets,
            "total_profit": total_profit,
            "total_profit_pct": total_profit / self.initial_cash * 100,
            "position_count": len(self.positions),
            "trade_count": len(self.trade_history)
        }

    def print_summary(self):
        """打印账户摘要"""
        s = self.get_summary()
        print("\n" + "=" * 50)
        print("📊 账户摘要")
        print("=" * 50)
        print(f"初始资金：{s['initial_cash']:,.2f}")
        print(f"当前现金：{s['cash']:,.2f}")
        print(f"总资产：  {s['total_assets']:,.2f}")
        print(f"总收益：  {s['total_profit']:,.2f}（{s['total_profit_pct']:.2f}%）")
        print(f"持仓数：  {s['position_count']}")
        print(f"交易数：  {s['trade_count']}")
        if self.positions:
            print("\n持仓明细：")
            for pos in self.positions.values():
                icon = "🔴" if pos.profit_loss > 0 else "🟢"
                print(f"  {icon} {pos.name}({pos.symbol})：{pos.quantity}股 | 成本{pos.avg_cost:.2f} | 现价{pos.current_price:.2f} | 盈亏{pos.profit_loss:,.2f}")


if __name__ == "__main__":
    print("=" * 50)
    print("ETF 模拟环境测试")
    print("=" * 50)

    env = ETFSimEnv(initial_cash=500000)

    print("\n📋 可用 ETF：")
    for etf in env.get_all_quotes():
        icon = "🔴" if etf.change_pct > 0 else "🟢"
        print(f"  {icon} {etf.symbol} {etf.name}：{etf.price:.2f}（{etf.change_pct:+.1f}%）- {etf.category}")

    print("\n🔴 测试买入：")
    r1 = env.buy("512690", 10000)
    print(f"  {r1['message']}")
    r2 = env.buy("510300", 5000)
    print(f"  {r2['message']}")

    print("\n🟢 测试卖出：")
    r3 = env.sell("512690", 3000)
    print(f"  {r3['message']}")

    env.print_summary()

    print("\n✅ ETF 模拟环境测试完成")