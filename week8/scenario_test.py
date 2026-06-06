# ============================================
# 场景对比测试
# 测试智能体在不同市场环境下的表现
# 场景1：牛市（每天上涨 1-5%）
# 场景2：熊市（每天下跌 1-5%）
# 场景3：震荡市（涨跌互现）
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random
from etf_env import ETFSimEnv

def set_market_scenario(env: ETFSimEnv, scenario: str, day: int):
    """
    根据场景设置当日的市场行情

    参数：
        env: ETF 环境
        scenario: "bull"（牛市）、"bear"（熊市）、"volatile"（震荡）
        day: 第几天
    """
    for etf in env.etf_list:
        if scenario == "bull":
            # 牛市：每天涨 1% 到 5%
            change = random.uniform(0.01, 0.05)
        elif scenario == "bear":
            # 熊市：每天跌 1% 到 5%
            change = random.uniform(-0.05, -0.01)
        else:
            # 震荡：-3% 到 +3%
            change = random.uniform(-0.03, 0.03)

        etf.price = round(etf.price * (1 + change), 2)
        etf.change_pct = round(change * 100, 1)

    # 更新持仓价格
    for pos in env.positions.values():
        etf = env.etf_dict.get(pos.symbol)
        if etf:
            pos.current_price = etf.price

def print_scenario_header(scenario_name: str):
    """打印场景标题"""
    print("\n" + "=" * 60)
    print(f"📊 场景：{scenario_name}")
    print("=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 场景对比测试")
    print("=" * 60)
    print()
    print("本测试展示智能体在不同市场环境下的决策差异")
    print("注意：实际运行需要调用 LLM，这里先展示框架")
    print()

    # 展示三个场景的行情模拟
    for scenario, name in [("bull", "🐂 牛市（持续上涨）"), ("bear", "🐻 熊市（持续下跌）"), ("volatile", "📊 震荡市（涨跌互现）")]:
        print_scenario_header(name)
        env = ETFSimEnv(initial_cash=500000)
        set_market_scenario(env, scenario, 1)

        print("\n📋 当日行情：")
        for etf in env.etf_list:
            icon = "🔴" if etf.change_pct > 0 else "🟢"
            print(f"  {icon} {etf.symbol} {etf.name}：{etf.price:.2f}（{etf.change_pct:+.1f}%）")

        print(f"\n💡 预期智能体行为：")
        if scenario == "bull":
            print("   - 倾向于增加仓位")
            print("   - 偏好高 Beta 的行业 ETF")
            print("   - 可能触发集中度风控")
        elif scenario == "bear":
            print("   - 倾向于减仓或空仓")
            print("   - 可能转向债券 ETF")
            print("   - 风控会拦截追跌买入")
        else:
            print("   - 谨慎交易，等待明确信号")
            print("   - 可能做波段操作")
            print("   - 风控正常运作")

    print("\n" + "=" * 60)
    print("✅ 场景对比框架展示完成")
    print("=" * 60)