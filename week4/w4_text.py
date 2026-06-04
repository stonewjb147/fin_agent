from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route("/feishu/webhook", methods=["POST"])
def webhook():
    print("✅ 请求已到达 webhook！")
    
    # 获取原始请求体
    body = request.get_data(as_text=True)
    print(f"原始请求体: {body[:500]}")
    
    try:
        data = json.loads(body)
        print(f"解析成功，type: {data.get('type')}")
    except:
        print("JSON 解析失败")
    
    return jsonify({"code": 0, "msg": "ok"})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5188, debug=False)