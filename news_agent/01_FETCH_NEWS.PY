#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第四练 Day 1：新闻获取模块
功能：调用 GNews API 抓取金融新闻，保存为 JSON 文件
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

class NewsFetcher:
    def __init__(self):
        self.api_key = os.getenv("GNEWS_API_KEY")
        if not self.api_key:
            raise ValueError("请在 .env 中设置 GNEWS_API_KEY")
        self.base_url = "https://gnews.io/api/v4/search"

    def fetch_news(self, query: str = "stock market", language: str = "en",
                   from_date: Optional[str] = None, max_results: int = 20) -> List[Dict]:
        """
        抓取新闻
        :param query: 搜索关键词
        :param language: 语言 (en, zh, etc.)
        :param from_date: 起始日期 "2025-05-20"
        :param max_results: 最大条数 (GNews 免费版最多 100)
        :return: 新闻列表，每条包含 title, description, content, publishedAt, source
        """
        params = {
            "q": query,
            "lang": language,
            "country": "us",
            "max": min(max_results, 100),
            "apikey": self.api_key,
            "sortby": "publishedAt",
        }
        if from_date:
            # 转换为 GNews 需要的格式：2025-05-20T00:00:00Z
            params["from"] = f"{from_date}T00:00:00Z"

        response = requests.get(self.base_url, params=params)
        response.raise_for_status()
        data = response.json()

        articles = []
        for item in data.get("articles", []):
            articles.append({
                "title": item.get("title"),
                "description": item.get("description"),
                "content": item.get("content"),
                "publishedAt": item.get("publishedAt"),
                "source": item.get("source", {}).get("name"),
            })
        return articles

    def save_to_json(self, news_list: List[Dict], filename: str = None):
        if filename is None:
            filename = f"news_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(news_list, f, ensure_ascii=False, indent=2)
        print(f"✅ 已保存 {len(news_list)} 条新闻到 {filename}")
        return filename

    def load_from_json(self, filename: str) -> List[Dict]:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

# 验证代码
if __name__ == "__main__":
    fetcher = NewsFetcher()
    # 抓取最近2天的新闻
    since = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    news = fetcher.fetch_news(query="finance", language="en", from_date=since, max_results=10)
    print(f"抓取到 {len(news)} 条新闻")
    if news:
        print("第一条新闻标题:", news[0]["title"])
    # 保存
    fetcher.save_to_json(news)