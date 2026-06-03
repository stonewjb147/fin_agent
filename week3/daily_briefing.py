# ============================================
# 每日金融简报生成脚本
# 功能：加载信号 JSONL，生成专业的 Markdown 简报
# 输入：signals_YYYYMMDD.jsonl + signal_stats_YYYYMMDD.json
# 输出：daily_briefing_YYYYMMDD.md
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import json
from datetime import datetime
from collections import Counter

print("=" * 60)
print("📝 每日金融简报生成器")
print("=" * 60)

data_dir = "/users/stonewjb/fin_agent_projects/data"
today = datetime.now().strftime("%Y%m%d")

# ============================================
# 第 1 步：加载信号数据
# ============================================

# 找到最新的信号文件
signal_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("signals_") and f.endswith(".jsonl")
]
signal_files.sort(reverse=True)
signal_file = os.path.join(data_dir, signal_files[0])

print(f"\n正在加载信号数据：{signal_file}")

signals = []
with open(signal_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                signals.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 跳过解析失败的行

print(f"成功加载 {len(signals)} 条信号")

# 只保留有效信号
valid_signals = [s for s in signals if s.get("is_valid", False)]
print(f"有效信号：{len(valid_signals)} 条")

# ============================================
# 第 2 步：加载统计分析
# ============================================

stats_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("signal_stats_") and f.endswith(".json")
]
stats_files.sort(reverse=True)

stats = {}
if stats_files:
    stats_file = os.path.join(data_dir, stats_files[0])
    with open(stats_file, "r", encoding="utf-8") as f:
        stats = json.load(f)
    print(f"加载统计分析：{stats_file}")

# ============================================
# 第 3 步：按方向分组
# ============================================

bullish = [s for s in valid_signals if s.get("direction") == "看多"]  # 利多信号
bearish = [s for s in valid_signals if s.get("direction") == "看空"]  # 利空信号
neutral = [s for s in valid_signals if s.get("direction") == "中性"]  # 中性信号

# 按置信度降序排序（重要信号排前面）
bullish.sort(key=lambda x: x.get("confidence", 0), reverse=True)
bearish.sort(key=lambda x: x.get("confidence", 0), reverse=True)

# ============================================
# 第 4 步：生成 Markdown 简报
# ============================================

lines = []

# --- 标题和摘要 ---
lines.append("# 📰 每日金融情报简报")
lines.append("")
lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append(f"**监测范围**：全网财经新闻")
lines.append(f"**信号总数**：{len(valid_signals)} 条有效信号")
lines.append("")

# --- 市场情绪概览 ---
lines.append("## 📊 市场情绪概览")
lines.append("")
lines.append("| 方向 | 数量 | 占比 | 情绪指示 |")
lines.append("|------|------|------|----------|")
lines.append(f"| 🔴 看多 | {len(bullish)} | {len(bullish)/max(len(valid_signals),1)*100:.1f}% | 利好信号 |")
lines.append(f"| 🟢 看空 | {len(bearish)} | {len(bearish)/max(len(valid_signals),1)*100:.1f}% | 利空信号 |")
lines.append(f"| ⚪ 中性 | {len(neutral)} | {len(neutral)/max(len(valid_signals),1)*100:.1f}% | 中性报道 |")
lines.append("")

# 情绪判断
if len(bullish) > len(bearish) * 1.5:
    sentiment = "偏乐观 😊"
    sentiment_desc = "看多信号明显多于看空信号，市场情绪偏积极"
elif len(bearish) > len(bullish) * 1.5:
    sentiment = "偏谨慎 😟"
    sentiment_desc = "看空信号明显多于看多信号，需关注风险"
else:
    sentiment = "中性 😐"
    sentiment_desc = "多空信号相对均衡，市场无明显倾向"

lines.append(f"**整体情绪**：{sentiment}")
lines.append(f"**判断依据**：{sentiment_desc}")
lines.append("")

# --- 热门板块 ---
if stats.get("top_assets"):
    lines.append("## 🔥 热门板块 Top 5")
    lines.append("")
    for i, (asset, count) in enumerate(stats["top_assets"].items(), 1):
        lines.append(f"{i}. **{asset}**：{count} 条相关信号")
    lines.append("")

# --- 重点利多信号 ---
lines.append("## 🔴 重点利多信号（Top 5）")
lines.append("")
if bullish:
    for i, signal in enumerate(bullish[:5], 1):
        lines.append(f"### {i}. {signal.get('asset', '未知板块')}")
        lines.append(f"- **信号强度**：{signal.get('strength', '未知')}")
        lines.append(f"- **置信度**：{signal.get('confidence', 0):.0%}")
        lines.append(f"- **摘要**：{signal.get('summary', '无')}")
        lines.append(f"- **关键词**：{', '.join(signal.get('keywords', []))}")
        lines.append(f"- **来源**：{signal.get('source_title', '')[:60]}...")
        lines.append("")
else:
    lines.append("*今日无看多信号*")
    lines.append("")

# --- 重点利空信号 ---
lines.append("## 🟢 重点利空信号（Top 5）")
lines.append("")
if bearish:
    for i, signal in enumerate(bearish[:5], 1):
        lines.append(f"### {i}. {signal.get('asset', '未知板块')}")
        lines.append(f"- **信号强度**：{signal.get('strength', '未知')}")
        lines.append(f"- **置信度**：{signal.get('confidence', 0):.0%}")
        lines.append(f"- **摘要**：{signal.get('summary', '无')}")
        lines.append(f"- **关键词**：{', '.join(signal.get('keywords', []))}")
        lines.append(f"- **来源**：{signal.get('source_title', '')[:60]}...")
        lines.append("")
else:
    lines.append("*今日无看空信号*")
    lines.append("")

# --- 置信度最高的信号 ---
lines.append("## ⭐ 高置信度信号（置信度 ≥ 80%）")
lines.append("")
high_conf = [s for s in valid_signals if s.get("confidence", 0) >= 0.8]
if high_conf:
    for signal in high_conf[:5]:
        lines.append(f"- [{signal.get('direction', '')}] **{signal.get('asset', '')}**：{signal.get('summary', '')}（置信度：{signal.get('confidence', 0):.0%}）")
else:
    lines.append("*今日无高置信度信号*")
lines.append("")

# --- 免责声明 ---
lines.append("---")
lines.append("")
lines.append("*本简报由 AI 自动生成，仅供参考，不构成任何投资建议。*")
lines.append(f"*数据来源：聚合数据新闻 API，生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

# ============================================
# 第 5 步：保存简报
# ============================================

briefing_file = f"{data_dir}/daily_briefing_{today}.md"
with open(briefing_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\n✅ 每日简报已保存到：{briefing_file}")
print(f"   文件大小：{os.path.getsize(briefing_file) / 1024:.1f} KB")

# ============================================
# 第 6 步：打印简报预览
# ============================================

print("\n" + "=" * 60)
print("📄 简报预览")
print("=" * 60)
print("\n".join(lines[:30]))  # 打印前 30 行作为预览
print("...")
print(f"\n完整内容请查看：{briefing_file}")

print("\n✅ 全部完成！")