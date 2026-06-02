#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
聚合数据 - 新闻头条接口抓取脚本
接口文档：https://www.juhe.cn/docs/api/id/235
用于第四练：全球情报守望者
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# ============================================
# 配置
# ============================================

# 新闻头条接口地址（官方正确地址）
API_URL = "http://v.juhe.cn/toutiao/index"

# 从 .env 读取 AppKey
APP_KEY = os.getenv("APP_key") or os.getenv("JUHE_NEWS_API_KEY") or os.getenv("JUHE_APPKEY")

if not APP_KEY:
    raise ValueError("请在 .env 文件中设置 app_key=你的聚合数据AppKey")

# 新闻类型（用于第四练财经新闻）
# 可选值：top(推荐), guonei(国内), guoji(国际), caijing(财经), keji(科技), shishang(时尚), yule(娱乐), tiyu(体育)
NEWS_TYPE = "caijing"  # 财经新闻，最贴近股票市场

# 每页数量（最大50）
PAGE_SIZE = 50

print("=" * 60)
print("📰 聚合数据 - 新闻头条抓取器")
print(f"接口地址: {API_URL}")
print(f"新闻类型: {NEWS_TYPE}")
print("=" * 60)

# ============================================
# 抓取新闻
# ============================================

def fetch_news(page=1, page_size=PAGE_SIZE):
    """
    抓取新闻
    :param page: 页码
    :param page_size: 每页数量
    :return: 新闻列表
    """
    params = {
        "type": NEWS_TYPE,
        "key": APP_KEY,
        "page": page,
        "page_size": page_size
    }
    
    try:
        response = requests.get(API_URL, params=params, timeout=15)
        data = response.json()
        
        if data.get("error_code") == 0:
            result = data.get("result", {})
            articles = result.get("data", [])
            total = len(articles)
            print(f"✅ 成功获取 {total} 条新闻")
            return articles
        else:
            error_code = data.get("error_code")
            reason = data.get("reason", "未知错误")
            print(f"❌ 请求失败: [{error_code}] {reason}")
            
            # 错误码提示
            if error_code == 10001:
                print("   → AppKey无效，请检查 .env 中的 app_key")
            elif error_code == 10005:
                print("   → 请求过于频繁，请稍后再试")
            elif error_code == 10022:
                print("   → 接口未申请，请先在聚合数据申请「新闻头条」接口")
            return []
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时，请检查网络连接")
        return []
    except Exception as e:
        print(f"❌ 异常: {e}")
        return []

# ============================================
# 保存到JSON
# ============================================

def save_to_json(articles, filename=None):
    """保存新闻到JSON文件"""
    if not articles:
        print("没有数据可保存")
        return None
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"juhe_news_{timestamp}.json"
    
    # 创建data目录
    os.makedirs("data", exist_ok=True)
    filepath = os.path.join("data", filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已保存到: {filepath}")
    print(f"   文件大小: {os.path.getsize(filepath) / 1024:.1f} KB")
    return filepath

# ============================================
# 数据预览
# ============================================

def preview_news(articles, limit=5):
    """预览新闻"""
    if not articles:
        print("没有数据可预览")
        return
    
    print("\n" + "=" * 60)
    print(f"📄 新闻预览（前{limit}条）")
    print("=" * 60)
    
    for i, article in enumerate(articles[:limit], 1):
        title = article.get("title", "无标题")
        author = article.get("author_name", "未知来源")
        date = article.get("date", "未知时间")
        url = article.get("url", "")
        
        print(f"\n[{i}] {title}")
        print(f"    来源: {author} | 时间: {date}")
        if url:
            print(f"    链接: {url[:80]}...")

# ============================================
# 主函数
# ============================================

def main():
    print("\n[1/3] 正在抓取新闻...")
    articles = fetch_news(page=1, page_size=30)
    
    if not articles:
        print("\n❌ 抓取失败，请检查：")
        print("1. AppKey是否正确")
        print("2. 是否已申请「新闻头条」接口")
        print("3. 是否完成实名认证")
        return
    
    print(f"\n[2/3] 共抓取 {len(articles)} 条新闻")
    
    # 预览
    preview_news(articles, limit=5)
    
    print(f"\n[3/3] 保存数据...")
    save_to_json(articles)
    
    print("\n" + "=" * 60)
    print("✅ 抓取完成！")
    print("=" * 60)

# ============================================
# 供其他模块调用的函数
# ============================================

def get_finance_news(limit=50):
    """
    获取财经新闻（供第四练调用）
    :param limit: 最大数量
    :return: 新闻列表
    """
    params = {
        "type": "caijing",
        "key": APP_KEY,
        "page": 1,
        "page_size": min(limit, 50)
    }
    
    try:
        response = requests.get(API_URL, params=params, timeout=10)
        data = response.json()
        if data.get("error_code") == 0:
            return data.get("result", {}).get("data", [])
    except:
        pass
    return []

if __name__ == "__main__":
    main()