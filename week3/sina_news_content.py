#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新浪财经新闻抓取器（修正版）
支持 RSS 接口 + 快讯接口 + 爬虫正文
"""

import os
import sys
import time
import json
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================
# 配置
# ============================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://finance.sina.com.cn/"
}

QUERIES = [
    "航天", "AI", "半导体",
    "A股", "基金", "深证成指",
    "美联储", "利率", "央行",
    "新能源", "光伏", "锂电池",
    "人民币汇率", "美元"
]

REQUEST_INTERVAL = 1


# ============================================
# 方式一：RSS接口（修正版）
# ============================================

def fetch_news_via_rss(num: int = 30) -> list:
    """
    通过新浪财经RSS接口获取新闻列表
    接口：https://feed.mix.sina.com.cn/api/roll/get
    """
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {
        "pageid": 153,
        "lid": 2516,
        "num": min(num, 50),
        "page": 1
    }
    
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # 正确的判断路径
        result = data.get("result", {})
        status = result.get("status", {})
        
        if status.get("code") == 0:
            news_list = result.get("data", [])
            print(f"✅ RSS接口获取到 {len(news_list)} 条新闻")
            
            articles = []
            for item in news_list:
                # 处理时间字段（可能是时间戳或字符串）
                ctime = item.get("ctime", "")
                if isinstance(ctime, int):
                    ctime = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                
                articles.append({
                    "title": item.get("title", ""),
                    "description": item.get("summary", "") or item.get("content", ""),
                    "source": item.get("media_name", "新浪财经"),
                    "publishedAt": ctime,
                    "url": item.get("url", ""),
                    "uniquekey": item.get("docid", "") or str(item.get("id", ""))
                })
            return articles
        else:
            print(f"⚠️ RSS接口返回错误：{data}")
            return []
            
    except Exception as e:
        print(f"❌ RSS接口请求失败：{e}")
        return []


# ============================================
# 方式二：快讯接口
# ============================================

def fetch_news_via_flash(num: int = 20) -> list:
    """
    通过新浪财经快讯接口获取实时快讯
    """
    url = "https://feed.sina.com.cn/api/roll/get"
    params = {
        "pageid": 153,
        "lid": 2509,
        "num": min(num, 20),
        "page": 1
    }
    
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        result = data.get("result", {})
        status = result.get("status", {})
        
        if status.get("code") == 0:
            news_list = result.get("data", [])
            print(f"✅ 快讯接口获取到 {len(news_list)} 条快讯")
            
            articles = []
            for item in news_list:
                ctime = item.get("ctime", "")
                if isinstance(ctime, int):
                    ctime = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                
                articles.append({
                    "title": item.get("title", ""),
                    "description": item.get("content", "") or item.get("summary", ""),
                    "source": "新浪快讯",
                    "publishedAt": ctime,
                    "url": item.get("url", ""),
                    "uniquekey": item.get("docid", "") or str(item.get("id", ""))
                })
            return articles
        else:
            print(f"⚠️ 快讯接口返回错误：{data}")
            return []
            
    except Exception as e:
        print(f"❌ 快讯接口请求失败：{e}")
        return []


# ============================================
# 方式三：网页爬虫获取正文
# ============================================

def fetch_news_content_from_url(url: str) -> str:
    """从新闻详情页爬取正文"""
    if not url:
        return ""
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 移除干扰标签
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        
        # 查找正文容器
        selectors = [
            "article",
            ".article-content",
            ".content",
            "#content",
            ".article-body",
            ".main-content",
            ".entry-content",
            ".article",
            "#article",
            ".detail-content",
            ".news-content",
            ".article-content p",
            ".article-detail",
            ".article-body"
        ]
        
        content_elem = None
        for selector in selectors:
            elems = soup.select(selector)
            if elems:
                content_elem = elems[0]
                break
        
        if content_elem:
            text = content_elem.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)
            if len(text) > 100:
                return text
        
        # 备选：提取所有p标签
        paragraphs = soup.find_all('p')
        if paragraphs:
            p_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if p_texts:
                text = '\n\n'.join(p_texts)
                if len(text) > 100:
                    return text
        
        return ""
        
    except Exception as e:
        return ""


# ============================================
# 通用处理函数
# ============================================

def filter_articles(articles, keywords):
    filtered = []
    for article in articles:
        title = article.get("title", "")
        desc = article.get("description", "")
        for kw in keywords:
            if kw in title or kw in desc:
                filtered.append(article)
                break
    return filtered


def deduplicate_articles(articles):
    seen = set()
    unique = []
    for article in articles:
        title = article.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(article)
    return unique


# ============================================
# 主函数
# ============================================

def main():
    print("=" * 60)
    print("📰 新浪财经新闻抓取器（修正版）")
    print("=" * 60)
    print(f"关键词过滤列表：{len(QUERIES)} 组")
    print()

    all_articles = []

    # 1. RSS接口
    print("正在从RSS接口获取新闻...")
    rss_news = fetch_news_via_rss(num=30)
    if rss_news:
        all_articles.extend(rss_news)

    # 2. 快讯接口
    print("\n正在从快讯接口获取新闻...")
    flash_news = fetch_news_via_flash(num=20)
    if flash_news:
        all_articles.extend(flash_news)

    # 3. 去重
    print(f"\n合并后共 {len(all_articles)} 条")
    all_articles = deduplicate_articles(all_articles)
    print(f"去重后 {len(all_articles)} 条")

    # 4. 关键词过滤
    all_articles = filter_articles(all_articles, QUERIES)
    print(f"关键词过滤后 {len(all_articles)} 条")

    if not all_articles:
        print("⚠️ 无符合条件的新闻")
        sys.exit(0)

    # 5. 获取正文
    print("\n正在获取正文内容...")
    for i, article in enumerate(all_articles, 1):
        title = article.get("title", "无标题")[:30]
        print(f"  [{i}/{len(all_articles)}] {title}...", end=" ")
        
        # 如果已有description且足够长，直接使用
        desc = article.get("description", "")
        if desc and len(desc) > 100:
            article["content"] = desc
            print("✅")
            continue
        
        # 从URL爬取
        url = article.get("url", "")
        if url:
            content = fetch_news_content_from_url(url)
            article["content"] = content
            print("✅" if content else "⚠️ 正文为空")
        else:
            article["content"] = ""
            print("⚠️ 无URL")
        
        time.sleep(REQUEST_INTERVAL)

    # 6. 保存
    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    os.makedirs(output_dir, exist_ok=True)
    
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"sina_news_{today}.json")
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 新闻数据已保存到：{output_file}")
    
    total = len(all_articles)
    with_content = sum(1 for a in all_articles if a.get("content") and len(a.get("content", "")) > 50)
    print(f"   总新闻数：{total}")
    print(f"   有正文的新闻：{with_content}")
    print(f"   正文覆盖率：{with_content/total*100:.1f}%")


if __name__ == "__main__":
    main()