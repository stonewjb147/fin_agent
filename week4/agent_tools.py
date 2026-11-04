# ============================================
# 飞书机器人 Function Call 工具集
# 功能：定义智能体可以调用的所有工具函数
# 工具1：汇率查询（调用免费 API）
# 工具2：金融信号查询（读取本地 signals.jsonl）
# ============================================

import os
import json
import requests
from datetime import datetime

# ============================================
# 工具1：汇率查询
# ============================================



def query_exchange_rate(base_currency: str, target_currency: str) -> str:
    """
    查询两种货币之间的实时汇率
    
    参数：
        base_currency: 基础货币代码（如 CNY, USD, EUR）
        target_currency: 目标货币代码（如 CNY, USD, EUR）
    
    返回：
        汇率信息的文本描述
    
    使用的免费 API：ExchangeRate-API（无需注册，每天 1500 次免费调用）
    文档：https://github.com/fawazahmed0/exchange-api
    """
    try:
        # 使用免费的汇率 API
        # 这个 API 无需注册，直接 GET 即可
        url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base_currency.lower()}.json"
        
        # 发送 GET 请求
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 解析返回的 JSON
        data = response.json()
        
        # 获取目标货币的汇率
        target_code = target_currency.lower()
        if target_code in data.get(base_currency.lower(), {}):
            rate = data[base_currency.lower()][target_code]
            
            result = (
                f"💱 实时汇率查询结果\n"
                f"━━━━━━━━━━━━━━━\n"
                f"1 {base_currency.upper()} = {rate:.4f} {target_currency.upper()}\n"
                f"查询时间：{data.get('date', '最新日期')}\n"
                f"数据来源：ExchangeRate-API（免费）"
            )
            return result
        else:
            return f"❌ 未找到 {base_currency.upper()} → {target_currency.upper()} 的汇率数据"
    
    except requests.exceptions.Timeout:
        return "❌ 汇率查询超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        return f"❌ 汇率查询失败：{str(e)[:50]}"
    except Exception as e:
        return f"❌ 汇率查询异常：{str(e)[:50]}"


# ============================================
# 工具2：金融信号查询
# ============================================

def query_financial_signals(asset: str = "", direction: str = "", limit: int = 5) -> str:
    """
    查询最新的金融信号
    
    参数：
        asset: 要查询的资产/板块（如"白酒"、"新能源"，为空则返回所有）
        direction: 信号方向筛选（"看多"、"看空"、"中性"，为空则返回所有）
        limit: 最多返回几条信号（默认 5 条）
    
    返回：
        信号列表的文本描述
    """
    # 找到最新的信号文件
    data_dir = "/users/stonewjb/fin_agent_projects/data"
    
    # 查找所有 signals_ 开头的 jsonl 文件
    signal_files = [
        f for f in os.listdir(data_dir)
        if f.startswith("signals_") and f.endswith(".jsonl")
    ]
    
    if not signal_files:
        return "❌ 未找到信号数据文件，请先运行信号提取脚本"
    
    # 取最新的文件
    signal_files.sort(reverse=True)
    latest_file = os.path.join(data_dir, signal_files[0])
    
    # 加载信号数据
    signals = []
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        signal = json.loads(line)
                        # 只保留有效信号
                        if signal.get("is_valid", False):
                            signals.append(signal)
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        return "❌ 信号数据文件读取失败"
    
    if not signals:
        return "📭 当前没有有效的金融信号数据"
    
    # 按资产筛选
    if asset:
        signals = [
            s for s in signals
            if asset.lower() in s.get("asset", "").lower()
        ]
    
    # 按方向筛选
    if direction:
        signals = [
            s for s in signals
            if s.get("direction") == direction
        ]
    
    # 按置信度降序排序
    signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    
    # 取前 N 条
    signals = signals[:limit]
    
    if not signals:
        filter_desc = []
        if asset:
            filter_desc.append(f"板块={asset}")
        if direction:
            filter_desc.append(f"方向={direction}")
        return f"📭 没有找到匹配的信号（筛选条件：{', '.join(filter_desc)}）"
    
    # 构建返回文本
    result_lines = []
    result_lines.append(f"📊 最新金融信号（共 {len(signals)} 条）")
    result_lines.append("━━━━━━━━━━━━━━━")
    
    for i, signal in enumerate(signals, 1):
        # 方向图标
        dir_icon = {"看多": "🔴", "看空": "🟢", "中性": "⚪"}
        icon = dir_icon.get(signal.get("direction", ""), "⚪")
        
        result_lines.append(
            f"{i}. {icon} [{signal.get('direction', '')}] "
            f"{signal.get('asset', '未知')} "
            f"| 置信度：{signal.get('confidence', 0):.0%}"
        )
        result_lines.append(f"   {signal.get('summary', '无摘要')[:60]}")
        result_lines.append(f"   关键词：{', '.join(signal.get('keywords', [])[:4])}")
        result_lines.append("")
    
    result_lines.append(f"数据来源：{os.path.basename(latest_file)}")
    
    return "\n".join(result_lines)


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("工具函数测试")
    print("=" * 50)
    
    # 测试汇率查询
    print("\n【测试1】汇率查询：CNY → USD")
    result = query_exchange_rate("cny", "usd")
    print(result)
    
    # 测试信号查询（所有信号）
    print("\n【测试2】查询所有最新信号（前 3 条）")
    result = query_financial_signals(limit=3)
    print(result)
    
    # 测试信号查询（按板块筛选）
    print("\n【测试3】查询白酒板块看多信号")
    result = query_financial_signals(asset="白酒", direction="看多", limit=3)
    print(result)