# ============================================
# 飞书机器人完整服务（纯 HTTP 版本，无需飞书 SDK）
# 功能：
#   1. 被动响应：接收飞书消息事件，智能回复
#   2. 主动推送：每天早上 9:00 发送每日简报
#   3. 定时快报：每 4 小时发送市场信号摘要
#   4. 手动触发：浏览器访问 /trigger_briefing 立即推送
#
# 架构：
#   Flask 主线程：处理飞书事件推送
#   schedule 子线程：管理定时任务
# ============================================

import os
from dotenv import load_dotenv
load_dotenv()

import json
import time
import hashlib
import threading
import requests
from datetime import datetime

from flask import Flask, request, jsonify
import schedule

from feishu_agent import process_message
from briefing_formatter import (
    load_latest_briefing,
    format_briefing_for_feishu,
    get_signal_summary,
)

# ============================================
# 第 1 步：读取配置
# ============================================

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")
TARGET_CHAT_ID = os.getenv("FEISHU_CHAT_ID", "")

if not TARGET_CHAT_ID:
    print("⚠️ 未配置 FEISHU_CHAT_ID，定时推送暂不可用")
    print("   请先获取群聊 ID 并写入 .env")

# ============================================
# 第 2 步：获取 tenant_access_token（纯 HTTP）
# ============================================

def get_tenant_access_token() -> str:
    """
    通过 HTTP POST 获取 tenant_access_token
    文档：https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
    """
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data["tenant_access_token"]
        else:
            print(f"❌ 获取 token 失败：{data.get('msg', '')}")
            return ""
    except Exception as e:
        print(f"❌ 获取 token 异常：{e}")
        return ""


# ============================================
# 第 3 步：发送消息（纯 HTTP）
# ============================================

def send_message_to_chat(chat_id: str, text: str) -> bool:
    """
    向飞书群发送文本消息
    文档：https://open.feishu.cn/document/server-docs/im-v1/message/create
    """
    token = get_tenant_access_token()
    if not token:
        print("❌ 无法获取 token，消息发送失败")
        return False
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            print(f"✅ 消息发送成功，message_id: {data['data']['message_id']}")
            return True
        else:
            print(f"❌ 消息发送失败：{data.get('msg', '')}")
            return False
    except Exception as e:
        print(f"❌ 消息发送异常：{e}")
        return False


def send_message_to_user(open_id: str, text: str) -> bool:
    """
    向用户发送私聊消息
    """
    token = get_tenant_access_token()
    if not token:
        return False
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            print(f"✅ 私聊消息发送成功")
            return True
        else:
            print(f"❌ 私聊消息发送失败：{data.get('msg', '')}")
            return False
    except Exception as e:
        print(f"❌ 私聊消息发送异常：{e}")
        return False


# ============================================
# 第 4 步：Flask 应用
# ============================================

app = Flask(__name__)

# ============================================
# 第 5 步：处理飞书事件
# ============================================

def verify_signature(timestamp: str, nonce: str, body: str, signature: str) -> bool:
    """
    验证飞书推送的签名
    签名算法：sha256(timestamp + nonce + verification_token + body)
    """
    raw = f"{timestamp}{nonce}{VERIFICATION_TOKEN}{body}"
    computed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return computed == signature


def handle_event(data: dict) -> None:
    """
    处理飞书推送的事件
    """
    event = data.get("event", {})
    event_type = event.get("type", "")
    
    if event_type != "im.message.receive_v1":
        return
    
    # 提取消息内容
    message = event.get("message", {})
    message_id = message.get("message_id", "")
    chat_id = message.get("chat_id", "")
    content_str = message.get("content", "{}")
    
    # 提取发送者
    sender = event.get("sender", {})
    sender_open_id = sender.get("sender_id", {}).get("open_id", "")
    
    # 解析消息文本
    try:
        content = json.loads(content_str)
        user_text = content.get("text", "").strip()
    except json.JSONDecodeError:
        print(f"⚠️ 消息内容解析失败")
        return
    
    if not user_text:
        return
    
    print(f"\n📨 收到消息")
    print(f"   发送者: {sender_open_id[:15]}...")
    print(f"   内容: {user_text[:80]}")
    print(f"   chat_id: {chat_id}")
    
    # 调用智能体
    reply_text = process_message(user_text)
    print(f"📤 回复: {reply_text[:80]}")
    
    # 发送回复
    if chat_id:
        send_message_to_chat(chat_id, reply_text)
    elif sender_open_id:
        send_message_to_user(sender_open_id, reply_text)


@app.route("/feishu/webhook", methods=["POST"])
def feishu_webhook():
    """
    飞书事件订阅端点
    """
    body = request.get_data(as_text=True)
    
    # URL 验证
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return jsonify({"code": 1, "msg": "invalid json"}), 400
    
    req_type = data.get("type", "")
    
    if req_type == "url_verification":
        challenge = data.get("challenge", "")
        print(f"✅ URL 验证请求，返回 challenge")
        return jsonify({"challenge": challenge})
    
    if req_type == "event_callback":
        handle_event(data)
        return jsonify({"code": 0, "msg": "ok"})
    
    return jsonify({"code": 0, "msg": "ok"})


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "service": "飞书机器人完整服务"})


@app.route("/trigger_briefing", methods=["GET"])
def trigger_briefing():
    """手动触发每日简报推送"""
    job_daily_briefing()
    return jsonify({"status": "ok", "message": "简报推送已触发"})


@app.route("/trigger_snapshot", methods=["GET"])
def trigger_snapshot():
    """手动触发信号快报推送"""
    job_signal_snapshot()
    return jsonify({"status": "ok", "message": "信号快报已触发"})


# ============================================
# 第 6 步：定时任务
# ============================================

def job_daily_briefing():
    """每日简报推送"""
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 推送每日简报")
    
    if not TARGET_CHAT_ID:
        print("❌ 未配置 TARGET_CHAT_ID")
        return
    
    content = load_latest_briefing()
    if content.startswith("📭") or content.startswith("⚠️"):
        send_message_to_chat(TARGET_CHAT_ID, content)
        return
    
    formatted = format_briefing_for_feishu(content, max_length=4000)
    today = datetime.now().strftime("%Y年%m月%d日")
    full_msg = f"📰 {today} 每日金融情报简报\n\n{formatted}"
    
    send_message_to_chat(TARGET_CHAT_ID, full_msg)
    print("✅ 每日简报推送完成")


def job_signal_snapshot():
    """市场信号快报推送"""
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 推送信号快报")
    
    if not TARGET_CHAT_ID:
        print("❌ 未配置 TARGET_CHAT_ID")
        return
    
    summary = get_signal_summary()
    if summary:
        send_message_to_chat(TARGET_CHAT_ID, summary)
        print("✅ 信号快报推送完成")
    else:
        print("⚠️ 暂无信号数据")


def job_health_check():
    """健康检查（仅控制台打印）"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"💓 [{now}] 服务运行中")


def run_scheduler():
    """定时任务调度器（独立线程）"""
    print("⏳ 定时任务调度器已启动")
    print("   每日简报：09:00")
    print("   信号快报：09:00 / 13:00 / 17:00")
    print()
    
    schedule.every().day.at("09:00").do(job_daily_briefing)
    schedule.every().day.at("09:00").do(job_signal_snapshot)
    schedule.every().day.at("13:00").do(job_signal_snapshot)
    schedule.every().day.at("17:00").do(job_signal_snapshot)
    schedule.every().hour.do(job_health_check)
    
    while True:
        schedule.run_pending()
        time.sleep(1)


# ============================================
# 第 7 步：启动服务
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 飞书机器人完整服务启动")
    print("=" * 50)
    print(f"Webhook 地址: http://0.0.0.0:5188/feishu/webhook")
    print(f"推送目标群: {TARGET_CHAT_ID[:25] if TARGET_CHAT_ID else '未配置'}...")
    print()
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    print("📋 手动触发推送（浏览器访问）:")
    print("   https://你的ngrok地址/trigger_briefing")
    print("   https://你的ngrok地址/trigger_snapshot")
    print()
    
    app.run(host="0.0.0.0", port=5188, debug=False)