#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AKShare 财经新闻抓取器（稳定版 v2）
数据源：东方财富、新浪财经、央视新闻、金十数据（自适应）
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
import akshare as ak

# ============================================
# 配置
# ============================================

SEARCH_KEYWORDS = [
    "航天", "AI", "人工智能", "半导体", "芯片", "光模块",
    "新能源", "光伏", "锂电池", "储能"
]

ENABLE_FILTER = False
MAX_PER_SOURCE = 100


# ============================================
# 数据源函数（保持不变）
# ============================================

def fetch_eastmoney_news(limit=100):
    try:
        df = ak.stock_news_em()
        if df is not None and not df.empty:
            print(f"✅ 东方财富：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        print(f"⚠️ 东方财富：{e}")
    return pd.DataFrame()


def fetch_sina_news(limit=100):
    try:
        df = ak.news_cctv()
        if df is not None and not df.empty:
            print(f"✅ 新浪财经：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        print(f"⚠️ 新浪财经：{e}")
    return pd.DataFrame()


def fetch_main_news(limit=100):
    try:
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            print(f"✅ 财经主接口：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        print(f"⚠️ 财经主接口：{e}")
    return pd.DataFrame()


def fetch_jin10_news(limit=100):
    possible = [
        ('news_jin10', lambda: ak.news_jin10()),
        ('jin10_news', lambda: ak.jin10_news()),
        ('js_news', lambda: ak.js_news(indicator='最新资讯')),
        ('get_js_news', lambda: ak.get_js_news()),
    ]
    for name, func in possible:
        try:
            df = func()
            if df is not None and not df.empty:
                print(f"✅ 金十数据({name})：{len(df)} 条")
                return df.head(limit)
        except:
            continue
    print("⚠️ 金十数据：不可用")
    return pd.DataFrame()


def fetch_163_news(limit=100):
    try:
        df = ak.news_163()
        if df is not None and not df.empty:
            print(f"✅ 网易财经：{len(df)} 条")
            return df.head(limit)
    except:
        pass
    return pd.DataFrame()


# ============================================
# 核心修改：字段标准化（复制策略）
# ============================================

def normalize(df, source):
    """
    将不同数据源的字段统一为 title, description, pub_time
    采用“复制”而非“重命名”，确保不丢失数据
    """
    if df.empty:
        return df

    # 调试：打印原始列名
    print(f"🔍 {source} 原始列名: {df.columns.tolist()}")
    print(f"🔍 {source} 行数: {len(df)}")

    # 1. 创建 title 字段：优先从 tag、title、name、subject 取
    title_candidates = ['tag', 'title', 'name', 'subject', 'headline']
    df['title'] = ''
    for col in title_candidates:
        if col in df.columns:
            # 如果当前 title 为空，则从该列复制
            mask = df['title'].isna() | (df['title'] == '')
            df.loc[mask, 'title'] = df.loc[mask, col]
    # 如果 title 仍为空，用第一列非空字符串（兜底）
    if df['title'].isna().all() or (df['title'] == '').all():
        for col in df.columns:
            if df[col].dtype == object:  # 文本列
                df['title'] = df[col]
                break

    # 2. 创建 description 字段：优先从 content、summary、description、text 取
    content_candidates = ['content', 'summary', 'description', 'text', 'body']
    df['description'] = ''
    for col in content_candidates:
        if col in df.columns:
            mask = df['description'].isna() | (df['description'] == '')
            df.loc[mask, 'description'] = df.loc[mask, col]

    # 3. 创建 pub_time 字段：从 datetime, date, time, publish_time 取
    time_candidates = ['pub_time', 'datetime', 'date', 'time', 'publish_time', 'ctime']
    df['pub_time'] = ''
    for col in time_candidates:
        if col in df.columns:
            mask = df['pub_time'].isna() | (df['pub_time'] == '')
            df.loc[mask, 'pub_time'] = df.loc[mask, col]
    # 如果时间仍为空，用当前时间
    df['pub_time'] = df['pub_time'].fillna(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # 4. 添加来源
    df['source'] = source

    # 5. 保留原始数据（不删除列），方便调试
    return df


# ============================================
# 过滤与去重
# ============================================

def filter_by_keywords(df, keywords):
    if df.empty or not keywords:
        return df

    def contains(text):
        if not text or not isinstance(text, str):
            return False
        t = text.lower()
        return any(kw.lower() in t for kw in keywords)

    mask = df['title'].apply(contains) | df['description'].apply(contains)
    filtered = df[mask].copy()
    print(f"   🔍 过滤后：{len(filtered)} 条")
    return filtered


# ============================================
# 主函数
# ============================================

def main():
    print("=" * 60)
    print("📰 AKShare 财经新闻抓取器（稳定版 v2）")
    print("=" * 60)
    print(f"关键词：{SEARCH_KEYWORDS}")
    print(f"过滤：{'启用' if ENABLE_FILTER else '禁用'}")
    print()

    sources = [
        ('财经主接口', fetch_main_news),
        ('东方财富', fetch_eastmoney_news),
        ('新浪财经', fetch_sina_news),
        ('金十数据', fetch_jin10_news),
    ]

    all_dfs = []
    for name, func in sources:
        print(f"\n正在获取 {name}...")
        df = func(MAX_PER_SOURCE)
        if not df.empty:
            df = normalize(df, name)
            all_dfs.append(df)

    if not all_dfs:
        print("❌ 所有数据源均失败")
        sys.exit(1)

    # 合并
    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\n📊 合并后：{len(combined)} 条")

    # 去重（按 title）
    combined = combined.drop_duplicates(subset=['title'], keep='first')
    print(f"   去重后：{len(combined)} 条")

    # 过滤
    if ENABLE_FILTER:
        combined = filter_by_keywords(combined, SEARCH_KEYWORDS)

    if combined.empty:
        print("⚠️ 无相关新闻")
        sys.exit(0)

    # 保存
    out_dir = os.path.expanduser("~/fin_agent_projects/data")
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    out_file = os.path.join(out_dir, f"news_akshare_{today}.json")
    records = combined.to_dict(orient='records')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 保存到：{out_file}")
    print(f"   总条数：{len(records)}")

    # 预览
    print("\n📄 预览（前5条）：")
    for i, row in combined.head(5).iterrows():
        title = row.get('title', '')[:40]
        src = row.get('source', '')
        print(f"  {i+1}. {title}... ({src})")

    # 来源统计
    print("\n📊 来源统计：")
    cnt = combined['source'].value_counts()
    for src, c in cnt.items():
        print(f"   {src}：{c} 条")


if __name__ == "__main__":
    main()