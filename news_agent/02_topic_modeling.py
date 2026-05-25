#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第四练 Day 2：BERTopic 主题建模
功能：加载新闻 JSON，进行主题聚类，保存模型和可视化
验证：打印主题统计，生成 HTML 文件
"""

import os
import json
import glob
from datetime import datetime
from bertopic import BERTopic
from sentence_transformers import SentenceTransformer

# 1. 找到最新的新闻 JSON 文件
json_files = glob.glob("news_*.json")
if not json_files:
    raise FileNotFoundError("未找到新闻 JSON 文件，请先运行 01_fetch_news.py")
latest_file = max(json_files, key=os.path.getctime)
print(f"✅ 加载新闻文件: {latest_file}")

with open(latest_file, 'r', encoding='utf-8') as f:
    news_list = json.load(f)

# 2. 提取文档（标题 + 描述）
docs = []
for item in news_list:
    title = item.get("title", "")
    desc = item.get("description", "")
    text = f"{title}. {desc}" if desc else title
    if len(text.strip()) > 20:
        docs.append(text.strip())
print(f"✅ 有效文档数: {len(docs)}")

# 3. 初始化 BERTopic（使用轻量级 embedding 模型）
embedding_model = SentenceTransformer("BAAI/bge-small-zh")  # 英文模型，速度快
topic_model = BERTopic(embedding_model=embedding_model, verbose=True)

# 4. 训练模型
print("🔄 正在训练 BERTopic 模型...")
topics, probs = topic_model.fit_transform(docs)
print(f"✅ 训练完成，发现 {len(set(topics)) - (1 if -1 in topics else 0)} 个主题（不含离群点）")

# 5. 打印主题信息
topic_info = topic_model.get_topic_info()
print("\n=== 主题聚类结果 ===")
print(topic_info[['Topic', 'Count', 'Name']].head(10))

# 6. 保存模型和可视化
topic_model.save("bertopic_model")
print("✅ 模型已保存到 ./bertopic_model")

# 生成交互式可视化
fig_topics = topic_model.visualize_topics()
fig_topics.write_html("topics_viz.html")
print("✅ 主题可视化已保存到 topics_viz.html")

fig_documents = topic_model.visualize_documents(docs)
fig_documents.write_html("documents_viz.html")
print("✅ 文档可视化已保存到 documents_viz.html")

# 7. 保存主题标签到新闻（可选）
for idx, topic in enumerate(topics):
    if idx < len(news_list):
        news_list[idx]['topic_id'] = int(topic)
        topic_keywords = topic_model.get_topic(topic)
        if topic_keywords:
            news_list[idx]['topic_keywords'] = [kw[0] for kw in topic_keywords[:5]]
        else:
            news_list[idx]['topic_keywords'] = []

# 保存带主题的新闻文件
output_file = f"news_with_topics_{datetime.now().strftime('%Y-%m-%d')}.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(news_list, f, ensure_ascii=False, indent=2)
print(f"✅ 带主题的新闻已保存到 {output_file}")

print("\n🎉 主题建模完成！")