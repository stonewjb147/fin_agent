#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
金融新闻抓取器（修复版）
数据源：东方财富快讯 + 正文爬虫（补充完整内容）
输出：统一格式的 JSON 文件，title 和 content 均有有效数据
"""

import os
import sys
import json
import time
import requests
from urllib.parse import urlparse
import pandas as pd
from datetime import datetime
import logging

# 尝试导入 akshare（东方财富数据源）
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logging.warning("akshare 未安装，请运行: pip install akshare")

# 尝试导入 BeautifulSoup（用于爬取正文）
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logging.warning("BeautifulSoup 未安装，正文爬取功能将受限，请运行: pip install beautifulsoup4 lxml")


# ============================================
# 配置
# ============================================

MAX_PER_SOURCE = 30
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================
# 工具函数：从 URL 爬取新闻正文
# ============================================

def fetch_article_content(url: str) -> str:
    """
    从新闻详情页爬取完整正文
    仅当 akshare 返回的 content 为空或过短时调用
    """
    if not url or not BS4_AVAILABLE:
        return ""
    
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 移除脚本和样式
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
            # 清理多余空行
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


# ============================================
# 数据源1：东方财富快讯（主要数据源）
# ============================================

def fetch_eastmoney_news(limit: int = MAX_PER_SOURCE) -> pd.DataFrame:
    """
    通过 akshare 获取东方财富快讯，并补充完整正文
    """
    if not AKSHARE_AVAILABLE:
        logger.error("akshare 未安装，无法获取东方财富数据")
        return pd.DataFrame()
    
    try:
        df = ak.stock_news_em()
        if df is None or df.empty:
            logger.warning("东方财富快讯返回空数据")
            return pd.DataFrame()
        
        # 调试：打印列名（确认字段）
        logger.info(f"东方财富列名: {df.columns.tolist()}")
        
        records = []
        for _, row in df.iterrows():
            # 提取标题（通常为 'title' 列）
            title = row.get('title', '') or row.get('新闻标题', '') or row.get('name', '')
            if not title:
                continue  # 跳过无标题的条目
            
            # 提取内容（可能为空或摘要）
            content = row.get('content', '') or row.get('新闻内容', '') or row.get('summary', '')
            url = row.get('url', '') or row.get('link', '') or row.get('新闻链接', '')
            pub_time = row.get('date', '') or row.get('发布时间', '') or row.get('pub_time', '')
            
            # 如果内容过短且 url 可用，尝试爬取完整正文
            if len(content) < 50 and url and BS4_AVAILABLE:
                logger.debug(f"内容过短，尝试爬取: {title[:30]}...")
                full_content = fetch_article_content(url)
                if full_content:
                    content = full_content
                    logger.debug("爬取成功")
                else:
                    # 若爬取失败，保留原内容（可能为摘要）
                    pass
            elif len(content) < 50 and not url:
                # 无 url，无法补充，标记为内容不足
                pass
            
            records.append({
                'title': title.strip(),
                'content': content.strip() if content else '',
                'pub_time': str(pub_time).strip() if pub_time else '',
                'url': url.strip() if url else '',
                'source': '东方财富'
            })
        
        df_result = pd.DataFrame(records)
        # 过滤掉内容为空的条目
        df_result = df_result[df_result['content'] != '']
        
        logger.info(f"✅ 东方财富：原始 {len(df)} 条，有效 {len(df_result)} 条")
        return df_result.head(limit)
        
    except Exception as e:
        logger.error(f"东方财富获取失败：{e}")
        return pd.DataFrame()


# ============================================
# 数据源2：财联社（备用，但已失效，保留占位）
# ============================================

# （财联社接口已确认失效，此函数仅为兼容旧代码保留，实际不会调用）
def fetch_cls_news(limit: int = MAX_PER_SOURCE) -> pd.DataFrame:
    logger.warning("财联社接口已失效，已跳过")
    return pd.DataFrame()


# ============================================
# 数据合并与去重
# ============================================

def deduplicate_articles(df: pd.DataFrame) -> pd.DataFrame:
    """按标题去重"""
    if df.empty:
        return df
    before = len(df)
    df = df.drop_duplicates(subset=['title'], keep='first')
    after = len(df)
    if before > after:
        logger.info(f"🔄 去重移除 {before - after} 条重复新闻")
    return df


# ============================================
# 保存数据
# ============================================

def save_news_data(df: pd.DataFrame, output_dir: str) -> str:
    """保存新闻数据到 JSON 文件"""
    os.makedirs(output_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"news_primary_{today}.json")
    
    records = df.to_dict(orient='records')
    for rec in records:
        if 'pub_time' in rec and hasattr(rec['pub_time'], 'strftime'):
            rec['pub_time'] = rec['pub_time'].strftime('%Y-%m-%d %H:%M:%S')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    logger.info(f"💾 数据已保存：{output_file}，共 {len(records)} 条")
    return output_file


# ============================================
# 主函数
# ============================================

def main():
    logger.info("=" * 60)
    logger.info("📰 金融新闻抓取器（修复版）")
    logger.info("=" * 60)
    logger.info("数据源：东方财富快讯 + 正文爬虫（补充完整内容）")
    logger.info("")
    
    all_dfs = []
    
    # 1. 东方财富（主要）
    logger.info("🔄 正在获取东方财富快讯...")
    df_em = fetch_eastmoney_news()
    if not df_em.empty:
        all_dfs.append(df_em)
    
    # 2. 财联社（已失效，跳过）
    # df_cls = fetch_cls_news()
    # if not df_cls.empty:
    #     all_dfs.append(df_cls)
    
    if not all_dfs:
        logger.error("❌ 所有数据源均失败，请检查网络和依赖")
        sys.exit(1)
    
    # 合并
    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(f"📊 合并后总条数：{len(combined)}")
    
    # 去重
    combined = deduplicate_articles(combined)
    logger.info(f"📊 去重后总条数：{len(combined)}")
    
    # 保存
    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    save_news_data(combined, output_dir)
    
    # 预览
    logger.info("\n📄 数据预览（前5条）：")
    for i, row in combined.head(5).iterrows():
        title = row.get('title', '')[:50]
        content_preview = row.get('content', '')[:30]
        src = row.get('source', '')
        logger.info(f"  {i+1}. {title}... ({src})")
        logger.info(f"     内容预览: {content_preview}...")
    
    logger.info("\n✅ 抓取完成！")


if __name__ == "__main__":
    main()