# ============================================
# MCP 风格工具封装
# 将网络搜索、计算器、信号查询统一封装
# 并注册到 ToolRegistry
# ============================================

import os
import sys

# 把项目根目录加入路径，确保能导入 week5 下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json
import math
from tavily import TavilyClient
from tool_registry import ToolDefinition, ToolRegistry

# ============================================
# 初始化 Tavily 客户端
# ============================================

_tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", ""))

# ============================================
# 工具1：网络搜索
# ============================================

def _execute_search(query: str, max_results: int = 5) -> str:
    """网络搜索的执行函数"""
    try:
        response = _tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=True
        )
        
        lines = [f"🔍 搜索结果：{query}"]
        
        if response.get("answer"):
            lines.append(f"📌 摘要：{response['answer']}")
        
        for i, result in enumerate(response.get("results", []), 1):
            title = result.get("title", "无标题")
            url = result.get("url", "")
            content = result.get("content", "")[:200]
            lines.append(f"{i}. {title}")
            lines.append(f"   {url}")
            lines.append(f"   {content}...")
        
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 搜索失败：{str(e)[:100]}"


def _validate_search(params: dict) -> bool:
    """验证搜索参数"""
    return "query" in params and len(params["query"]) > 0


search_tool = ToolDefinition(
    name="网络搜索",
    description=(
        "在互联网上搜索最新信息。"
        "输入 JSON 格式：{\"query\": \"搜索关键词\", \"max_results\": 5}。"
        "当需要查询实时数据、新闻、公司财报时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"},
            "max_results": {"type": "integer", "description": "最大结果数，默认 5"}
        },
        "required": ["query"]
    },
    execute_func=_execute_search,
    validate_func=_validate_search
)


# ============================================
# 工具2：计算器
# ============================================

def _execute_calculator(expression: str) -> str:
    """计算器的执行函数"""
    safe_dict = {
        "abs": abs, "round": round, "max": max, "min": min,
        "sum": sum, "pow": pow,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(expression.strip(), {"__builtins__": {}}, safe_dict)
        if isinstance(result, float):
            return f"计算结果：{result:.4f}"
        return f"计算结果：{result}"
    except ZeroDivisionError:
        return "❌ 错误：不能除以零"
    except Exception as e:
        return f"❌ 计算失败：{str(e)[:50]}"


def _validate_calculator(params: dict) -> bool:
    """验证计算器参数"""
    return "expression" in params and len(params["expression"]) > 0


calculator_tool = ToolDefinition(
    name="计算器",
    description=(
        "执行数学计算。"
        "输入 JSON 格式：{\"expression\": \"数学表达式\"}。"
        "例如：{\"expression\": \"(800-650)/650*100\"} 计算增长率。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        },
        "required": ["expression"]
    },
    execute_func=_execute_calculator,
    validate_func=_validate_calculator
)


# ============================================
# 工具3：金融信号查询
# ============================================

def _execute_signals(asset: str = "") -> str:
    """信号查询的执行函数"""
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data"
    )
    
    signal_files = [
        f for f in os.listdir(data_dir)
        if f.startswith("signals_") and f.endswith(".jsonl")
    ]
    
    if not signal_files:
        return "暂无信号数据"
    
    signal_files.sort(reverse=True)
    latest_file = os.path.join(data_dir, signal_files[0])
    
    signals = []
    with open(latest_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    s = json.loads(line)
                    if s.get("is_valid", False):
                        signals.append(s)
                except json.JSONDecodeError:
                    continue
    
    if asset:
        signals = [s for s in signals if asset in s.get("asset", "")]
    
    signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    signals = signals[:10]
    
    if not signals:
        return f"未找到与'{asset}'相关的信号"
    
    lines = [f"📊 最新金融信号（共 {len(signals)} 条）"]
    for i, s in enumerate(signals, 1):
        lines.append(
            f"{i}. [{s.get('direction')}] {s.get('asset')} "
            f"| 置信度 {s.get('confidence', 0):.0%}"
        )
    
    return "\n".join(lines)


def _validate_signals(params: dict) -> bool:
    """信号查询参数验证（asset 是可选的）"""
    return True


signal_tool = ToolDefinition(
    name="金融信号查询",
    description=(
        "查询本地存储的最新金融信号。"
        "输入 JSON 格式：{\"asset\": \"板块名称\"}。"
        "例如：{\"asset\": \"白酒\"} 查询白酒板块信号。"
        "不填 asset 则返回所有信号。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "asset": {"type": "string", "description": "要查询的资产/板块名称，可选"}
        },
        "required": []
    },
    execute_func=_execute_signals,
    validate_func=_validate_signals
)


# ============================================
# 创建全局工具注册中心
# ============================================

registry = ToolRegistry()
registry.register(search_tool)
registry.register(calculator_tool)
registry.register(signal_tool)

# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("MCP 封装工具测试")
    print("=" * 50)
    
    print(f"\n已注册工具：{registry.list_names()}")
    
    # 测试搜索
    print("\n【测试1】网络搜索")
    result = registry.execute("网络搜索", {"query": "贵州茅台 2025 营收"})
    print(result[:300])
    
    # 测试计算器
    print("\n【测试2】计算器")
    result = registry.execute("计算器", {"expression": "(800-650)/650*100"})
    print(result)
    
    # 测试信号查询
    print("\n【测试3】信号查询")
    result = registry.execute("金融信号查询", {"asset": "白酒"})
    print(result[:300])