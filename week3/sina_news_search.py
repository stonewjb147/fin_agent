#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新浪财经新闻抓取器（关键词查询版 - 增强解析）
"""

import os
import sys
import time
import json
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://finance.sina.com.cn/"
}

SEARCH_KEYWORDS = ["航天", "AI", "人工智能", "半导体", "芯片", "光模块"]
REQUEST_INTERVAL = 1


def search_sina_news(keyword: str, num: int = 20) -> list:
    """搜索函数（健壮版）"""
    url = "https://search.sina.com.cn/roll/"
    params = {"q": keyword, "c": "news", "page": 1}
    
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 提取所有新闻链接
        links = soup.find_all('a', href=re.compile(r'(/doc-|/i-|/c/\d{4})'))
        if not links:
            # 备用：查找包含这些特征的父级容器
            containers = soup.select('[class*="result"], [class*="list"]')
            for container in containers:
                for a in container.find_all('a', href=True):
                    if '/doc-' in a['href'] or '/i-' in a['href']:
                        links.append(a)
        
        if not links:
            print(f"   ⚠️ 未找到新闻链接")
            return []
        
        seen = set()
        articles = []
        for a in links:
            link = a.get('href')
            if not link:
                continue
            if not link.startswith('http'):
                link = 'https:' + link if link.startswith('//') else 'https://' + link.lstrip('/')
            if link in seen:
                continue
            seen.add(link)
            
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            
            # 提取时间和来源
            parent = a.parent
            source = '新浪搜索'
            pub_time = ''
            if parent:
                texts = parent.get_text(separator=' ')
                time_match = re.search(r'\d{4}-\d{2}-\d{2}', texts)
                if time_match:
                    pub_time = time_match.group(0)
                source_match = re.search(r'[（(]([^）)]+)[）)]', texts)
                if source_match:
                    source = source_match.group(1)
            
            articles.append({
                "title": title,
                "description": "",
                "source": source,
                "publishedAt": pub_time,
                "url": link,
                "uniquekey": link.split('/')[-1].replace('.shtml', '') if '/doc-' in link else '',
            })
            if len(articles) >= num:
                break
        
        print(f"✅ 搜索关键词 '{keyword}' 找到 {len(articles)} 条")
        return articles
    except Exception as e:
        print(f"❌ 搜索失败：{e}")
        return []


def fetch_news_via_rss(num: int = 30) -> list:
    """备用：RSS栏目获取"""
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {"pageid": 153, "lid": 2516, "num": min(num, 50), "page": 1}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        result = data.get("result", {})
        status = result.get("status", {})
        if status.get("code") == 0:
            news_list = result.get("data", [])
            articles = []
            for item in news_list:
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
            print(f"✅ RSS备用获取 {len(articles)} 条")
            return articles
    except Exception as e:
        print(f"⚠️ RSS备用失败：{e}")
    return []


def fetch_news_content_from_url(url: str) -> str:
    """爬取正文"""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        selectors = [
            "article", ".article-content", ".content", "#content",
            ".article-body", ".main-content", ".entry-content", ".article",
            "#article", ".detail-content", ".news-content"
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
        paragraphs = soup.find_all('p')
        if paragraphs:
            p_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if p_texts:
                text = '\n\n'.join(p_texts)
                if len(text) > 100:
                    return text
        return ""
    except Exception:
        return ""


def main():
    print("=" * 60)
    print("📰 新浪财经新闻抓取器（关键词查询版 - 增强）")
    print("=" * 60)
    print(f"搜索关键词：{SEARCH_KEYWORDS}")
    print()

    all_articles = []

    # 1. 关键词搜索
    print("正在通过关键词搜索获取新闻...")
    for kw in SEARCH_KEYWORDS:
        print(f"  搜索：{kw}")
        articles = search_sina_news(kw, num=20)
        if articles:
            all_articles.extend(articles)
        time.sleep(REQUEST_INTERVAL)

    # 2. 备用方案（若搜索结果太少）
    if len(all_articles) < 5:
        print(f"\n搜索获取的新闻较少（{len(all_articles)}条），启用备用方案...")
        rss_news = fetch_news_via_rss(num=30)
        if rss_news:
            # 本地过滤
            filtered = []
            for article in rss_news:
                title = article.get("title", "")
                for kw in SEARCH_KEYWORDS:
                    if kw in title:
                        filtered.append(article)
                        break
            print(f"备用过滤后得到 {len(filtered)} 条")
            all_articles.extend(filtered)

    if not all_articles:
        print("❌ 未获取到任何新闻")
        sys.exit(0)

    # 去重
    seen = set()
    unique = []
    for a in all_articles:
        title = a.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(a)
    all_articles = unique
    print(f"\n去重后共 {len(all_articles)} 条新闻")

    # 获取正文
    print("\n正在获取正文内容...")
    for i, article in enumerate(all_articles, 1):
        title = article.get("title", "无标题")[:30]
        print(f"  [{i}/{len(all_articles)}] {title}...", end=" ")
        desc = article.get("description", "")
        if desc and len(desc) > 100:
            article["content"] = desc
            print("✅")
            continue
        url = article.get("url", "")
        if url:
            content = fetch_news_content_from_url(url)
            article["content"] = content
            print("✅" if content else "⚠️ 正文为空")
        else:
            article["content"] = ""
            print("⚠️ 无URL")
        time.sleep(REQUEST_INTERVAL)

    # 保存
    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    os.makedirs(output_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"sina_search_{today}.json")
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