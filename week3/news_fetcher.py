# ============================================
# 新闻抓取脚本
# 功能：从 NewsAPI 获取全球金融新闻，保存为 JSON
# 免费额度：每天 100 次请求
# ============================================

import os

#from week3.test_newsapi import app_key
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

import requests
import json
from datetime import datetime, timedelta

# ============================================
# 第一步：配置 API 参数
# ============================================

# 从 .env 读取密钥
NEWS_key = os.getenv("NEWSAPI_KEY")
if not NEWS_key:
    raise ValueError("请先在 .env 文件中设置 APP_key")

# 请求的基础 URL
BASE_URL = "https://newsapi.org/v2/everything"

# 我们要搜索的关键词（可以自己修改）
QUERIES = [
    "贵州茅台 OR 五粮液 OR 白酒",           # 白酒行业
    "A股 OR 上证指数 OR 深证成指",         # 中国股市
    "美联储 OR 利率 OR 央行",               # 宏观政策
    "新能源 OR 光伏 OR 锂电池",             # 热门板块
    "人民币汇率 OR 美元",                   # 汇率
]

# 每页返回的数量（免费版最多 100）
PAGE_SIZE = 20

# 搜索时间范围：最近 7 天
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

print("=" * 60)
print("📰 全球金融新闻抓取器")
print("=" * 60)
print(f"搜索时间范围：{START_DATE} 至 {END_DATE}")
print(f"搜索关键词：{len(QUERIES)} 组")
print()

# ============================================
# 第二步：抓取新闻
# ============================================

all_articles = []  # 存放所有新闻
total_fetched = 0  # 计数器

for query in QUERIES:
    print(f"正在搜索：{query}...")
    
    # 构建请求参数
    params = {
        "q": query,                    # 搜索关键词
        "from": START_DATE,            # 开始日期
        "to": END_DATE,                # 结束日期
        "language": "zh",              # 中文新闻
        "sortBy": "publishedAt",       # 按发布时间排序
        "pageSize": PAGE_SIZE,         # 每页数量
        "apiKey": NEWS_key         # API 密钥
    }
    
    try:
        # 发送 GET 请求
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()  # 如果请求失败则抛异常
        
        data = response.json()
        
        if data.get("status") == "ok":
            articles = data.get("articles", [])
            
            # 给每条新闻加上分类标签
            for article in articles:
                article["query_topic"] = query  # 记录是用哪个关键词搜到的
                all_articles.append(article)
            
            print(f"  ✅ 获取到 {len(articles)} 条新闻")
            total_fetched += len(articles)
        else:
            print(f"  ⚠️ API 返回异常：{data.get('message', '未知错误')}")
    
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 请求失败：{e}")

print()
print(f"共抓取 {total_fetched} 条新闻（去重前）")

# ============================================
# 第三步：去重（按标题去重）
# ============================================

seen_titles = set()
unique_articles = []

for article in all_articles:
    title = article.get("title", "")
    # 如果标题为空或已见过，跳过
    if not title or title in seen_titles:
        continue
    seen_titles.add(title)
    unique_articles.append(article)

print(f"去重后剩余 {len(unique_articles)} 条新闻")

# ============================================
# 第四步：保存为 JSON 文件
# ============================================

# 创建输出目录
output_dir = "../data"
os.makedirs(output_dir, exist_ok=True)

# 生成文件名（带日期）
today = datetime.now().strftime("%Y%m%d")
output_file = f"{output_dir}/news_{today}.json"

# 保存
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(unique_articles, f, ensure_ascii=False, indent=2)

print(f"\n✅ 新闻数据已保存到：{output_file}")
print(f"   文件大小：{os.path.getsize(output_file) / 1024:.1f} KB")

# ============================================
# 第五步：数据预览
# ============================================
print("\n" + "=" * 60)
print("📄 数据预览（前 3 条）")
print("=" * 60)

for i, article in enumerate(unique_articles[:3], 1):
    print(f"\n--- 新闻 {i} ---")
    print(f"标题：{article.get('title', '无标题')}")
    print(f"来源：{article.get('source', {}).get('name', '未知来源')}")
    print(f"时间：{article.get('publishedAt', '未知时间')[:10]}")
    print(f"描述：{article.get('description', '无描述')[:100]}...")

print("\n全部完成！")