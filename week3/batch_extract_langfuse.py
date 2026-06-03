# ============================================
# 批量信号提取脚本（带 Langfuse 监控）
# 功能：提取信号 + 追踪每次 LLM 调用
# 在周四脚本基础上增加了 Langfuse 集成
# ============================================

import os
# 消除 huggingface tokenizers 的并行警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
# 加载 .env 中的 API 密钥
load_dotenv()

import json
import time
from datetime import datetime
from collections import Counter

# 导入信号模型
from signal_model import FinancialSignal

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek

# 导入 LangChain Prompt 模板
from langchain.prompts import PromptTemplate

# 导入 Langfuse 回调处理器
from langfuse.callback import CallbackHandler

print("=" * 60)
print("📊 批量金融信号提取器（带 Langfuse 监控）")
print("=" * 60)

# ============================================
# 第 1 步：初始化 Langfuse 回调
# ============================================

print("\n正在连接 Langfuse 监控...")

# 创建 Langfuse 回调处理器
# 这个处理器会自动追踪 LLM 调用、Token 消耗、延迟等
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),  # 公钥
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),  # 私钥
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")  # Langfuse 服务地址
)

print("Langfuse 监控连接成功")
print("每条信号提取都会在 Langfuse 后台生成追踪记录")

# ============================================
# 第 2 步：加载新闻数据
# ============================================

data_dir = "/users/stonewjb/fin_agent_projects/data"

# 找到最新的聚类新闻文件
json_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("news_clustered_") and f.endswith(".json")
]

if not json_files:
    raise FileNotFoundError("未找到聚类新闻文件，请先运行 topic_clustering.py")

json_files.sort(reverse=True)
latest_file = os.path.join(data_dir, json_files[0])
print(f"\n正在加载新闻数据：{latest_file}")

with open(latest_file, "r", encoding="utf-8") as f:
    articles = json.load(f)

print(f"成功加载 {len(articles)} 条新闻")

# 过滤有效新闻（标题长度 > 10）
valid_articles = [
    a for a in articles
    if a.get("title") and len(a.get("title", "")) > 10
]
print(f"有效新闻数：{len(valid_articles)}")

# ============================================
# 第 3 步：创建 DeepSeek 模型（绑定 Langfuse）
# ============================================

print("\n正在连接 DeepSeek 模型...")

# 创建模型实例，同时传入 Langfuse 回调
# 这样每次 LLM 调用都会自动被追踪
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]  # 关键：绑定 Langfuse 回调
)

print("DeepSeek 模型连接成功（已绑定 Langfuse 追踪）")

# 提示词模板
extraction_template = """你是一位专业的金融信号分析师。请从以下新闻标题中提取投资信号。

【要求】
1. 判断信号方向（看多/看空/中性）
2. 识别涉及的资产/板块
3. 评估信号强度（高/中/低）
4. 评估置信度（0.0 到 1.0）
5. 写一句话摘要（不超过 50 字）
6. 提取 2-4 个关键触发词

【输出格式】
请严格按照以下 JSON 格式输出：

{{
  "direction": "看多",
  "asset": "白酒板块",
  "strength": "高",
  "confidence": 0.85,
  "summary": "一句话摘要",
  "keywords": ["关键词1", "关键词2"]
}}

【新闻标题】
{title}

【JSON 输出】"""

prompt = PromptTemplate(
    template=extraction_template,
    input_variables=["title"]
)

print("提示词模板创建完成")

# ============================================
# 第 4 步：批量提取信号
# ============================================

print("\n" + "=" * 60)
print("开始批量提取信号（带 Langfuse 追踪）")
print("=" * 60)
print(f"待处理：{len(valid_articles)} 条新闻")
print(f"预计耗时：{len(valid_articles) * 3 // 60} 分钟")
print()

today = datetime.now().strftime("%Y%m%d")
output_jsonl = f"{data_dir}/signals_{today}.jsonl"

success_count = 0
failure_count = 0
all_signals = []

# 记录开始时间（用于统计总耗时）
start_time = time.time()

for i, article in enumerate(valid_articles, 1):
    title = article.get("title", "")
    source_topic = article.get("topic_id", -1)
    
    # 每 5 条打印一次进度
    if i % 5 == 0 or i == 1:
        elapsed = time.time() - start_time
        speed = i / elapsed * 60 if elapsed > 0 else 0
        print(f"  进度：{i}/{len(valid_articles)} ({i*100//len(valid_articles)}%) | 速度：{speed:.1f} 条/分钟")
    
    try:
        # 构建提示词
        full_prompt = prompt.format(title=title)
        
        # 调用 LLM（这次调用会自动记录到 Langfuse）
        response = llm.invoke(full_prompt)
        
        # 解析响应
        response_text = response.content if hasattr(response, 'content') else str(response)
        response_text = response_text.strip()
        
        # 清理 Markdown 代码块
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # 解析 JSON
        data = json.loads(response_text)
        
        # 创建信号对象
        signal = FinancialSignal(
            direction=data.get("direction", "中性"),
            asset=data.get("asset", "未知"),
            strength=data.get("strength", "低"),
            confidence=float(data.get("confidence", 0.5)),
            summary=data.get("summary", ""),
            keywords=data.get("keywords", []),
            source_title=title,
            source_topic=source_topic
        )
        
        if signal.is_valid():
            success_count += 1
        else:
            failure_count += 1
        
        all_signals.append(signal)
        
        # 追加到 JSONL 文件
        with open(output_jsonl, "a", encoding="utf-8") as f:
            f.write(signal.to_json() + "\n")
    
    except json.JSONDecodeError:
        failure_count += 1
        fallback = FinancialSignal(
            direction="中性", asset="未知", strength="低",
            confidence=0.3, summary="JSON解析失败",
            keywords=[], source_title=title, source_topic=source_topic
        )
        all_signals.append(fallback)
        with open(output_jsonl, "a", encoding="utf-8") as f:
            f.write(fallback.to_json() + "\n")
    
    except Exception as e:
        failure_count += 1
        fallback = FinancialSignal(
            direction="中性", asset="未知", strength="低",
            confidence=0.3, summary=f"异常：{str(e)[:20]}",
            keywords=[], source_title=title, source_topic=source_topic
        )
        all_signals.append(fallback)
        with open(output_jsonl, "a", encoding="utf-8") as f:
            f.write(fallback.to_json() + "\n")
    
    # 避免触发频率限制
    time.sleep(0.5)

# 计算总耗时
total_time = time.time() - start_time
print(f"\n批量提取完成！")
print(f"  总耗时：{total_time/60:.1f} 分钟")
print(f"  有效信号：{success_count} 条")
print(f"  失败信号：{failure_count} 条")
print(f"  信号文件：{output_jsonl}")

# ============================================
# 第 5 步：刷新 Langfuse（确保数据上传）
# ============================================

print("\n正在上传追踪数据到 Langfuse...")
langfuse_handler.flush()
print("Langfuse 数据上传完成")
print("请打开 https://cloud.langfuse.com 查看调用追踪")

# ============================================
# 第 6 步：信号统计
# ============================================

print("\n" + "=" * 60)
print("📈 信号统计概览")
print("=" * 60)

valid_signals = [s for s in all_signals if s.is_valid()]

if valid_signals:
    direction_counter = Counter(s.direction for s in valid_signals)
    print(f"\n方向分布：")
    for d, c in direction_counter.most_common():
        print(f"  {d}：{c} 条（{c/len(valid_signals)*100:.1f}%）")
    
    asset_counter = Counter(s.asset for s in valid_signals)
    print(f"\n热门板块 Top 5：")
    for asset, count in asset_counter.most_common(5):
        print(f"  {asset}：{count} 条")
    
    avg_conf = sum(s.confidence for s in valid_signals) / len(valid_signals)
    print(f"\n平均置信度：{avg_conf:.2f}")

print("\n✅ 全部完成！记得去 Langfuse 后台查看追踪数据")