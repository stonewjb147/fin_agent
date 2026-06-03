# ============================================
# 飞书发送消息脚本
# 功能：通过飞书机器人向指定用户或群发送消息
# 这是后续所有推送功能的基础
# ============================================

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

import requests
import json
from feishu_auth import get_tenant_access_token

# ============================================
# 获取访问令牌
# ============================================

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")

if not APP_ID or not APP_SECRET:
    print("❌ 请在 .env 文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    exit(1)

# 获取 token
print("正在获取访问令牌...")
token = get_tenant_access_token(APP_ID, APP_SECRET)

if not token:
    print("❌ 无法获取访问令牌，请检查飞书应用配置")
    exit(1)

# ============================================
# 发送文本消息的函数
# ============================================

def send_text_message(token: str, receive_id: str, content: str, receive_type: str = "open_id") -> bool:
    """
    向飞书用户或群发送文本消息
    
    参数：
        token: tenant_access_token
        receive_id: 接收者的 open_id 或 chat_id
        content: 要发送的文本内容
        receive_type: 接收者类型，"open_id" 表示发给用户，"chat_id" 表示发给群
    
    返回：
        True 表示发送成功，False 表示发送失败
    
    飞书 API 文档：
        https://open.feishu.cn/document/server-docs/im-v1/message/create
    """
    # 飞书发送消息的 API 地址
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=" + receive_type
    
    # 消息体
    # msg_type: text 表示文本消息
    # content: JSON 字符串，包含文本内容
    payload = {
        "receive_id": receive_id,           # 接收者 ID
        "msg_type": "text",                 # 消息类型：文本
        "content": json.dumps({             # 消息内容（必须是 JSON 字符串）
            "text": content                 # 文本内容
        })
    }
    
    # 请求头：Bearer Token 认证
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # 发送 POST 请求
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        # 飞书返回格式：
        # {
        #   "code": 0,
        #   "msg": "ok",
        #   "data": { "message_id": "om_xxx" }
        # }
        
        if data.get("code") == 0:
            msg_id = data.get("data", {}).get("message_id", "")
            print(f"✅ 消息发送成功")
            print(f"   消息 ID：{msg_id}")
            return True
        else:
            print(f"❌ 消息发送失败：{data.get('msg', '未知错误')}")
            print(f"   错误码：{data.get('code', '')}")
            print(f"完整相应：{data}")
            return False
    
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败：{e}")
        return False


# ============================================
# 获取用户 Open ID 的函数
# ============================================

def get_user_open_id(token: str, email: str) -> str:
    """
    通过邮箱获取用户的 Open ID
    
    参数：
        token: tenant_access_token
        email: 用户的飞书邮箱
    
    返回：
        用户的 open_id，失败返回空字符串
    """
    url = "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id"
    
    payload = {
        "emails": [email]
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if data.get("code") == 0:
            user_list = data.get("data", {}).get("user_list", [])
            if user_list:
                open_id = user_list[0].get("user_id", "")
                print(f"✅ 获取用户 Open ID 成功：{open_id[:10]}...")
                return open_id
        
        print(f"❌ 获取用户 Open ID 失败")
        return ""
    
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败：{e}")
        return ""


# ============================================
# 测试：给自己发送一条测试消息
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("飞书消息发送测试")
    print("=" * 50)
    
    # 方法一：先获取自己的 Open ID，再发送消息
    # 请把你的飞书邮箱填在这里
   # YOUR_EMAIL = "544596792@qq.com"
    
    #print(f"\n正在查找用户：{YOUR_EMAIL}")
    #open_id = get_user_open_id(token, YOUR_EMAIL)
    # 直接使用你的 Open ID（从飞书管理后台获取）
    
    # 从环境变量读取 Open ID（安全方式）
    YOUR_OPEN_ID = os.getenv("FEISHU_MY_OPEN_ID")
    
    if not YOUR_OPEN_ID:
        print("❌ 请在 .env 文件中设置 FEISHU_MY_OPEN_ID=ou_你的OpenID")
        exit(1)
    
    print(f"\n使用 Open ID：{YOUR_OPEN_ID[:15]}...")
    open_id = YOUR_OPEN_ID
    print(f"\n使用 Open ID：{YOUR_OPEN_ID[:10]}...")
    open_id = YOUR_OPEN_ID
    
    if open_id:
        # 发送测试消息
        test_content = "🤖 你好！我是金融智能助手，已成功连接到飞书。\n\n这是一条测试消息，表明基础通信功能正常。"
        print(f"\n正在发送测试消息...")
        success = send_text_message(token, open_id, test_content, receive_type="open_id")
        
        if success:
            print(f"\n🎉 请打开飞书，查看是否收到机器人发来的测试消息")
        else:
            print(f"\n⚠️ 消息发送失败，请检查飞书应用权限配置")
    else:
        print(f"\n⚠️ 请先在代码中填写你的飞书邮箱（YOUR_EMAIL 变量）")
        print(f"   如果已填写，请检查：")
        print(f"   1. 邮箱是否和飞书账号绑定")
        print(f"   2. 应用是否有'读取通讯录'权限")