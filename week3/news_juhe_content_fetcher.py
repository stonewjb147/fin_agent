#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻抓取脚本（API获取列表 + 爬虫抓取正文）
优势：不消耗额外API额度，可获取完整正文
"""

import os
import time
import requests
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 配置
# ============================================
JUHE_API_KEY = os.getenv("JUHE_NEWS_API_KEY")
if not JUHE_API_KEY:
    raise ValueError("请在 .env 文件中设置 JUHE_NEWS_API_KEY")

LIST_API_URL = "http://v.juhe.cn/toutiao/index"

# 常见的新闻正文提取规则（可扩展）
CONTENT_RULES = {
    "article": "article",
    ".content": "content",
    "#content": "content", 
    ".article-content": "article-content",
    ".post-content": "post-content",
    ".main-text": "main-text",
    ".news-content": "news-content",
    ".detail-content": "detail-content",
    ".article-body": "article-body",
    ".main-content": "main-content",
    ".entry-content": "entry-content"
}

print("=" * 60)
print("📰 新闻抓取器（API列表 + 爬虫正文）")
print("=" * 60)

# ============================================
# 函数1：获取新闻列表
# ============================================
def fetch_news_list(page_size=30):
    """从聚合数据获取新闻列表"""
    params = {
        "key": JUHE_API_KEY,
        "type": "caijing",
        "page": 1,
        "page_size": page_size
    }
    
    try:
        response = requests.get(LIST_API_URL, params=params, timeout=15)
        data = response.json()
        
        if data.get("error_code") == 0:
            articles = data.get("result", {}).get("data", [])
            print(f"✅ 获取到 {len(articles)} 条新闻列表")
            return articles
        else:
            print(f"❌ API错误: {data.get('reason')}")
            return []
    except Exception as e:
        print(f"❌ 异常: {e}")
        return []

# ============================================
# 函数2：爬虫抓取正文（核心）
# ============================================
def extract_news_content(url):
    """
    从新闻URL爬取正文内容
    支持：新浪、腾讯、网易、搜狐、凤凰等主流媒体
    """
    if not url:
        return ""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = response.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 方法1：按常见标签提取
        for selector in CONTENT_RULES.values():
            elements = soup.select(selector)
            if elements:
                # 提取正文，移除脚本和样式
                for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    script.decompose()
                
                # 获取纯文本
                text = elements[0].get_text(separator='\n', strip=True)
                # 清理多余空白行
                text = re.sub(r'\n\s*\n', '\n\n', text)
                if len(text) > 200:  # 确保不是空/过短
                    return text
        
        # 方法2：提取所有段落
        paragraphs = soup.find_all('p')
        if paragraphs:
            content = '\n'.join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            if len(content) > 200:
                return content
        
        # 方法3：提取body主要文本
        body = soup.find('body')
        if body:
            for tag in body(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = body.get_text(separator='\n', strip=True)
            text = re.sub(r'\n\s*\n', '\n\n', text)
            if len(text) > 200:
                return text
        
        return ""
        
    except requests.exceptions.Timeout:
        print(f"  ⏰ 超时: {url[:60]}...")
        return ""
    except Exception as e:
        print(f"  ❌ 爬取失败: {e}")
        return ""

# ============================================
# 主流程
# ============================================
def main():
    # 1. 获取新闻列表
    print("\n[1/3] 获取新闻列表...")
    news_list = fetch_news_list(page_size=20)
    
    if not news_list:
        print("未获取到新闻列表")
        return
    
    # 2. 爬取正文
    print(f"\n[2/3] 开始爬取 {len(news_list)} 条新闻的正文...")
    
    full_articles = []
    for i, article in enumerate(news_list, 1):
        title = article.get("title", "无标题")
        url = article.get("url", "")
        
        print(f"\n[{i}/{len(news_list)}] {title[:50]}...")
        
        if not url:
            print("    无URL，跳过")
            content = ""
        else:
            print(f"    爬取: {url[:80]}...")
            content = extract_news_content(url)
            print(f"    正文长度: {len(content)} 字符")
            time.sleep(1)  # 避免请求过快
        
        full_article = {
            "title": title,
            "content": content,
            "date": article.get("date", ""),
            "source": article.get("author_name", ""),
            "url": url,
            "category": article.get("category", "")
        }
        full_articles.append(full_article)
    
    # 3. 保存
    print("\n[3/3] 保存数据...")
    output_dir = "/users/stonewjb/fin_agent_projects/data"
    os.makedirs(output_dir, exist_ok=True)
    output_file = f"{output_dir}/news_with_crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(full_articles, f, ensure_ascii=False, indent=2)
    
    # 统计
    total = len(full_articles)
    has_content = sum(1 for a in full_articles if a.get("content") and len(a["content"]) > 200)
    
    print(f"\n✅ 保存完成: {output_file}")
    print(f"   总新闻数: {total} 条")
    print(f"   成功爬取正文: {has_content} 条")
    print(f"   成功率: {has_content/total*100:.1f}%")

if __name__ == "__main__":
    main()