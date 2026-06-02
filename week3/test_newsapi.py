#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NewsAPI.org 连接测试脚本
用于诊断 API Key 有效性和网络连接问题
"""

import requests
import json
import sys
from datetime import datetime, timedelta

# ============================================
# 配置区域（请替换为你的实际 Key）
# ============================================
app_key = "83687c7236471bf4cda9e33c6d6c0e24"  # 替换为你的 NewsAPI Key
BASE_URL = "https://newsapi.org/v2"

# ============================================
# 测试函数
# ============================================

def test_connection():
    """测试网络连接"""
    print("\n" + "="*60)
    print("1. 测试网络连接")
    print("="*60)
    
    try:
        response = requests.get("https://newsapi.org", timeout=10)
        print(f"✅ 网络连接正常 (状态码: {response.status_code})")
        return True
    except requests.exceptions.Timeout:
        print("❌ 连接超时：无法访问 newsapi.org")
        print("   → 可能原因：网络代理问题、防火墙限制")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接失败: {e}")
        print("   → 可能原因：需要配置代理、DNS解析失败")
        return False

def test_api_key_format():
    """测试 API Key 格式"""
    print("\n" + "="*60)
    print("2. 测试 API Key 格式")
    print("="*60)
    
    if not API_KEY:
        print("❌ API Key 为空")
        return False
    
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"长度: {len(API_KEY)} 字符")
    
    # NewsAPI Key 通常是32-64位的十六进制字符串
    if len(API_KEY) >= 32:
        print("✅ API Key 格式正常")
        return True
    else:
        print("⚠️ API Key 长度较短，可能格式不正确")
        return False

def test_simple_top_headlines():
    """测试最简单的 /v2/top-headlines 接口"""
    print("\n" + "="*60)
    print("3. 测试 /v2/top-headlines 接口")
    print("="*60)
    
    url = f"{BASE_URL}/top-headlines"
    params = {
        "country": "us",
        "pageSize": 5,
        "apiKey": API_KEY
    }
    
    print(f"请求 URL: {url}")
    print(f"参数: country=us, pageSize=5")
    
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get("articles", [])
            print(f"✅ 成功！获取到 {len(articles)} 条新闻")
            if articles:
                print(f"\n第一条新闻标题: {articles[0].get('title', 'N/A')}")
            return True
        else:
            print(f"❌ 失败")
            print(f"错误信息: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

def test_search_endpoint():
    """测试 /v2/everything 搜索接口"""
    print("\n" + "="*60)
    print("4. 测试 /v2/everything 搜索接口")
    print("="*60)
    
    # 使用一个简单的查询
    one_week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"{BASE_URL}/everything"
    params = {
        "q": "finance",
        "from": one_week_ago,
        "language": "en",
        "pageSize": 5,
        "apiKey": API_KEY
    }
    
    print(f"请求 URL: {url}")
    print(f"查询: q=finance, from={one_week_ago}")
    
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get("articles", [])
            total = data.get("totalResults", 0)
            print(f"✅ 成功！总共 {total} 条结果，本次获取 {len(articles)} 条")
            return True
        else:
            print(f"❌ 失败")
            error_data = response.json() if response.text else {}
            print(f"错误码: {error_data.get('code', 'N/A')}")
            print(f"错误信息: {error_data.get('message', response.text)}")
            
            # 常见错误解释
            if response.status_code == 401:
                print("\n🔍 错误解释: API Key 无效或已过期")
                print("   → 解决方案: 去 https://newsapi.org/account 检查你的 Key")
            elif response.status_code == 426:
                print("\n🔍 错误解释: 需要升级账户（免费版不支持某些参数）")
                print("   → 解决方案: 检查是否使用了需要付费版的参数")
            elif response.status_code == 429:
                print("\n🔍 错误解释: 请求次数超限")
                print("   → 解决方案: 等待一段时间再试，或升级账户")
            
            return False
            
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

def test_chinese_search():
    """测试中文搜索"""
    print("\n" + "="*60)
    print("5. 测试中文搜索（如果前两项都失败可跳过）")
    print("="*60)
    
    url = f"{BASE_URL}/everything"
    params = {
        "q": "A股 OR 股市",
        "language": "zh",
        "pageSize": 3,
        "apiKey": API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get("articles", [])
            print(f"✅ 成功！获取到 {len(articles)} 条中文新闻")
            return True
        else:
            print(f"⚠️ 中文搜索失败（可能免费版不支持）")
            return False
            
    except Exception as e:
        print(f"⚠️ 异常: {e}")
        return False

# ============================================
# 主函数
# ============================================

def main():
    print("\n" + "="*60)
    print("NewsAPI.org 环境诊断工具")
    print("="*60)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # 执行测试
    results.append(("网络连接", test_connection()))
    results.append(("API Key 格式", test_api_key_format()))
    results.append(("头条新闻接口", test_simple_top_headlines()))
    results.append(("搜索接口", test_search_endpoint()))
    
    # 只有前几个成功才测试中文
    if results[2][1] or results[3][1]:
        results.append(("中文搜索", test_chinese_search()))
    
    # 汇总结果
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 恭喜！所有测试通过，你的 NewsAPI 环境配置正确！")
        print("可以开始使用 NewsAPI 抓取新闻了。")
    else:
        print("⚠️ 部分测试失败，请根据上面的提示进行排查：")
        print("\n常见解决方案：")
        print("1. 确认 API Key 正确：访问 https://newsapi.org/account 检查")
        print("2. 检查网络：是否需要配置代理？")
        print("3. 免费版限制：某些参数或地区可能不支持")
        print("\n如果问题持续，建议切换到 GNews API：")
        print("   https://gnews.io 免费注册，每日100次请求")
    print("="*60)

if __name__ == "__main__":
    main()