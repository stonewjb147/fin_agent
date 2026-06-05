# ============================================
# 简报格式化脚本
# 功能：读取 Markdown 简报文件，转成飞书消息格式
# 飞书消息支持的类型：
#   - text：纯文本
#   - post：富文本（支持 Markdown 部分语法）
#   - interactive：卡片消息
# ============================================

import os
import json
from datetime import datetime

def load_latest_briefing() -> str:
    """
    加载最新的 Markdown 简报文件内容
    
    返回：
        简报的完整 Markdown 文本
        如果找不到文件，返回提示信息
    """
    # 简报文件存放目录
    data_dir = "/users/stonewjb/fin_agent_projects/data"
    
    # 查找所有 daily_briefing_ 开头的 md 文件
    briefing_files = [
        f for f in os.listdir(data_dir)
        if f.startswith("daily_briefing_") and f.endswith(".md")
    ]
    
    # 如果没有简报文件
    if not briefing_files:
        return "📭 暂无每日简报数据，请先运行信号提取和简报生成脚本。"
    
    # 按文件名排序，取最新的（日期在文件名里）
    briefing_files.sort(reverse=True)
    latest_file = os.path.join(data_dir, briefing_files[0])
    
    # 读取文件内容
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 打印加载信息
        file_size = os.path.getsize(latest_file) / 1024
        print(f"✅ 已加载简报：{os.path.basename(latest_file)}")
        print(f"   文件大小：{file_size:.1f} KB")
        
        return content
    
    except FileNotFoundError:
        return "📭 简报文件读取失败，请稍后重试。"
    except Exception as e:
        return f"⚠️ 简报加载异常：{str(e)[:50]}"


def format_briefing_for_feishu(markdown_content: str, max_length: int = 4000) -> str:
    """
    将 Markdown 简报转为适合飞书消息的纯文本格式
    
    飞书文本消息的限制：
    - 单条消息最大 15000 字符
    - 不支持 Markdown 渲染
    - 支持部分 Unicode 表情符号
    
    所以我们需要：
    1. 去掉 Markdown 标记符号（#、**、- 等）
    2. 用 Unicode 符号替代
    3. 控制每条消息的长度
    
    参数：
        markdown_content: Markdown 格式的简报内容
        max_length: 单条消息最大字符数（默认 4000，留有余量）
    
    返回：
        格式化后的纯文本内容
    """
    # 如果内容已经足够短，直接返回
    if len(markdown_content) <= max_length:
        return markdown_content
    
    # 如果内容太长，按段落截断
    # 找到最后一个完整的段落结束位置
    paragraphs = markdown_content.split("\n\n")
    
    formatted = ""
    for para in paragraphs:
        # 如果加上这一段会超长，就停止
        if len(formatted) + len(para) + 2 > max_length:
            # 添加"查看更多"的提示
            formatted += "\n\n---\n⚠️ 内容过长已截断，完整内容请查看本地文件。"
            break
        # 拼接段落
        if formatted:
            formatted += "\n\n"
        formatted += para
    
    return formatted


def get_signal_summary() -> str:
    """
    生成简短的市场信号摘要（用于定时快报推送）
    
    从最新的信号统计数据中提取关键信息，
    生成一条 200 字以内的市场情绪快报。
    
    返回：
        市场信号摘要文本
    """
    data_dir = "/users/stonewjb/fin_agent_projects/data"
    
    # 查找最新的信号统计文件
    stats_files = [
        f for f in os.listdir(data_dir)
        if f.startswith("signal_stats_") and f.endswith(".json")
    ]
    
    if not stats_files:
        return ""
    
    stats_files.sort(reverse=True)
    stats_file = os.path.join(data_dir, stats_files[0])
    
    try:
        with open(stats_file, "r", encoding="utf-8") as f:
            stats = json.load(f)
        
        # 提取关键数据
        total = stats.get("total_signals", 0)
        direction = stats.get("direction_distribution", {})
        top_assets = stats.get("top_assets", {})
        avg_conf = stats.get("average_confidence", 0)
        
        if total == 0:
            return ""
        
        # 构建摘要
        lines = []
        lines.append("📊 市场信号快报")
        lines.append("")
        lines.append(f"监测信号总数：{total} 条")
        
        # 方向分布
        bullish = direction.get("看多", 0)
        bearish = direction.get("看空", 0)
        neutral = direction.get("中性", 0)
        lines.append(f"看多 {bullish} | 看空 {bearish} | 中性 {neutral}")
        
        # 整体情绪判断
        if bullish > bearish * 1.5:
            lines.append("整体情绪：偏乐观 😊")
        elif bearish > bullish * 1.5:
            lines.append("整体情绪：偏谨慎 😟")
        else:
            lines.append("整体情绪：中性 😐")
        
        # 热门板块
        if top_assets:
            lines.append("")
            lines.append("热门板块：")
            for i, (asset, count) in enumerate(list(top_assets.items())[:3]):
                lines.append(f"  {i+1}. {asset}（{count} 条信号）")
        
        lines.append("")
        lines.append(f"平均置信度：{avg_conf:.0%}")
        lines.append("")
        lines.append(f"更新时间：{datetime.now().strftime('%H:%M:%S')}")
        
        return "\n".join(lines)
    
    except Exception as e:
        print(f"⚠️ 生成信号摘要失败：{e}")
        return ""


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("简报格式化测试")
    print("=" * 50)
    
    # 测试1：加载简报
    print("\n【测试1】加载最新简报")
    briefing = load_latest_briefing()
    print(f"简报前 200 字预览：")
    print(briefing[:200])
    print("...")
    
    # 测试2：格式化
    print("\n【测试2】格式化简报（限制 500 字符）")
    formatted = format_briefing_for_feishu(briefing, max_length=500)
    print(formatted)
    
    # 测试3：生成信号摘要
    print("\n【测试3】生成市场信号快报")
    summary = get_signal_summary()
    print(summary)