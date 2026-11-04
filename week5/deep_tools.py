# ============================================
# Deep Agent 工具集
# 工具1：网络搜索（Tavily API）
# 工具2：计算器（Python 表达式求值）
# 这两个工具让 Agent 能自主搜索信息并进行计算对比
# ============================================

import os
from dotenv import load_dotenv
load_dotenv()

import math
import json
from tavily import TavilyClient

# ============================================
# 工具1：Tavily 网络搜索
# ============================================

# 初始化 Tavily 客户端（全局单例，避免重复创建）
_tavily_client = None

def _get_tavily_client():
    """获取 Tavily 客户端实例（懒加载：需要加载的时候调入内存）"""
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            raise ValueError("请先在 .env 中设置 TAVILY_API_KEY")
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client

def web_search(query: str) -> str:
    """
    在互联网上搜索信息，返回结构化的搜索结果
    
    参数：
        query: 搜索关键词或问题
    
    返回：
        包含搜索结果的文本摘要
        每条结果包含标题、URL、内容摘要
    
    这是 Agent 获取外部信息的主要途径
    """
    try:
        client = _get_tavily_client()
        
        # 调用 Tavily 搜索
        # search_depth="basic" 快速搜索，"advanced" 深度搜索
        # max_results=5 返回最多 5 条结果
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=True  # 包含 AI 生成的答案摘要
        )
        
        # 构建返回文本
        lines = []
        lines.append(f"🔍 搜索结果：{query}")
        lines.append("")
        
        # 如果有 AI 生成的答案摘要，先显示
        if response.get("answer"):
            lines.append(f"📌 摘要：{response['answer']}")
            lines.append("")
        
        # 逐条显示搜索结果
        results = response.get("results", [])
        for i, result in enumerate(results, 1):
            title = result.get("title", "无标题")
            url = result.get("url", "")
            content = result.get("content", "")[:200]
            lines.append(f"{i}. {title}")
            lines.append(f"   链接：{url}")
            lines.append(f"   内容：{content}...")
            lines.append("")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"❌ 搜索失败：{str(e)[:100]}"


# ============================================
# 工具2：Python 计算器
# ============================================

def calculator(expression: str) -> str:
    """
    安全的 Python 表达式计算器
    
    参数：
        expression: 数学表达式字符串，例如 "100 * 1.2 / 3"
    
    返回：
        计算结果字符串
    
    支持的运算：
        + - * / // % ** （加减乘除、整除、取余、乘方）
        以及 math 模块的函数：sqrt, log, sin, cos 等
    """
    # 白名单：只允许安全的函数和操作
    safe_dict = {
        "abs": abs,
        "round": round,
        "max": max,
        "min": min,
        "sum": sum,
        "pow": pow,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "pi": math.pi,
        "e": math.e,
    }
    
    try:
        # 清理表达式
        expression = expression.strip()
        
        # 使用 eval 在受限环境中计算
        result = eval(expression, {"__builtins__": {}}, safe_dict)
        
        # 格式化结果
        if isinstance(result, float):
            return f"计算结果：{result:.4f}"
        else:
            return f"计算结果：{result}"
    
    except ZeroDivisionError:
        return "❌ 错误：不能除以零"
    except SyntaxError:
        return f"❌ 表达式语法错误：{expression}"
    except Exception as e:
        return f"❌ 计算失败：{str(e)[:50]}"


# ============================================
# 工具3：加载本地信号数据（复用第三周成果）
# ============================================

def load_local_signals(asset: str = "") -> str:
    """
    加载最新的金融信号数据，用于 Agent 分析当前市场状况
    
    参数：
        asset: 要筛选的资产/板块名称，为空则返回全部
    
    返回：
        信号数据的文本摘要
    """
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data"
    )
    
    # 查找最新的信号文件
    signal_files = [
        f for f in os.listdir(data_dir)
        if f.startswith("signals_") and f.endswith(".jsonl")
    ]
    
    if not signal_files:
        return "暂无信号数据"
    
    signal_files.sort(reverse=True)
    latest_file = os.path.join(data_dir, signal_files[0])
    
    signals = []
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        signal = json.loads(line)
                        if signal.get("is_valid", False):
                            signals.append(signal)
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        return "信号文件读取失败"
    
    # 按资产筛选
    if asset:
        signals = [s for s in signals if asset in s.get("asset", "")]
    
    # 按置信度排序
    signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    signals = signals[:10]
    
    if not signals:
        return f"未找到与'{asset}'相关的信号"
    
    lines = [f"📊 最新金融信号（共 {len(signals)} 条）"]
    for i, s in enumerate(signals, 1):
        lines.append(
            f"{i}. [{s.get('direction')}] {s.get('asset')} "
            f"置信度 {s.get('confidence', 0):.0%} | {s.get('summary', '')[:50]}"
        )
    
    return "\n".join(lines)


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("Deep Agent 工具集测试")
    print("=" * 50)
    
    # 测试1：搜索
    print("\n【测试1】网络搜索：贵州茅台 2025 年营收")
    result = web_search("贵州茅台 2025 年营收")
    print(result[:500])
    
    # 测试2：计算器
    print("\n【测试2】计算器：100 * 1.2 / 3")
    result = calculator("100 * 1.2 / 3")
    print(result)
    
    # 测试3：加载信号
    print("\n【测试3】加载本地信号")
    result = load_local_signals()
    print(result[:300])