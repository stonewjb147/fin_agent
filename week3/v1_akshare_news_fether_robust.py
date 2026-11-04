#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AKShare 财经新闻抓取器（健壮版 v3）
================================================================================
功能说明：
1. 多数据源智能适配（声明式配置，新增数据源只需在 DATA_SOURCE_CONFIG 中添加）1,匹配取数函数2.增加数据源；
“”“
def fetch_我的新数据源(limit=100):
    # 1. 读取环境变量
    api_key = os.getenv("MY_NEW_API_KEY")
    if not api_key:
        logger.warning("我的新数据源 API Key 未配置，请在 .env 中设置 MY_NEW_API_KEY")
        return pd.DataFrame()

    # 2. 调用 API（示例）
    try:
        # response = requests.get(...)
        # data = response.json()
        
        # 3. 关键：必须转换为 DataFrame
        # 假设 data['list'] 是新闻列表
        df = pd.DataFrame(data['list'])
        
        logger.info(f"✅ 我的新数据源：{len(df)} 条")
        return df.head(limit)
    except Exception as e:
        logger.error(f"我的新数据源请求失败: {e}")
        return pd.DataFrame()
        
    2数据源映射


    DATA_SOURCE_CONFIG = {
    # ... 已有数据源 ...
    
    '我的新数据源': {  # 1. 数据源名称
        # 2. 绑定刚才写的函数
        'fetch_func': lambda: fetch_我的新数据源(MAX_PER_SOURCE), 
        
        # 3. 核心映射（按优先级填写候选列名）
        'field_mapping': {
            'title': ['标题列名', 'title', 'name'],       # 脚本最终要 'title'
            'content': ['正文列名', 'content', 'text'],   # 脚本最终要 'description'
            'time': ['时间列名', 'date', 'pub_time']     # 脚本最终要 'pub_time'
        },
        'description': '这里填写数据源的说明文字'
    }
}
”“”
2. 支持 AKShare、聚合数据（Juhe）、Tushare 三大数据源
3. 所有 API Key / Token 均从 .env 文件读取，不硬编码
4. 智能摘要提取 + 数据质量验证 + 软件工程健壮性（重试、超时、日志）
5. 完整的逐行注释，便于维护和扩展
================================================================================
"""

import os
import sys
import json
import re
import time
import logging
from datetime import datetime
from typing import Dict, List, Callable, Optional, Tuple
import pandas as pd
import requests
from dotenv import load_dotenv

# ============================================
# 第 0 部分：加载环境变量（必须在最前面）
# ============================================

# 加载项目根目录的 .env 文件
env_path = os.path.expanduser("~/fin_agent_projects/.env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # 如果根目录没有，尝试当前目录
    load_dotenv()
    # 若仍没有，给出警告，但脚本继续运行（可能某些数据源失效）
    if not os.getenv("JUHE_API_KEY") and not os.getenv("TUSHARE_TOKEN"):
        logging.warning("未找到 .env 文件或缺少密钥，聚合/Tushare 数据源可能无法使用")

# ============================================
# 第 1 部分：日志配置（确保日志目录存在）
# ============================================

log_dir = os.path.expanduser("~/fin_agent_projects/logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(log_dir, "fetcher.log"), mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# 第 2 部分：全局配置（外部化，便于修改）
# ============================================

SEARCH_KEYWORDS = [
    "航天", "AI", "人工智能", "半导体", "芯片", "光模块",
    "新能源", "光伏", "锂电池", "储能"
]

MIN_TITLE_LENGTH = 2
MIN_CONTENT_LENGTH = 10
MAX_RETRY_TIMES = 3
REQUEST_TIMEOUT = 30

PLACEHOLDERS = [
    '无内容', '周刊提前读', '周刊精选', '周刊',
    'None', 'null', '', ' ', '\t', '\n', 'NaN'
]

# ============================================
# 第 3 部分：数据源获取函数（含环境变量读取）
# ============================================

# ---- 3.1 AKShare 数据源（不变） ----
def fetch_eastmoney_news(limit=100):
    try:
        import akshare as ak
        df = ak.stock_news_em()
        if df is not None and not df.empty:
            logger.info(f"✅ 东方财富：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        logger.error(f"⚠️ 东方财富：{e}")
    return pd.DataFrame()

def fetch_sina_news(limit=100):
    try:
        import akshare as ak
        df = ak.news_cctv()
        if df is not None and not df.empty:
            logger.info(f"✅ 新浪财经：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        logger.error(f"⚠️ 新浪财经：{e}")
    return pd.DataFrame()

def fetch_main_news(limit=100):
    try:
        import akshare as ak
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            logger.info(f"✅ 财经主接口：{len(df)} 条")
            return df.head(limit)
    except Exception as e:
        logger.error(f"⚠️ 财经主接口：{e}")
    return pd.DataFrame()

def fetch_jin10_news(limit=100):
    try:
        import akshare as ak
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
                    logger.info(f"✅ 金十数据({name})：{len(df)} 条")
                    return df.head(limit)
            except:
                continue
    except Exception as e:
        logger.error(f"⚠️ 金十数据：{e}")
    return pd.DataFrame()

# ---- 3.2 聚合数据（Juhe） ----
def fetch_juhe_news(limit=100):
    """从聚合数据获取财经新闻（API Key 从 .env 读取）"""
    api_key = os.getenv("JUHE_NEWS_API")
    if not api_key:
        logger.warning("聚合数据 API Key 未配置，请在 .env 中设置 JUHE_API_KEY")
        return pd.DataFrame()

    url = "http://v.juhe.cn/toutiao/index"
    params = {
        "type": "caijing",
        "key": api_key,
        "page": 1,
        "page_size": min(limit, 50)  # 聚合数据每页最大50
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("error_code") == 0:
            articles = data.get("result", {}).get("data", [])
            if articles:
                df = pd.DataFrame(articles)
                logger.info(f"✅ 聚合数据：{len(df)} 条")
                return df.head(limit)
            else:
                logger.warning("聚合数据返回空列表")
                return pd.DataFrame()
        else:
            logger.warning(f"聚合数据API错误: {data.get('reason')}")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"聚合数据请求失败: {e}")
        return pd.DataFrame()

# ---- 3.3 Tushare 数据源 ----
def fetch_tushare_news(limit=100):
    """从 Tushare 获取新闻（Token 从 .env 读取）"""
    token = os.getenv("token")
    if not token:
        logger.warning("Tushare Token 未配置，请在 .env 中设置 TUSHARE_TOKEN")
        return pd.DataFrame()

    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()

        # 计算日期范围（近7天）
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - pd.Timedelta(days=7)).strftime("%Y%m%d")

        df = pro.news(
            src='sina',           # 可指定数据源，也可不指定
            start_date=start_date,
            end_date=end_date
        )
        if df is not None and not df.empty:
            logger.info(f"✅ Tushare：{len(df)} 条")
            return df.head(limit)
        else:
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Tushare 新闻获取失败: {e}")
        return pd.DataFrame()

# ============================================
# 第 4 部分：数据源配置（声明式，包含新增数据源）
# ============================================

DATA_SOURCE_CONFIG = {
    '财经主接口': {
        'fetch_func': lambda: fetch_main_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['tag', 'title', 'name'],
            'content': ['summary', 'content', 'description'],
            'time': ['pub_time', 'datetime', 'date']
        },
        'description': '财新/财经主接口，标题在 tag，内容在 summary'
    },
    '东方财富': {
        'fetch_func': lambda: fetch_eastmoney_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['新闻标题', 'title', 'tag'],
            'content': ['新闻内容', 'content', 'summary', 'description'],
            'time': ['发布时间', 'datetime', 'date']
        },
        'description': '东方财富快讯，标题在 新闻标题，内容在 新闻内容'
    },
    '新浪财经': {
        'fetch_func': lambda: fetch_sina_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['title', 'tag', 'name'],
            'content': ['content', 'summary', 'description'],
            'time': ['datetime', 'date', 'pub_time']
        },
        'description': '新浪财经/央视新闻，标题在 title，内容在 content'
    },
    '金十数据': {
        'fetch_func': lambda: fetch_jin10_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['title', 'tag', 'name'],
            'content': ['content', 'summary', 'description'],
            'time': ['datetime', 'date', 'pub_time']
        },
        'description': '金十数据（自适应多接口），可能不稳定'
    },
    # ========== 新增数据源 ==========
    '聚合数据': {
        'fetch_func': lambda: fetch_juhe_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['title', 'tag'],
            'content': ['content', 'summary'],
            'time': ['date', 'pub_time']
        },
        'description': '聚合数据财经新闻，通过 HTTP API 获取，需配置 JUHE_API_KEY'
    },
    'Tushare': {
        'fetch_func': lambda: fetch_tushare_news(MAX_PER_SOURCE),
        'field_mapping': {
            'title': ['title', 'tag'],
            'content': ['content', 'summary'],
            'time': ['datetime', 'date']
        },
        'description': 'Tushare 新闻数据，需配置 TUSHARE_TOKEN'
    },
}

# 为了方便，添加一个每源最大条数常量
MAX_PER_SOURCE = 100

# ============================================
# 第 5 部分：工具函数（保持不变）
# ============================================

def safe_fetch(func: Callable, max_retries: int = MAX_RETRY_TIMES, timeout: int = REQUEST_TIMEOUT):
    """安全执行数据获取函数，带重试机制和超时控制"""
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            result = func()
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"请求超时 ({elapsed:.2f}s > {timeout}s)，重试 {attempt+1}/{max_retries}")
                continue
            if result is not None and not result.empty:
                return result
            else:
                logger.warning(f"返回空数据，重试 {attempt+1}/{max_retries}")
                time.sleep(1)
        except Exception as e:
            logger.error(f"请求失败 (尝试 {attempt+1}/{max_retries}): {e}")
            time.sleep(2 ** attempt)
            continue
    logger.error(f"数据源 {func.__name__} 所有重试均失败")
    return pd.DataFrame()

def is_placeholder(text: str) -> bool:
    if text is None or pd.isna(text):
        return True
    if not isinstance(text, str):
        return True
    text = text.strip()
    if text in PLACEHOLDERS:
        return True
    if re.match(r'^[\s\-_—\.,;:!?()\[\]{}""\'\n\r\t]*$', text):
        return True
    return False

def clean_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return ''
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^[\s\-_\.,;:!?]+', '', text)
    text = re.sub(r'[\s\-_\.,;:!?]+$', '', text)
    return text

def get_field_value(row: pd.Series, field_candidates: List[str]) -> str:
    for field in field_candidates:
        if field in row and not pd.isna(row[field]) and not is_placeholder(row[field]):
            value = str(row[field])
            if value.strip():
                return clean_text(value)
    return ''

# ============================================
# 第 6 部分：智能标准化函数
# ============================================

def normalize(df: pd.DataFrame, source_name: str, field_mapping: Dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    logger.info(f"处理数据源: {source_name}")

    title_candidates = field_mapping.get('title', ['title', 'tag'])
    content_candidates = field_mapping.get('content', ['content', 'summary', 'description'])
    time_candidates = field_mapping.get('time', ['pub_time', 'datetime', 'date'])

    titles = df.apply(lambda row: get_field_value(row, title_candidates), axis=1)
    contents = df.apply(lambda row: get_field_value(row, content_candidates), axis=1)
    times = df.apply(lambda row: get_field_value(row, time_candidates), axis=1)
    times = times.apply(lambda x: x if x else datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # 补全
    for i in range(len(titles)):
        if not titles[i] and contents[i]:
            titles[i] = contents[i][:30] + ('...' if len(contents[i]) > 30 else '')
    for i in range(len(contents)):
        if not contents[i] and titles[i]:
            contents[i] = titles[i]

    result_df = pd.DataFrame({
        'title': titles,
        'description': contents,
        'pub_time': times,
        'source': source_name
    })

    # 保留原始列（调试用）
    for col in df.columns:
        if col not in ['title', 'description', 'pub_time', 'source']:
            result_df[f'_raw_{col}'] = df[col]

    valid_titles = (result_df['title'] != '').sum()
    valid_contents = (result_df['description'] != '').sum()
    total = len(result_df)
    logger.info(f"  ✅ 有效标题: {valid_titles}/{total} ({valid_titles/total*100:.1f}%)")
    logger.info(f"  ✅ 有效内容: {valid_contents}/{total} ({valid_contents/total*100:.1f}%)")

    return result_df

# ============================================
# 第 7 部分：数据清洗与过滤
# ============================================

def filter_valid_articles(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    mask = (df['title'] != '') | (df['description'] != '')
    mask &= (df['description'].str.len() >= MIN_CONTENT_LENGTH) | (df['title'].str.len() >= MIN_TITLE_LENGTH)
    df = df[mask].copy()
    after = len(df)
    if before - after > 0:
        logger.info(f"  🧹 过滤掉 {before - after} 条无效新闻")
    return df

def deduplicate_articles(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset=['title'], keep='first')
    after = len(df)
    if before - after > 0:
        logger.info(f"  🔄 去重移除 {before - after} 条重复新闻")
    return df

def filter_by_keywords(df: pd.DataFrame, keywords: List[str]) -> pd.DataFrame:
    if df.empty or not keywords:
        return df

    def contains_keyword(text: str) -> bool:
        if not text or not isinstance(text, str):
            return False
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    mask = df['title'].apply(contains_keyword) | df['description'].apply(contains_keyword)
    filtered = df[mask].copy()
    logger.info(f"  🔍 关键词过滤后: {len(filtered)} 条 (剩余 {len(filtered)/len(df)*100:.1f}%)")
    return filtered

# ============================================
# 第 8 部分：数据保存与质量报告
# ============================================

def save_news_data(df: pd.DataFrame, output_dir: str) -> Tuple[str, Dict]:
    os.makedirs(output_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"news_akshare_{today}.json")

    records = df.to_dict(orient='records')
    for rec in records:
        if 'pub_time' in rec and hasattr(rec['pub_time'], 'strftime'):
            rec['pub_time'] = rec['pub_time'].strftime('%Y-%m-%d %H:%M:%S')

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    total = len(records)
    empty_title = sum(1 for r in records if not r.get('title'))
    empty_desc = sum(1 for r in records if not r.get('description'))
    short_desc = sum(1 for r in records if r.get('description') and len(r.get('description', '')) < 20)

    quality_report = {
        'total': total,
        'empty_title': empty_title,
        'empty_description': empty_desc,
        'short_description': short_desc,
        'valid_rate': (total - empty_desc) / total * 100 if total > 0 else 0,
        'file_path': output_file,
        'file_size_kb': os.path.getsize(output_file) / 1024
    }

    logger.info("=" * 60)
    logger.info("📊 数据质量报告")
    logger.info("=" * 60)
    logger.info(f"  总条数: {total}")
    logger.info(f"  空标题: {empty_title} 条 ({empty_title/total*100:.1f}%)")
    logger.info(f"  空内容: {empty_desc} 条 ({empty_desc/total*100:.1f}%)")
    logger.info(f"  短内容 (<20字): {short_desc} 条")
    logger.info(f"  有效内容率: {quality_report['valid_rate']:.1f}%")
    logger.info(f"  文件路径: {output_file}")
    logger.info(f"  文件大小: {quality_report['file_size_kb']:.1f} KB")
    logger.info("=" * 60)

    return output_file, quality_report

# ============================================
# 第 9 部分：主函数
# ============================================

def main():
    logger.info("=" * 60)
    logger.info("📰 AKShare 财经新闻抓取器（健壮版 v3）")
    logger.info("=" * 60)
    logger.info(f"关键词: {SEARCH_KEYWORDS}")
    logger.info(f"数据源: {list(DATA_SOURCE_CONFIG.keys())}")
    logger.info("")

    all_dfs = []
    failed_sources = []

    for source_name, config in DATA_SOURCE_CONFIG.items():
        logger.info(f"🔄 正在获取数据源: {source_name}")
        logger.info(f"   {config['description']}")

        try:
            raw_df = safe_fetch(config['fetch_func'], max_retries=MAX_RETRY_TIMES)
            if raw_df is None or raw_df.empty:
                logger.warning(f"   ⚠️ {source_name} 返回空数据，跳过")
                failed_sources.append(source_name)
                continue

            normalized_df = normalize(raw_df, source_name, config['field_mapping'])
            normalized_df = filter_valid_articles(normalized_df)

            if normalized_df.empty:
                logger.warning(f"   ⚠️ {source_name} 标准化后无有效数据")
                failed_sources.append(source_name)
                continue

            all_dfs.append(normalized_df)
            logger.info(f"   ✅ {source_name} 成功获取 {len(normalized_df)} 条有效数据")

        except Exception as e:
            logger.error(f"   ❌ {source_name} 处理异常: {e}")
            failed_sources.append(source_name)
            continue

    if not all_dfs:
        logger.error("❌ 所有数据源均失败")
        logger.error(f"   失败的数据源: {failed_sources}")
        sys.exit(1)

    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(f"\n📊 合并后: {len(combined)} 条")

    combined = deduplicate_articles(combined)

    if SEARCH_KEYWORDS:
        combined = filter_by_keywords(combined, SEARCH_KEYWORDS)

    if combined.empty:
        logger.warning("⚠️ 无相关新闻，退出")
        sys.exit(0)

    output_dir = os.path.expanduser("~/fin_agent_projects/data")
    output_file, quality_report = save_news_data(combined, output_dir)

    logger.info("\n📄 数据预览（前5条）：")
    for i, row in combined.head(5).iterrows():
        title = row.get('title', '无标题')[:50]
        desc = row.get('description', '')[:50]
        src = row.get('source', '')
        logger.info(f"  {i+1}. {title}... ({src})")
        logger.info(f"     内容: {desc}...")

    if failed_sources:
        logger.warning(f"\n⚠️ 以下数据源获取失败: {failed_sources}")
    else:
        logger.info("\n✅ 所有数据源均成功")

    logger.info("\n✅ 抓取完成！")

if __name__ == "__main__":
    main()