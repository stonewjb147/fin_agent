#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
聚合数据新闻抓取器（完整版 + 爬虫备用）
功能：
1. 通过聚合数据列表接口获取新闻列表
2. 优先通过聚合数据详情接口获取正文
3. 如果详情接口返回正文为空，则使用爬虫从 url 抓取完整正文
用法：python news_juhe_full_with_crawl.py
"""

import os
import sys
import time
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# 爬虫相关
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# 加载环境变量
load_dotenv()

# ============================================
# 配置
# ============================================

API_KEY = os.getenv("JUHE_NEWS_API_KEY")
if not API_KEY:
    print("❌ 未找到 JUHE_API_KEY，请在 .env 中设置")
    sys.exit(1)

# 聚合数据接口地址
LIST_URL = "http://v.juhe.cn/toutiao/index"
CONTENT_URL = "http://v.juhe.cn/toutiao/content"

# 新闻分类
NEWS_TYPE = "caijing"  # 财经

# 每页数量
PAGE_SIZE = 30

# 关键词过滤列表（本地过滤）
QUERIES = [
    
   "A股","创业板"    
]

# 请求间隔（秒），避免调用过快
REQUEST_INTERVAL = 0.5

# 爬虫请求头
CRAWL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 爬虫超时时间
CRAWL_TIMEOUT = 10


# ============================================
# 核心函数
# ============================================

def fetch_news_list():
    """获取新闻列表"""
    params = {
        "type": NEWS_TYPE,
        "key": API_KEY,
        "page": 1,
        "page_size": PAGE_SIZE
    }
    
    try:
        resp = requests.get(LIST_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("error_code") != 0:
            print(f"❌ 列表接口错误：{data.get('reason')}")
            return []
        
        articles = data.get("result", {}).get("data", [])
        print(f"✅ 获取到 {len(articles)} 条新闻列表")
        return articles
        
    except Exception as e:
        print(f"❌ 列表请求失败：{e}")
        return []


def fetch_news_content_api(uniquekey):
    """通过聚合数据详情接口获取正文"""
    if not uniquekey:
        return ""
    
    params = {
        "key": API_KEY,
        "uniquekey": uniquekey
    }
    
    try:
        resp = requests.get(CONTENT_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("error_code") != 0:
            return ""
        
        content = data.get("result", {}).get("content", "")
        return content
        
    except Exception:
        return ""


def fetch_content_from_url(url):
    """
    爬虫函数：从新闻 URL 抓取完整正文
    支持多种常见的新闻网站结构
    """
    if not url:
        return ""
    
    try:
        # 发送请求
        resp = requests.get(url, headers=CRAWL_HEADERS, timeout=CRAWL_TIMEOUT)
        resp.raise_for_status()
        # 自动检测编码
        resp.encoding = resp.apparent_encoding or 'utf-8'
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # ----- 方法1：移除干扰标签 -----
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()
        
        # ----- 方法2：按常见选择器查找正文 -----
        # 常见正文容器选择器（按优先级）
        selectors = [
            "article",                      # <article> 标签
            ".article-content",            # class 包含 article-content
            ".content",                    # class content
            "#content",                    # id content
            ".post-content",               # class post-content
            ".main-text",                  # class main-text
            ".news-content",               # class news-content
            ".detail-content",             # class detail-content
            ".article-body",               # class article-body
            ".main-content",               # class main-content
            ".entry-content",              # class entry-content
            ".rich_media_content",         # 微信公众号常见
        ]
        
        content_elem = None
        for selector in selectors:
            elems = soup.select(selector)
            if elems:
                # 选择第一个匹配的元素
                content_elem = elems[0]
                break
        
        if content_elem:
            # 从元素中提取纯文本
            text = content_elem.get_text(separator='\n', strip=True)
            # 清理多余空行
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)
            if len(text) > 100:  # 如果正文足够长，直接返回
                return text
        
        # ----- 方法3：如果没找到正文容器，提取所有 <p> 标签 -----
        paragraphs = soup.find_all('p')
        if paragraphs:
            # 过滤掉太短的段落（可能是导航、版权等）
            p_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if p_texts:
                text = '\n\n'.join(p_texts)
                if len(text) > 100:
                    return text
        
        # ----- 方法4：提取 body 中的主要文本（最粗糙） -----
        body = soup.find('body')
        if body:
            text = body.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)
            if len(text) > 200:
                return text
        
        return ""
        
    except requests.exceptions.Timeout:
        print("   ⏰ 爬虫超时")
        return ""
    except requests.exceptions.RequestException as e:
        print(f"   ❌ 爬虫请求失败：{e}")
        return ""
    except Exception as e:
        print(f"   ❌ 爬虫解析失败：{e}")
        return ""


def filter_articles(articles, keywords):
    """本地关键词过滤"""
    filtered = []
    for article in articles:
        title = article.get("title", "")
        desc = article.get("description", "") or article.get("content", "")
        for kw in keywords:
            if kw in title or kw in desc:
                filtered.append(article)
                break
    return filtered


def deduplicate_articles(articles):
    """按标题去重"""
    seen = set()
    unique = []
    for article in articles:
        title = article.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(article)
    return unique


# ============================================
# 主流程
# ============================================

def main():
    print("=" * 60)
    print("📰 聚合数据新闻抓取器（完整版 + 爬虫备用）")
    print("=" * 60)
    print(f"新闻分类：{NEWS_TYPE}")
    print(f"关键词过滤列表：{len(QUERIES)} 组")
    print()

    # ---- 1. 获取新闻列表 ----
    print("正在获取新闻列表...")
    articles = fetch_news_list()
    
    if not articles:
        print("❌ 未获取到任何新闻")
        sys.exit(1)

    # ---- 2. 本地关键词过滤 ----
    print(f"关键词过滤前：{len(articles)} 条")
    articles = filter_articles(articles, QUERIES)
    print(f"关键词过滤后：{len(articles)} 条")

    # ---- 3. 去重 ----
    articles = deduplicate_articles(articles)
    print(f"去重后：{len(articles)} 条")

    if not articles:
        print("⚠️ 过滤后无新闻，退出")
        sys.exit(0)

    # ---- 4. 逐条获取正文（API优先 + 爬虫备用） ----
    print("\n正在获取正文内容...")
    full_articles = []
    
    for i, article in enumerate(articles, 1):
        title = article.get("title", "无标题")
        uniquekey = article.get("uniquekey", "")
        url = article.get("url", "")
        
        print(f"  [{i}/{len(articles)}] {title[:30]}...", end=" ")
        
        # 第一步：尝试通过聚合数据详情接口获取正文
        content = fetch_news_content_api(uniquekey)
        
        # 第二步：如果正文为空且有 URL，尝试爬虫
        if not content and url:
            print("尝试爬虫...", end=" ")
            content = fetch_content_from_url(url)
        
        full_article = {
            "title": article.get("title", ""),
            "content": content,
            "source": article.get("author_name", ""),
            "publishedAt": article.get("date", ""),
            "url": article.get("url", ""),
            "category": article.get("category", ""),
            "uniquekey": uniquekey
        }
        full_articles.append(full_article)
        
        status = "✅" if content else "⚠️ 正文为空"
        print(status)
        
        # 控制请求频率
        time.sleep(REQUEST_INTERVAL)

    # ---- 5. 保存结果 ----
    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    os.makedirs(output_dir, exist_ok=True)
    
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"juhenews_full_crawl_{today}.json")
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(full_articles, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 新闻数据已保存到：{output_file}")
    
    # ---- 6. 统计 ----
    total = len(full_articles)
    with_content = sum(1 for a in full_articles if a.get("content"))
    print(f"   总新闻数：{total}")
    print(f"   有正文的新闻：{with_content}")
    print(f"   正文覆盖率：{with_content/total*100:.1f}%")

    # ---- 7. 预览 ----
    print("\n" + "=" * 60)
    print("📄 数据预览（前 3 条）")
    print("=" * 60)
    
    for i, article in enumerate(full_articles[:3], 1):
        print(f"\n--- 新闻 {i} ---")
        print(f"标题：{article.get('title', '无标题')}")
        print(f"来源：{article.get('source', '未知')}")
        print(f"时间：{article.get('publishedAt', '')[:10]}")
        print(f"正文预览：{article.get('content', '')[:100]}...")
    
    print("\n✅ 全部完成！")


if __name__ == "__main__":
    main()