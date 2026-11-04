#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻数据聚合器（模块化版）
功能：
1. 将多个数据源（东方财富、财联社、Tavily等）封装为独立类
2. 统一数据格式（title, content, pub_time, url, source）
3. 支持正文爬虫增强（针对东方财富）
4. 可插拔，方便添加新数据源
5. 输出标准化 JSON 文件

作者: FinTech Expert
版本: 2.0
"""

import os
import sys
import json
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from abc import ABC, abstractmethod

import pandas as pd
import requests
from dotenv import load_dotenv

# 尝试导入可选依赖
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logging.warning("akshare 未安装，东方财富数据源不可用")
    logging.warning("请运行: pip install akshare")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logging.warning("BeautifulSoup 未安装，正文爬取功能受限")
    logging.warning("请运行: pip install beautifulsoup4 lxml")

try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    logging.warning("tavily-python 未安装，Tavily 数据源不可用")
    logging.warning("请运行: pip install tavily-python")

# 加载环境变量
load_dotenv()

# ============================================================
# 配置
# ============================================================

LOG_LEVEL = logging.INFO
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
MAX_RESULTS_PER_SOURCE = 30
OUTPUT_DIR = os.path.expanduser("~/fin_agent_projects/data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Tavily 配置（需在 .env 中设置 TAVILY_API_KEY）
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_TOPIC = "finance"
TAVILY_SEARCH_DEPTH = "basic"   # "basic" 或 "advanced"

# 配置日志
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 工具函数：爬取新闻正文（用于补充内容）
# ============================================================

def fetch_full_content(url: str, timeout: int = 10) -> str:
    """
    从新闻详情页爬取完整正文
    仅当内容为空或过短时调用
    """
    if not url or not BS4_AVAILABLE:
        return ""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 移除干扰标签
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        # 查找正文容器（常见选择器）
        selectors = [
            "article", ".article-content", ".content", "#content",
            ".article-body", ".main-content", ".entry-content",
            ".article", "#article", ".detail-content", ".news-content"
        ]
        content_elem = None
        for sel in selectors:
            elems = soup.select(sel)
            if elems:
                content_elem = elems[0]
                break
        if content_elem:
            text = content_elem.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)
            if len(text) > 100:
                return text
        # 备选：提取所有 p 标签
        paragraphs = soup.find_all('p')
        if paragraphs:
            p_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if p_texts:
                text = '\n\n'.join(p_texts)
                if len(text) > 100:
                    return text
        return ""
    except Exception as e:
        logger.debug(f"爬取正文失败 ({url}): {e}")
        return ""

# ============================================================
# 数据源基类
# ============================================================

class NewsSource(ABC):
    """所有新闻数据源的基类"""
    
    @abstractmethod
    def fetch(self, limit: int = 30) -> pd.DataFrame:
        """
        获取新闻数据，返回标准化 DataFrame
        必须包含列: title, content, pub_time, url, source
        """
        pass
    
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        pass

# ============================================================
# 具体数据源实现
# ============================================================

class EastmoneySource(NewsSource):
    """东方财富快讯（基于akshare）"""
    
    def name(self) -> str:
        return "东方财富"
    
    def fetch(self, limit: int = MAX_RESULTS_PER_SOURCE) -> pd.DataFrame:
        if not AKSHARE_AVAILABLE:
            logger.error("akshare 未安装，无法获取东方财富数据")
            return pd.DataFrame()
        
        try:
            df = ak.stock_news_em()
            if df is None or df.empty:
                logger.warning("东方财富快讯返回空数据")
                return pd.DataFrame()
            
            records = []
            for _, row in df.iterrows():
                title = row.get('title', '') or row.get('新闻标题', '') or row.get('name', '')
                if not title:
                    continue
                content = row.get('content', '') or row.get('新闻内容', '') or row.get('summary', '')
                url = row.get('url', '') or row.get('link', '') or row.get('新闻链接', '')
                pub_time = row.get('date', '') or row.get('发布时间', '') or row.get('pub_time', '')
                
                # 内容增强：如果内容过短且有 URL，尝试爬取
                if len(content) < 50 and url and BS4_AVAILABLE:
                    full = fetch_full_content(url)
                    if full:
                        content = full
                
                if not content:
                    continue  # 跳过无内容条目
                
                records.append({
                    'title': title.strip(),
                    'content': content.strip(),
                    'pub_time': str(pub_time).strip() if pub_time else '',
                    'url': url.strip() if url else '',
                    'source': self.name()
                })
            
            df_result = pd.DataFrame(records)
            logger.info(f"✅ 东方财富: 获取 {len(df_result)} 条")
            return df_result.head(limit)
        except Exception as e:
            logger.error(f"东方财富获取失败: {e}")
            return pd.DataFrame()


class TavilySource(NewsSource):
    """Tavily 实时搜索（需 API Key）"""
    
    def __init__(self, keywords: List[str]):
        self.keywords = keywords
        self._client = None
    
    def name(self) -> str:
        return "Tavily"
    
    def _get_client(self):
        if self._client is None:
            if not TAVILY_API_KEY:
                raise ValueError("未设置 TAVILY_API_KEY")
            self._client = TavilyClient(api_key=TAVILY_API_KEY)
        return self._client
    
    def fetch(self, limit: int = 30) -> pd.DataFrame:
        if not TAVILY_AVAILABLE:
            logger.error("tavily-python 未安装")
            return pd.DataFrame()
        if not TAVILY_API_KEY:
            logger.error("未设置 TAVILY_API_KEY，无法使用 Tavily")
            return pd.DataFrame()
        
        client = self._get_client()
        all_results = []
        seen_urls = set()
        
        for query in self.keywords:
            try:
                logger.info(f"  Tavily 搜索: {query}")
                response = client.search(
                    query=query,
                    search_depth=TAVILY_SEARCH_DEPTH,
                    max_results=limit // max(1, len(self.keywords)),
                    topic=TAVILY_TOPIC,
                    include_answer=False,
                    include_raw_content=False,
                )
                results = response.get("results", [])
                for item in results:
                    url = item.get("url")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    all_results.append({
                        'title': item.get('title', ''),
                        'content': item.get('content', ''),
                        'pub_time': item.get('published', ''),
                        'url': url,
                        'source': self.name()
                    })
                # 控制请求频率
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Tavily 搜索失败 ({query}): {e}")
        
        df = pd.DataFrame(all_results)
        logger.info(f"✅ Tavily: 获取 {len(df)} 条")
        return df.head(limit)


class ClsSource(NewsSource):
    """财联社（已失效，保留占位）"""
    
    def name(self) -> str:
        return "财联社"
    
    def fetch(self, limit: int = 30) -> pd.DataFrame:
        logger.warning("财联社接口已失效，返回空数据")
        return pd.DataFrame()

# ============================================================
# 聚合器主类
# ============================================================

class NewsAggregator:
    """
    新闻数据聚合器
    管理多个数据源，合并去重，输出统一格式
    """
    
    def __init__(self, sources: List[NewsSource]):
        self.sources = sources
    
    def fetch_all(self, limit_per_source: Optional[int] = None) -> pd.DataFrame:
        """抓取所有源数据并合并"""
        all_dfs = []
        for src in self.sources:
            logger.info(f"🔄 正在获取 {src.name()} ...")
            df = src.fetch(limit=limit_per_source or MAX_RESULTS_PER_SOURCE)
            if not df.empty:
                all_dfs.append(df)
        if not all_dfs:
            return pd.DataFrame()
        combined = pd.concat(all_dfs, ignore_index=True)
        # 去重（按标题）
        before = len(combined)
        combined = combined.drop_duplicates(subset=['title'], keep='first')
        after = len(combined)
        if before > after:
            logger.info(f"🔄 去重移除 {before - after} 条")
        return combined
    
    def save(self, df: pd.DataFrame, filename_prefix: str = "news") -> str:
        """保存 DataFrame 到 JSON"""
        if df.empty:
            logger.warning("无数据可保存")
            return ""
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        output_file = os.path.join(OUTPUT_DIR, f"{filename_prefix}_{today}.json")
        records = df.to_dict(orient='records')
        # 处理时间字段
        for rec in records:
            if 'pub_time' in rec and hasattr(rec['pub_time'], 'strftime'):
                rec['pub_time'] = rec['pub_time'].strftime('%Y-%m-%d %H:%M:%S')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 数据已保存: {output_file}，共 {len(records)} 条")
        return output_file
    
    def run(self, filename_prefix: str = "news") -> pd.DataFrame:
        """执行完整流程：抓取 → 合并 → 去重 → 保存 → 返回 DataFrame"""
        df = self.fetch_all()
        if df.empty:
            logger.error("所有数据源均失败")
            return df
        self.save(df, filename_prefix)
        # 预览
        logger.info("\n📄 数据预览（前5条）：")
        for i, row in df.head(5).iterrows():
            title = row.get('title', '')[:40]
            src = row.get('source', '')
            logger.info(f"  {i+1}. {title}... ({src})")
        return df

# ============================================================
# 主函数：构建聚合器并运行
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("📰 新闻数据聚合器（模块化版）")
    logger.info("=" * 60)
    
    # 1. 配置数据源列表
    sources = []
    
    # 东方财富（必选）
    sources.append(EastmoneySource())
    
    # Tavily（可选，需配置关键词）
    tavily_keywords = [
        "A股 热点 板块",
        "美股 科技股",
        "半导体 芯片",
        "新能源 光伏",
        "美联储 政策",
    ]
    if TAVILY_AVAILABLE and TAVILY_API_KEY:
        sources.append(TavilySource(tavily_keywords))
    else:
        logger.warning("Tavily 不可用，跳过 (需要安装 tavily-python 并设置 TAVILY_API_KEY)")
    
    # 财联社（已失效，可注释掉）
    # sources.append(ClsSource())
    
    # 2. 创建聚合器并运行
    aggregator = NewsAggregator(sources)
    df = aggregator.run(filename_prefix="news_primary")
    
    # 3. 可选：生成简单统计
    if not df.empty:
        logger.info("\n📊 来源统计：")
        cnt = df['source'].value_counts()
        for src, c in cnt.items():
            logger.info(f"   {src}: {c} 条")
    
    logger.info("\n✅ 聚合完成！")

if __name__ == "__main__":
    main()