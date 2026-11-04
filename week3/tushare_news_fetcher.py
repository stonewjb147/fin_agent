#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tushare 财经新闻抓取器（环境变量版）
功能：基于关键词检索财经新闻，支持多数据源、时间范围过滤
数据来源：新浪财经、华尔街见闻、同花顺、东方财富、财联社等
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
import pandas as pd
import tushare as ts
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ============================================
# 配置
# ============================================

# 从环境变量读取 Tushare Token
TUSHARE_TOKEN = os.getenv("token")
if not TUSHARE_TOKEN:
    print("❌ 未在 .env 文件中找到 TUSHARE_TOKEN")
    print("   请在项目根目录创建 .env 文件，并添加：")
    print("   TUSHARE_TOKEN=你的Token")
    sys.exit(1)

# 搜索关键词列表
SEARCH_KEYWORDS = [
    "航天", "AI", "人工智能", "半导体", "芯片", "光模块",
    "新能源", "光伏", "锂电池", "储能"
]

# 新闻来源（可选，不指定则获取所有来源）
# 可选值：sina, wallstreetcn, 10jqka, eastmoney, cls, yicai 等
NEWS_SOURCES = ["sina", "eastmoney", "cls", "10jqka"]

# 查询天数（往前推 N 天）
QUERY_DAYS = 7

# 每条新闻的最大正文长度
MAX_CONTENT_LENGTH = 5000

# 请求间隔（秒）
REQUEST_INTERVAL = 1


# ============================================
# 初始化 Tushare
# ============================================

def init_tushare():
    """初始化 Tushare SDK"""
    try:
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        # 测试连接
        test_df = pro.query('trade_cal', start_date='20260101', end_date='20260107')
        if test_df is not None and not test_df.empty:
            print("✅ Tushare 连接成功")
            return pro
        else:
            print("❌ Tushare 连接失败，请检查 Token")
            return None
    except Exception as e:
        print(f"❌ Tushare 初始化失败：{e}")
        return None


# ============================================
# 核心：关键词搜索新闻
# ============================================

def search_news_by_keyword(pro, keyword, days=7, sources=None, limit=100):
    """
    通过 Tushare news 接口按关键词搜索新闻
    
    参数：
        pro: Tushare API 对象
        keyword: 搜索关键词
        days: 往前查询的天数
        sources: 新闻来源列表，如 ['sina', 'eastmoney']
        limit: 最大返回条数
    
    返回：
        新闻列表（DataFrame 格式）
    """
    # 计算时间范围
    end_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"   ⏰ 时间范围：{start_date} 至 {end_date}")
    
    all_news = []
    
    # 如果指定了来源，逐个来源查询
    if sources:
        for src in sources:
            try:
                df = pro.news(
                    src=src,
                    start_date=start_date,
                    end_date=end_date
                )
                if df is not None and not df.empty:
                    # 本地关键词过滤
                    filtered = df[
                        df['title'].str.contains(keyword, na=False) |
                        df['content'].str.contains(keyword, na=False)
                    ]
                    if not filtered.empty:
                        filtered['source'] = src
                        all_news.append(filtered)
                        print(f"      ✅ {src}: 获取 {len(filtered)} 条")
            except Exception as e:
                print(f"      ⚠️ {src}: {e}")
            time.sleep(REQUEST_INTERVAL)
    else:
        # 不指定来源，尝试默认查询
        try:
            df = pro.news(start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                filtered = df[
                    df['title'].str.contains(keyword, na=False) |
                    df['content'].str.contains(keyword, na=False)
                ]
                if not filtered.empty:
                    all_news.append(filtered)
                    print(f"      ✅ 获取 {len(filtered)} 条")
        except Exception as e:
            print(f"      ⚠️ 查询失败：{e}")
    
    if not all_news:
        return pd.DataFrame()
    
    # 合并所有结果
    result = pd.concat(all_news, ignore_index=True)
    
    # 去重（按标题）
    result = result.drop_duplicates(subset=['title'], keep='first')
    
    # 限制数量
    if len(result) > limit:
        result = result.head(limit)
    
    return result


# ============================================
# 获取新闻正文（增强版）
# ============================================

def fetch_full_content_from_url(url):
    """
    从新闻详情页爬取完整正文（当 Tushare 返回的内容不完整时使用）
    """
    if not url:
        return ""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 移除干扰标签
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        
        # 查找正文容器
        selectors = [
            "article", ".article-content", ".content", "#content",
            ".article-body", ".main-content", ".entry-content",
            ".article", "#article", ".detail-content", ".news-content"
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
        return ""


def enhance_news_content(news_df):
    """
    增强新闻正文：如果 Tushare 返回的 content 为空或太短，尝试从 URL 爬取
    """
    print("\n正在增强新闻正文...")
    
    enhanced = []
    for idx, row in news_df.iterrows():
        title = row.get('title', '无标题')[:30]
        content = row.get('content', '')
        
        # 如果内容为空或太短，尝试爬取
        if not content or len(content) < 50:
            url = row.get('url', '')
            if url:
                print(f"  爬取：{title}...", end=" ")
                full_content = fetch_full_content_from_url(url)
                if full_content and len(full_content) > len(content):
                    row['content'] = full_content
                    print("✅")
                else:
                    print("⏭️")
            else:
                print(f"  ⏭️ {title}: 无 URL")
        else:
            print(f"  ✅ {title}: 已有正文 ({len(content)} 字符)")
        
        enhanced.append(row)
        time.sleep(0.5)
    
    return pd.DataFrame(enhanced)


# ============================================
# 保存数据
# ============================================

def save_news_data(news_df, keyword):
    """保存新闻数据到 JSON 文件"""
    if news_df.empty:
        print(f"⚠️ 关键词 '{keyword}' 无新闻数据")
        return
    
    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    os.makedirs(output_dir, exist_ok=True)
    
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"tushare_news_{keyword}_{today}.json")
    
    # 转换为 JSON 格式
    records = news_df.to_dict(orient='records')
    for rec in records:
        # 处理日期时间格式
        if 'datetime' in rec and rec['datetime']:
            rec['datetime'] = str(rec['datetime'])
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 保存到：{output_file}")
    print(f"   总条数：{len(records)}")
    
    # 统计正文覆盖情况
    with_content = sum(1 for r in records if r.get('content') and len(r.get('content', '')) > 50)
    print(f"   有正文的新闻：{with_content}")
    print(f"   正文覆盖率：{with_content/len(records)*100:.1f}%")


# ============================================
# 主函数
# ============================================

def main():
    print("=" * 60)
    print("📰 Tushare 财经新闻抓取器（环境变量版）")
    print("=" * 60)
    print(f"搜索关键词：{SEARCH_KEYWORDS}")
    print(f"新闻来源：{NEWS_SOURCES}")
    print(f"查询天数：{QUERY_DAYS} 天")
    print()

    # 初始化 Tushare
    pro = init_tushare()
    if not pro:
        print("❌ Tushare 初始化失败，请检查网络或 Token")
        sys.exit(1)

    all_results = {}

    # 逐个关键词查询
    for keyword in SEARCH_KEYWORDS:
        print(f"\n🔍 搜索关键词：{keyword}")
        df = search_news_by_keyword(
            pro=pro,
            keyword=keyword,
            days=QUERY_DAYS,
            sources=NEWS_SOURCES,
            limit=100
        )
        
        if df.empty:
            print(f"   ⚠️ 未找到与 '{keyword}' 相关的新闻")
            continue
        
        print(f"   ✅ 共获取 {len(df)} 条新闻")
        
        # 增强正文
        df = enhance_news_content(df)
        
        # 保存
        save_news_data(df, keyword)
        all_results[keyword] = df

    # 汇总统计
    print("\n" + "=" * 60)
    print("📊 汇总统计")
    print("=" * 60)
    for keyword, df in all_results.items():
        print(f"  {keyword}: {len(df)} 条")

    print("\n✅ 全部完成！")


if __name__ == "__main__":
    main()