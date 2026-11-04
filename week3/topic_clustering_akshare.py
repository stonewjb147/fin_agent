#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻主题聚类脚本（适配 AKShare 混合数据）
功能：根据不同数据源（财经主接口、东方财富、新浪财经）自动提取标题和内容
输入：../data/news_akshare_*.json 或 akshare_news_*.json
输出：聚类结果 JSON + Markdown 报告
"""

import os
import sys
import json
import re
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ============================================
# 第 1 步：定位最新的新闻文件
# ============================================

print("=" * 60)
print("📊 AKShare 新闻主题聚类分析（智能字段识别版）")
print("=" * 60)

script_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(script_dir, "..", "data")
data_dir = os.path.abspath(data_dir)

json_files = []
for pattern in ["news_primary_"]:
    json_files.extend([
        f for f in os.listdir(data_dir)
        if f.startswith(pattern) and f.endswith(".json")
    ])

if not json_files:
    raise FileNotFoundError("未找到新闻数据文件，请先运行抓取脚本")

json_files.sort(reverse=True)
latest_file = os.path.join(data_dir, json_files[0])

print(f"\n加载数据：{latest_file}")

with open(latest_file, "r", encoding="utf-8") as f:
    articles = json.load(f)

print(f"总条数：{len(articles)}")

# ============================================
# 第 2 步：智能提取标题和内容（根据数据源）
# ============================================

def extract_text(article):
    """
    根据数据源智能提取标题和内容
    """
    source = article.get("source", "")
    title = ""
    content = ""

    if source == "财经主接口":
        title = article.get("tag", "")
        content = article.get("summary", "")

    elif source == "东方财富":
        title = article.get("新闻标题", "")
        content = article.get("新闻内容", "")

    elif source == "新浪财经":
        # 新浪财经的 title 可能是日期，真正标题在 content 开头
        title = article.get("title", "")
        content = article.get("content", "")
        # 如果 title 是日期或数字，从 content 提取第一句
        if title.isdigit() or title.startswith("202"):
            sentences = re.split(r'[。！？\n]', content.strip())
            if sentences and sentences[0]:
                title = sentences[0][:50]

    else:
        # 未知数据源：通用策略
        title = article.get("title") or article.get("tag") or article.get("新闻标题") or ""
        content = article.get("description") or article.get("summary") or article.get("content") or article.get("新闻内容") or ""

    # 如果标题为空，从内容截取前30字
    if not title and content:
        title = content[:30] + ("..." if len(content) > 30 else "")

    return title, content

print("\n开始提取文本...")
docs = []
valid_count = 0

for article in articles:
    title, content = extract_text(article)
    
    # 构建完整文本
    if title and content:
        full_text = f"{title}。{content}"
    elif title:
        full_text = title
    elif content:
        full_text = content
    else:
        full_text = ""

    if full_text and len(full_text.strip()) > 5:
        docs.append(full_text.strip())
        valid_count += 1
    else:
        docs.append("无内容")

print(f"有效文档数：{valid_count} / {len(articles)}")

# 预览前 5 条有效文档
print("\n文档预览（前 5 条，各显示 100 字）：")
for i, doc in enumerate(docs[:5], 1):
    print(f"  {i}. {doc[:100]}...")

# ============================================
# 第 3 步：BERTopic 聚类
# ============================================

from bertopic import BERTopic

print("\n" + "=" * 60)
print("正在进行主题聚类（约 30-60 秒）...")
print("=" * 60)

topic_model = BERTopic(
    language="multilingual",
    min_topic_size=3,
    verbose=True
)

topics, probs = topic_model.fit_transform(docs)

unique_topics = set(topics)
noise_count = list(topics).count(-1)
topic_count = len(unique_topics) - (1 if -1 in unique_topics else 0)

print(f"\n聚类完成！")
print(f"  识别主题数：{topic_count} 个")
print(f"  噪声文档数：{noise_count} 条")

# ============================================
# 第 4 步：输出主题信息
# ============================================

print("\n" + "=" * 60)
print("📌 主题关键词汇总")
print("=" * 60)

topic_info = topic_model.get_topic_info()
print(topic_info.to_string())

print("\n各主题 Top 5 关键词：")
for topic_id in sorted(set(topics)):
    if topic_id == -1:
        continue
    words = topic_model.get_topic(topic_id)
    if words:
        top_words = [w for w, _ in words[:5]]
        doc_count = sum(1 for t in topics if t == topic_id)
        print(f"\n主题 {topic_id}（{doc_count} 篇）：")
        print(f"  关键词：{' | '.join(top_words)}")

# ============================================
# 第 5 步：保存聚类结果
# ============================================

print("\n" + "=" * 60)
print("保存聚类结果")
print("=" * 60)

for i, article in enumerate(articles):
    if i < len(topics):
        article["topic_id"] = int(topics[i])
        article["topic_probability"] = round(float(probs[i]), 4) if i < len(probs) else 0.0
    else:
        article["topic_id"] = -1
        article["topic_probability"] = 0.0

today = datetime.now().strftime("%Y%m%d")
clustered_file = os.path.join(data_dir, f"news_clustered_akshare_{today}.json")

with open(clustered_file, "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print(f"聚类结果已保存：{clustered_file}")
print(f"文件大小：{os.path.getsize(clustered_file) / 1024:.1f} KB")

# ============================================
# 第 6 步：生成 Markdown 报告
# ============================================

report_lines = []
report_lines.append("# AKShare 新闻主题聚类报告")
report_lines.append("")
report_lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append(f"**新闻总数**：{len(articles)} 条")
report_lines.append(f"**识别主题数**：{topic_count} 个")
report_lines.append(f"**噪声文档数**：{noise_count} 条")
report_lines.append("")

report_lines.append("## 各主题详情")
report_lines.append("")

for topic_id in sorted(set(topics)):
    if topic_id == -1:
        continue

    words = topic_model.get_topic(topic_id)
    top_words = [w for w, _ in words[:5]]
    doc_count = sum(1 for t in topics if t == topic_id)

    report_lines.append(f"### 主题 {topic_id}：{' / '.join(top_words[:3])}")
    report_lines.append("")
    report_lines.append(f"- **文档数量**：{doc_count} 篇")
    report_lines.append(f"- **关键词**：{', '.join(top_words)}")
    report_lines.append("")

    # 代表性新闻
    topic_articles = []
    for i, t in enumerate(topics):
        if t == topic_id and i < len(articles):
            topic_articles.append(articles[i])

    topic_articles.sort(
        key=lambda x: x.get("topic_probability", 0),
        reverse=True
    )

    report_lines.append("- **代表性新闻**：")
    for article in topic_articles[:3]:
        # 根据数据源显示标题
        source = article.get("source", "")
        if source == "财经主接口":
            title = article.get("tag", "无标题")
        elif source == "东方财富":
            title = article.get("新闻标题", "无标题")
        elif source == "新浪财经":
            title = article.get("title", "无标题")
            if title.isdigit() or title.startswith("202"):
                # 如果标题是日期，取内容开头
                content = article.get("content", "")
                if content:
                    title = content[:30] + "..."
        else:
            title = article.get("title") or article.get("tag") or "无标题"
        prob = article.get("topic_probability", 0)
        report_lines.append(f"  - {title}（置信度：{prob:.2f})")
    report_lines.append("")

report_file = os.path.join(data_dir, f"akshare_topic_report_{today}.md")
with open(report_file, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print(f"Markdown 报告已保存：{report_file}")

print("\n" + "=" * 60)
print("✅ 全部完成！")
print("=" * 60)