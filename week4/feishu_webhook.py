# ============================================
# 飞书机器人 Webhook 服务
# 功能：接收飞书推送的消息事件，调用智能体处理，回复消息
# 使用 Flask 框架，通过 ngrok 暴露到公网
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
# 加载 .env 中的环境变量
load_dotenv()

import json
import hashlib
import requests
from flask import Flask, request, jsonify

# 导入我们的智能体处理函数
from feishu_agent import process_message

# 导入飞书认证函数
from feishu_auth import get_tenant_access_token

# ============================================
# 第 1 步：创建 Flask 应用
# ============================================

# Flask 应用实例
app = Flask(__name__)

# 飞书应用凭证（从环境变量读取，安全）
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")

# 飞书事件订阅的验证 Token（稍后在飞书开放平台设置）
# 这里先设置一个临时值，后面会改成你实际填写的值
VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "my_verification_token_2024")

print("=" * 50)
print("🚀 飞书机器人 Webhook 服务启动")
print("=" * 50)
print(f"App ID：{APP_ID[:15]}...")
print(f"监听地址：http://0.0.0.0:5188")
print(f"Webhook 路径：/feishu/webhook")
print()

# ============================================
# 第 2 步：飞书消息签名验证函数
# ============================================

def verify_signature(timestamp: str, nonce: str, body: str, signature: str) -> bool:
    """
    验证飞书推送消息的签名，防止伪造请求
    
    飞书会对每个推送的消息生成签名，我们需要用同样的算法验证。
    
    参数：
        timestamp: 飞书推送的时间戳
        nonce: 飞书推送的随机数
        body: 推送的原始 JSON 字符串
        signature: 飞书生成的签名
    
    返回：
        True 表示验证通过，False 表示签名不匹配
    """
    # 飞书的签名算法：sha256(timestamp + nonce + verification_token + body)
    # 把所有元素拼接成字符串
    raw_str = f"{timestamp}{nonce}{VERIFICATION_TOKEN}{body}"
    
    # 计算 SHA256 哈希
    computed_signature = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    
    # 与飞书发来的签名比较
    return computed_signature == signature


# ============================================
# 第 3 步：事件处理函数
# ============================================

def handle_message_event(event: dict) -> None:
    """
    处理飞书推送的消息事件
    
    当用户在群里 @机器人 或给机器人发私聊消息时，飞书会推送这个事件
    
    参数：
        event: 事件数据，包含消息内容、发送者、群 ID 等
    """
    # 提取消息内容
    message_id = event.get("message", {}).get("message_id", "")
    
    # 消息内容在 content 字段里，是 JSON 字符串
    content_str = event.get("message", {}).get("content", "{}")
    
    try:
        # 解析消息内容
        content = json.loads(content_str)
        # 文本消息的文本在 text 字段里
        user_text = content.get("text", "")
    except json.JSONDecodeError:
        print("⚠️ 消息内容解析失败")
        return
    
    # 去掉 @机器人 的部分（如果有的话）
    # 飞书在群聊中 @机器人 时，消息文本会包含 @机器人名称
    user_text = user_text.strip()
    
    if not user_text:
        return
    
    print(f"\n📨 收到消息：{user_text[:80]}...")
    print(f"   消息 ID：{message_id}")
    
    # 调用智能体处理消息
    reply_text = process_message(user_text)
    
    print(f"📤 回复消息：{reply_text[:80]}...")
    
    # 获取回复目标（发给哪个群或哪个用户）
    chat_id = event.get("message", {}).get("chat_id", "")
    open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
    
    # 获取访问令牌
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        print("❌ 无法获取飞书访问令牌")
        return
    
    # 发送回复
    if chat_id:
        # 群聊消息，回复到群里
        send_message_to_chat(token, chat_id, reply_text, "chat_id")
    elif open_id:
        # 私聊消息，回复给用户
        send_message_to_chat(token, open_id, reply_text, "open_id")


def send_message_to_chat(token: str, receive_id: str, content: str, receive_type: str) -> None:
    """
    通过飞书 API 发送消息
    
    参数：
        token: 飞书访问令牌
        receive_id: 接收者 ID（群 ID 或用户 Open ID）
        content: 消息文本内容
        receive_type: 接收者类型（"chat_id" 或 "open_id"）
    """
    # 飞书发送消息的 API 地址
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=" + receive_type
    
    # 消息体
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    
    # 请求头
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if data.get("code") == 0:
            print(f"✅ 回复发送成功")
        else:
            print(f"❌ 回复发送失败：{data.get('msg', '')}")
    
    except requests.exceptions.RequestException as e:
        print(f"❌ 发送回复时网络异常：{e}")


# ============================================
# 第 4 步：定义 Webhook 路由
# ============================================
@app.route("/feishu/webhook", methods=["POST"])
def feishu_webhook():
    body = request.get_data(as_text=True)
    
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return jsonify({"code": 1, "msg": "Invalid JSON"}), 400
    
    # 新版飞书事件订阅（schema 2.0）使用 header.event_type
    header = data.get("header", {})
    event_type = header.get("event_type", "")
    
    print(f"\n📬 收到事件：{event_type}")
    
    # URL 验证（首次配置时）
    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        return jsonify({"challenge": challenge})
    
    # 处理消息事件
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        handle_message_event(event)
    
    return jsonify({"code": 0, "msg": "ok"})
''''
@app.route("/feishu/webhook", methods=["POST"])
def feishu_webhook():
    """
    飞书事件订阅的 Webhook 端点
    
    飞书会把以下事件推送到这个地址：
    - 机器人收到消息
    - 机器人被拉入群
    - 等等
    """
    # 获取请求头和请求体
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    
    # 获取原始请求体（字符串形式）
    body = request.get_data(as_text=True)
    
    # 解析 JSON 请求体
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return jsonify({"code": 1, "msg": "Invalid JSON"}), 400
    
    # 飞书有两种请求类型：
    # 1. URL 验证请求（type = "url_verification"）
    # 2. 事件推送请求（type = "event_callback"）
    
    request_type = data.get("type", "")
    
    if request_type == "url_verification":
        # 这是飞书在验证 Webhook 地址是否有效
        # 需要把 challenge 字段原样返回
        challenge = data.get("challenge", "")
        print(f"✅ URL 验证请求，返回 challenge：{challenge[:20]}...")
        return jsonify({"challenge": challenge})
    
    elif request_type == "event_callback":
        # 这是真正的事件推送
        event = data.get("event", {})
        event_type = event.get("type", "")
        
        print(f"\n📬 收到事件：{event_type}")
        
        if event_type == "im.message.receive_v1":
            # 收到消息事件
            handle_message_event(event)
        
        # 返回 200 表示接收成功
        return jsonify({"code": 0, "msg": "ok"})
    
    else:
        return jsonify({"code": 0, "msg": "ignored"})

'''
# ============================================
# 第 5 步：健康检查路由
# ============================================

@app.route("/ping", methods=["GET"])
def ping():
    """健康检查端点"""
    return jsonify({"status": "ok", "service": "飞书机器人 Webhook"})


# ============================================
# 第 6 步：启动服务
# ============================================

if __name__ == "__main__":
    print()
    print("📋 下一步操作：")
    print("1. 在另一个终端窗口运行 ngrok：")
    print("   ngrok http 5000")
    print()
    print("2. 复制 ngrok 生成的 https 地址")
    print("   例如：https://abc123.ngrok-free.app")
    print()
    print("3. 在飞书开放平台配置事件订阅：")
    print("   请求地址：https://你的ngrok地址/feishu/webhook")
    print(f"   验证 Token：{VERIFICATION_TOKEN}")
    print()
    
    # 启动 Flask 服务
    # host="0.0.0.0" 允许外部访问（ngrok 需要）
    # port=5000 使用 5000 端口
    # debug=False 生产模式
    app.run(host="0.0.0.0", port=5188, debug=False)