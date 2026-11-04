# ============================================
# 新闻抓取脚本（改用聚合数据 API）
# 功能：从聚合数据获取财经新闻，保存为 JSON
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

import requests
import json
from datetime import datetime, timedelta

# ============================================
# 第一步：配置 API 参数
# ============================================

# 从 .env 读取聚合数据 AppKey
API_KEY = os.getenv("JUHE_NEWS_API_KEY")
if not API_KEY:
    # 如果环境变量没有，直接使用你代码里的 Key（临时方案）
    API_KEY = "83687c7236471bf4cda9e33c6d6c0e24"

# 聚合数据新闻 API 的地址（正确）
BASE_URL = "http://v.juhe.cn/toutiao/index"

# 我们要搜索的关键词（用于本地过滤）
QUERIES = [
    "光模块", "存储", "半导体",
    "A股", "上证指数", "深证成指",
    "美联储", "利率", "央行",
    "新能源", "光伏", "锂电池",
    "人民币汇率", "美元","资金","AI"
]

# 聚合数据的新闻分类（财经类）
NEWS_TYPE = "caijing"  # 财经

# 每页返回的数量（聚合数据默认最大 50）
PAGE_SIZE = 30

print("=" * 60)
print("📰 聚合数据财经新闻抓取器")
print("=" * 60)
print(f"新闻分类：{NEWS_TYPE}")
print(f"关键词过滤列表：{len(QUERIES)} 组")
print()

# ============================================
# 第二步：抓取新闻
# ============================================

all_articles = []  # 存放所有新闻
total_fetched = 0  # 计数器

# 调用聚合数据 API（只调用一次，获取财经分类下的新闻）
params = {
    "type": NEWS_TYPE,
    "key": API_KEY,
    "page": 1,
    "page_size": PAGE_SIZE
}

print("正在从聚合数据获取财经新闻...")
try:
    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()
    
    data = response.json()
    
    if data.get("error_code") == 0:
        result = data.get("result", {})
        news_list = result.get("data", [])
        print(f"✅ 获取到 {len(news_list)} 条财经新闻")
        total_fetched += len(news_list)
        
        # 为每条新闻添加原始字段，并标准化
        for article in news_list:
            standardized = {
                "title": article.get("title", ""),
                "description": article.get("content", "")[:200],  # 内容可能较长
                "source": {"name": article.get("author_name", "聚合数据")},
                "publishedAt": article.get("date", ""),
                "url": article.get("url", ""),
                "category": article.get("category", ""),
            }
            all_articles.append(standardized)
    else:
        print(f"❌ API 返回错误：{data.get('reason')}")
        exit(1)

except requests.exceptions.RequestException as e:
    print(f"❌ 请求失败：{e}")
    exit(1)

print()
print(f"共抓取 {total_fetched} 条新闻")

# ============================================
# 第三步：本地关键词过滤（可选）
# ============================================

filtered_articles = []
if QUERIES:
    for article in all_articles:
        title = article.get("title", "")
        desc = article.get("description", "")
        # 如果标题或描述包含任一关键词，保留
        for kw in QUERIES:
            if kw in title or kw in desc:
                filtered_articles.append(article)
                break
    print(f"关键词过滤后剩余 {len(filtered_articles)} 条")
else:
    filtered_articles = all_articles

# ============================================
# 第四步：去重（按标题去重）
# ============================================

seen_titles = set()
unique_articles = []

for article in filtered_articles:
    title = article.get("title", "")
    if not title or title in seen_titles:
        continue
    seen_titles.add(title)
    unique_articles.append(article)

print(f"去重后剩余 {len(unique_articles)} 条新闻")

# ============================================
# 第五步：保存为 JSON 文件
# ============================================

# 创建输出目录
#import os

output_dir = os.path.expanduser("~/fin_agent_projects/data")
os.makedirs(output_dir, exist_ok=True)



# 生成文件名（带日期）
today = datetime.now().strftime("%Y%m%d")
output_file = f"{output_dir}/juhenews_{today}.json"

# 保存
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(unique_articles, f, ensure_ascii=False, indent=2)

print(f"\n✅ 新闻数据已保存到：{output_file}")
print(f"   文件大小：{os.path.getsize(output_file) / 1024:.1f} KB")

# ============================================
# 第六步：数据预览
# ============================================
print("\n" + "=" * 60)
print("📄 数据预览（前 3 条）")
print("=" * 60)

for i, article in enumerate(unique_articles[:3], 1):
    print(f"\n--- 新闻 {i} ---")
    print(f"标题：{article.get('title', '无标题')}")
    print(f"来源：{article.get('source', {}).get('name', '未知来源')}")
    print(f"时间：{article.get('publishedAt', '未知时间')[:10]}")
    print(f"描述：{article.get('description', '')[:100]}...")

print("\n全部完成！")