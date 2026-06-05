# ============================================
# 飞书机器人完整服务（Webhook + 定时推送）
# 基于已验证通过的 feishu_webhook.py 收发逻辑
# 新增：定时推送每日简报和信号快报
# ============================================

# ============================================
# 飞书机器人完整服务（Webhook + 定时推送）
# ============================================

import os as _os
_os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
# 强制从项目根目录加载 .env
load_dotenv(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".env"))

import os
import json
import time
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
# ===== 所有函数统一使用的 data 目录（绝对路径）=====
import os as _os
DATA_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data")
# ============================================
# 第 1 步：读取配置
# ============================================

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
TARGET_CHAT_ID = os.getenv("FEISHU_CHAT_ID", "")

if not TARGET_CHAT_ID:
    print("⚠️ 未配置 FEISHU_CHAT_ID，定时推送暂不可用")

# ============================================
# 第 2 步：获取飞书 Token
# ============================================

def get_tenant_access_token() -> str:
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data["tenant_access_token"]
        else:
            print(f"❌ 获取 Token 失败：{data}")
            return ""
    except Exception as e:
        print(f"❌ 获取 Token 异常：{e}")
        return ""


# ============================================
# 第 3 步：发送消息
# ============================================

def send_message(token: str, receive_id: str, content: str, receive_type: str) -> bool:
    """发送飞书消息"""
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_type}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            print(f"✅ 消息发送成功")
            return True
        else:
            print(f"❌ 消息发送失败：{data.get('msg', '')}")
            return False
    except Exception as e:
        print(f"❌ 发送异常：{e}")
        return False


# ============================================
# 第 4 步：Flask 应用
# ============================================

app = Flask(__name__)


# ============================================
# 第 5 步：处理消息事件（来自已验证的 feishu_webhook.py）
# ============================================

def handle_message_event(event: dict) -> None:
    """处理飞书推送的消息事件"""
    message = event.get("message", {})
    message_id = message.get("message_id", "")
    chat_id = message.get("chat_id", "")
    open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")

    # 解析消息内容
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
        user_text = content.get("text", "").strip()
    except json.JSONDecodeError:
        print("⚠️ 消息内容解析失败")
        return

    if not user_text:
        return

    print(f"\n📨 收到消息：{user_text[:80]}")
    print(f"   chat_id：{chat_id}")

    # 调用智能体
    reply_text = process_message(user_text)
    print(f"📤 回复：{reply_text[:80]}")

    # 发送回复
    token = get_tenant_access_token()
    if not token:
        return

    if chat_id:
        send_message(token, chat_id, reply_text, "chat_id")
    elif open_id:
        send_message(token, open_id, reply_text, "open_id")


# ============================================
# 第 6 步：Webhook 路由（来自已验证的 feishu_webhook.py）
# ============================================

@app.route("/feishu/webhook", methods=["POST"])
def feishu_webhook():
    body = request.get_data(as_text=True)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return jsonify({"code": 1, "msg": "Invalid JSON"}), 400

    # 新版飞书事件订阅（schema 2.0）
    header = data.get("header", {})
    event_type = header.get("event_type", "")

    print(f"\n📬 收到事件：{event_type}")

    # URL 验证
    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        return jsonify({"challenge": challenge})

    # 消息事件
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        handle_message_event(event)

    return jsonify({"code": 0, "msg": "ok"})


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "service": "飞书机器人完整服务"})


@app.route("/trigger_briefing", methods=["GET"])
def trigger_briefing():
    job_daily_briefing()
    return jsonify({"status": "ok", "message": "简报推送已触发"})


@app.route("/trigger_snapshot", methods=["GET"])
def trigger_snapshot():
    job_signal_snapshot()
    return jsonify({"status": "ok", "message": "信号快报已触发"})


# ============================================
# 第 7 步：定时任务
# ============================================

def job_daily_briefing():
    """每日简报推送"""
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 推送每日简报")
    if not TARGET_CHAT_ID:
        print("❌ 未配置 TARGET_CHAT_ID")
        return

    content = load_latest_briefing()
    if content.startswith("📭") or content.startswith("⚠️"):
        token = get_tenant_access_token()
        if token:
            send_message(token, TARGET_CHAT_ID, content, "chat_id")
        return

    formatted = format_briefing_for_feishu(content, max_length=4000)
    today = datetime.now().strftime("%Y年%m月%d日")
    full_msg = f"📰 {today} 每日金融情报简报\n\n{formatted}"

    token = get_tenant_access_token()
    if token:
        send_message(token, TARGET_CHAT_ID, full_msg, "chat_id")
    print("✅ 每日简报推送完成")


def job_signal_snapshot():
    """市场信号快报推送"""
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 推送信号快报")
    if not TARGET_CHAT_ID:
        return

    summary = get_signal_summary()
    if summary:
        token = get_tenant_access_token()
        if token:
            send_message(token, TARGET_CHAT_ID, summary, "chat_id")
        print("✅ 信号快报推送完成")


def job_health_check():
    """健康检查"""
    print(f"💓 [{datetime.now().strftime('%H:%M:%S')}] 服务运行中")


def run_scheduler():
    """定时任务调度器"""
    print("⏳ 定时任务调度器已启动")
    print("   每日简报：09:00 | 信号快报：09:00 / 13:00 / 17:00\n")

    schedule.every().day.at("09:00").do(job_daily_briefing)
    schedule.every().day.at("09:00").do(job_signal_snapshot)
    schedule.every().day.at("13:00").do(job_signal_snapshot)
    schedule.every().day.at("17:00").do(job_signal_snapshot)
    schedule.every().hour.do(job_health_check)

    while True:
        schedule.run_pending()
        time.sleep(1)


# ============================================
# 第 8 步：启动服务
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 飞书机器人完整服务启动")
    print("=" * 50)
    print(f"推送目标群: {TARGET_CHAT_ID[:25] if TARGET_CHAT_ID else '未配置'}...")
    print(f"Webhook 地址: http://0.0.0.0:5188/feishu/webhook")
    print()

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    print("📋 手动触发推送：")
    print("   https://你的ngrok地址/trigger_briefing")
    print("   https://你的ngrok地址/trigger_snapshot")
    print()

    app.run(host="0.0.0.0", port=5188, debug=False)