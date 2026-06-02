# ============================================
# 国内金融新闻抓取脚本（基于聚合数据 API）
# 功能：从聚合数据获取国内财经新闻，保存为 JSON
# 免费额度：每天 100 次调用，注册送 1000 次
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

# 从 .env 读取聚合数据 API Key
JUHE_API_KEY = os.getenv("JUHE_NEWS_API_KEY")
if not JUHE_API_KEY:
    raise ValueError("请先在 .env 文件中设置 JUHE_NEWS_API_KEY")

# 聚合数据新闻 API 的基础 URL
BASE_URL = "http://v.juhe.cn/toutiao/index"

# 我们要搜索的关键词（可以根据需要修改）
QUERIES = [
    "贵州茅台",     # 白酒龙头
    "A股",          # 中国股市
    "美联储",       # 宏观政策
    "新能源",       # 热门板块
    "人民币汇率",   # 汇率
]

# 每页返回的数量（聚合数据默认最多 40 条）
PAGE_SIZE = 20

print("=" * 60)
print("📰 国内金融新闻抓取器（聚合数据）")
print("=" * 60)
print(f"搜索关键词：{len(QUERIES)} 组")
print()

# ============================================
# 第二步：抓取新闻
# ============================================

all_articles = []  # 存放所有新闻
total_fetched = 0  # 计数器

for query in QUERIES:
    print(f"正在搜索：{query}...")
    
    # 聚合数据的请求参数
    params = {
        "key": JUHE_API_KEY,         # API 密钥
        "type": "caijing",           # 财经分类
        "page": 1,                   # 第一页
        "page_size": PAGE_SIZE,      # 每页数量
        "word": query,               # 搜索关键词
        "is_filter": 1               # 过滤重复
    }
    
    try:
        # 发送 GET 请求
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()  # 如果请求失败则抛异常
        
        data = response.json()
        
        # 聚合数据的返回格式
        # {
        #   "reason": "success",
        #   "result": {
        #     "stat": "1",
        #     "data": [...]
        #   }
        # }
        
        if data.get("reason") == "success":
            result = data.get("result", {})
            news_list = result.get("data", [])
            
            if news_list:
                # 给每条新闻加上搜索标签
                for article in news_list:
                    # 把聚合数据的字段名统一成我们之前定义的格式
                    standardized_article = {
                        "title": article.get("title", "无标题"),
                        "description": article.get("title", ""),  # 聚合数据没有单独描述
                        "source": {"name": article.get("category", "未知来源")},
                        "publishedAt": article.get("date", datetime.now().strftime("%Y-%m-%d")),
                        "url": article.get("url", ""),
                        "query_topic": query,
                        "author_name": article.get("author_name", "")
                    }
                    all_articles.append(standardized_article)
                
                print(f"  ✅ 获取到 {len(news_list)} 条新闻")
                total_fetched += len(news_list)
            else:
                print(f"  ⚠️ 没有返回新闻数据")
        else:
            error_msg = data.get("reason", "未知错误")
            print(f"  ❌ API 返回错误：{error_msg}")
    
    except requests.exceptions.Timeout:
        print(f"  ❌ 请求超时，跳过此关键词")
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 请求失败：{e}")

print()
print(f"共抓取 {total_fetched} 条新闻（去重前）")

# 如果聚合数据也没有数据，给出提示
if total_fetched == 0:
    print("\n⚠️ 未能获取到任何新闻。可能的原因：")
    print("  1. 聚合数据 API Key 无效或已过期")
    print("  2. 免费额度已用完（每天 100 次）")
    print("  3. 网络连接问题")
    print("  请检查 API Key 是否正确，或等待明天额度重置")

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
    print(f"搜索词：{article.get('query_topic', '')}")

print("\n全部完成！")