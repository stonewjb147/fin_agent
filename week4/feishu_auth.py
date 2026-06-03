# ============================================
# 飞书访问令牌获取脚本
# 功能：调用飞书 API 获取 tenant_access_token
# 所有飞书 API 调用都需要这个令牌
# 令牌有效期 2 小时，需定期刷新
# ============================================

import os
from dotenv import load_dotenv

# 加载 .env 中的环境变量
load_dotenv()

import requests
import json

# ============================================
# 获取 tenant_access_token 的函数
# ============================================

def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """
    调用飞书 API 获取 tenant_access_token
    
    参数：
        app_id: 应用的 App ID（从飞书开放平台获取）
        app_secret: 应用的 App Secret（从飞书开放平台获取）
    
    返回：
        token 字符串，如果失败则返回空字符串
    
    飞书 API 文档：
        https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token
    """
    # 飞书获取 token 的 API 地址
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    
    # 请求体：包含 app_id 和 app_secret
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    # 请求头：指定 JSON 格式
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        # 发送 POST 请求
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()  # 检查 HTTP 错误
        
        # 解析返回的 JSON
        data = response.json()
        
        # 飞书返回格式：
        # {
        #   "code": 0,
        #   "msg": "ok",
        #   "tenant_access_token": "t-g1044..."
        # }
        
        if data.get("code") == 0:
            token = data.get("tenant_access_token", "")
            print(f"✅ 获取 token 成功")
            print(f"   Token 前缀：{token[:20]}...")
            print(f"   有效期：约 2 小时")
            return token
        else:
            print(f"❌ 获取 token 失败：{data.get('msg', '未知错误')}")
            print(f"   错误码：{data.get('code', '')}")
            return ""
    
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败：{e}")
        return ""


# ============================================
# 测试：获取并验证 token
# ============================================

if __name__ == "__main__":
    # 从环境变量读取凭据
    APP_ID = os.getenv("FEISHU_APP_ID")
    APP_SECRET = os.getenv("FEISHU_APP_SECRET")
    
    # 检查凭据是否存在
    if not APP_ID or not APP_SECRET:
        print("❌ 请在 .env 文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        print("   获取方式：飞书开放平台 -> 应用详情 -> 凭证与基础信息")
        exit(1)
    
    print("=" * 50)
    print("飞书 Tenant Access Token 获取测试")
    print("=" * 50)
    print(f"App ID：{APP_ID[:10]}...")
    print()
    
    # 调用获取 token
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    
    if token:
        print(f"\n✅ 飞书 API 连接验证通过")
        print(f"   可以开始调用其他 API 了")
    else:
        print(f"\n❌ 飞书 API 连接验证失败")
        print(f"   请检查：")
        print(f"   1. App ID 和 App Secret 是否正确")
        print(f"   2. 应用是否已发布（飞书开放平台 -> 应用发布 -> 创建版本并发布）")