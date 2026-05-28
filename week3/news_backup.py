# ============================================
# 备选新闻抓取脚本（使用免费 RSS，无需 API 密钥）
# ============================================

import os
import json
import requests
from datetime import datetime

print("📰 使用免费 RSS 源抓取新闻...")

# 免费的中文新闻 RSS 源
RSS_SOURCES = [
    # 1. 新浪财经 RSS（官方）
     "http://finance.sina.com.cn/stock/stockclass/roll_2024_00.shtml"
# 注意：新浪没有标准 RSS，需要解析 HTML

# 2. 掘金科技热榜
     "https://rsshub.app/juejin/trending/tech"

# 3. 知乎热榜
    "https://rsshub.app/zhihu/hotlist"
]

all_articles = []

for url in RSS_SOURCES:
    try:
        response = requests.get(url, timeout=10)
        # 简单解析 RSS（提取 title 和 description）
        content = response.text
        # 用字符串分割方式提取标题（简单但有效）
        titles = []
        for line in content.split("\n"):
            if "<title>" in line and "<![CDATA[" in line:
                title = line.split("<![CDATA[")[1].split("]]>")[0]
                titles.append(title)
        
        for title in titles:
            all_articles.append({
                "title": title,
                "source": {"name": url.split("/")[-1].replace(".xml", "")},
                "publishedAt": datetime.now().strftime("%Y-%m-%d"),
                "description": title,
                "query_topic": "财经新闻"
            })
        
        print(f"  ✅ {url} 获取到 {len(titles)} 条")
    except Exception as e:
        print(f"  ❌ {url} 失败：{e}")

# 保存
output_file = f"../data/news_{datetime.now().strftime('%Y%m%d')}.json"
os.makedirs("../data", exist_ok=True)
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_articles, f, ensure_ascii=False, indent=2)

print(f"\n✅ 共获取 {len(all_articles)} 条新闻，已保存到 {output_file}")