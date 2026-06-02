# ============================================
# 批量金融信号提取脚本
# 功能：对聚类后的所有新闻逐条提取信号
# 输入：news_clustered_YYYYMMDD.json
# 输出：signals_YYYYMMDD.jsonl（每行一个信号）
#       signal_stats_YYYYMMDD.json（统计分析）
# 预计运行时间：10-20 分钟（取决于新闻数量）
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

# 导入我们定义的信号模型
from signal_model import FinancialSignal

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek

# 导入 Prompt 模板
from langchain.prompts import PromptTemplate

# ============================================
# 第 1 步：加载聚类后的新闻数据
# ============================================

print("=" * 60)
print("📊 批量金融信号提取器")
print("=" * 60)

data_dir = "/users/stonewjb/fin_agent_projects/data"

# 找到最新的聚类新闻文件
json_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("news_clustered_") and f.endswith(".json")
]

if not json_files:
    raise FileNotFoundError(
        "未找到聚类新闻文件，请先运行 topic_clustering.py"
    )

# 按文件名排序，取最新的
json_files.sort(reverse=True)
latest_file = os.path.join(data_dir, json_files[0])

print(f"\n正在加载新闻数据：{latest_file}")

with open(latest_file, "r", encoding="utf-8") as f:
    articles = json.load(f)

print(f"成功加载 {len(articles)} 条新闻")

# ============================================
# 第 2 步：过滤有效新闻
# ============================================

# 只保留标题不为空且长度大于 10 的新闻
# 太短的标题无法提取有效信号
valid_articles = []
for article in articles:
    title = article.get("title", "")
    if title and len(title) > 10:
        valid_articles.append(article)

print(f"有效新闻数（标题长度 > 10）：{len(valid_articles)}")
print(f"跳过的无效新闻数：{len(articles) - len(valid_articles)}")

# ============================================
# 第 3 步：创建 DeepSeek 模型和提示词
# ============================================

print("\n正在连接 DeepSeek 模型...")

# 创建 DeepSeek 模型实例
llm = ChatDeepSeek(
    model="deepseek-chat",                       # DeepSeek 聊天模型
    temperature=0,                                # 温度 0，输出最稳定
    api_key=os.getenv("DEEPSEEK_API_KEY")        # 从 .env 读取密钥
)

print("DeepSeek 模型连接成功")

# 定义信号提取的提示词模板
# 这是给 DeepSeek 的"任务说明书"
extraction_template = """你是一位专业的金融信号分析师。请从以下新闻标题中提取投资信号。

【要求】
1. 判断信号方向（看多/看空/中性）
   - 看多：利好消息，如业绩增长、政策支持、收购成功
   - 看空：利空消息，如业绩下滑、监管处罚、债务危机
   - 中性：客观报道，无明显多空倾向

2. 识别涉及的资产/板块
   - 示例：白酒板块、新能源、A股、人民币、利率
   - 尽量精确，不要用"中国股市"这种太宽泛的词

3. 评估信号强度（高/中/低）
   - 高：重大利好/利空，可能引发明显波动
   - 中：一般性利好/利空
   - 低：轻微影响或无影响

4. 评估置信度（0.0 到 1.0 之间的小数）
   - 标题信息明确的用高置信度（0.8-1.0）
   - 信息模糊的用低置信度（0.3-0.6）

5. 写一句话摘要（不超过 50 字）

6. 提取 2-4 个关键触发词

【输出格式】
请严格按照以下 JSON 格式输出，不要添加任何其他内容：

{{
  "direction": "看多",
  "asset": "白酒板块",
  "strength": "高",
  "confidence": 0.85,
  "summary": "一句话摘要",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}}

【新闻标题】
{title}

【JSON 输出】"""

# 创建 Prompt 模板对象
prompt = PromptTemplate(
    template=extraction_template,
    input_variables=["title"]  # 只需要新闻标题作为输入
)

print("提示词模板创建完成")

# ============================================
# 第 4 步：定义信号提取函数（带重试机制）
# ============================================

def extract_signal_from_title(title: str, source_topic: int, max_retries: int = 2) -> FinancialSignal:
    """
    从单条新闻标题中提取金融信号，带重试机制
    
    参数：
        title: 新闻标题文本
        source_topic: 新闻所属主题编号
        max_retries: 最大重试次数（默认 2 次）
    
    返回：
        FinancialSignal 对象
    """
    # 构建完整的提示词
    full_prompt = prompt.format(title=title)
    
    # 重试循环
    for attempt in range(max_retries + 1):
        try:
            # 调用 DeepSeek 大模型
            response = llm.invoke(full_prompt)
            
            # 获取模型返回的文本内容
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # 清理响应文本
            # 去掉可能的 Markdown 代码块标记 ```json ... ```
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # 去掉开头的 ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # 去掉开头的 ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # 去掉结尾的 ```
            response_text = response_text.strip()
            
            # 将 JSON 字符串解析为 Python 字典
            data = json.loads(response_text)
            
            # 用解析出的数据创建 FinancialSignal 对象
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
            
            # 如果信号有效，直接返回
            if signal.is_valid():
                return signal
            else:
                # 信号无效，重试
                if attempt < max_retries:
                    time.sleep(1)  # 等待 1 秒后重试
                    continue
                else:
                    return signal  # 重试耗尽，返回无效信号
        
        except json.JSONDecodeError:
            # JSON 解析失败（模型输出格式不对）
            if attempt < max_retries:
                time.sleep(1)  # 等待 1 秒后重试
                continue
            else:
                # 重试耗尽，返回默认中性信号
                return FinancialSignal(
                    direction="中性",
                    asset="未知",
                    strength="低",
                    confidence=0.3,
                    summary="JSON解析失败",
                    keywords=[],
                    source_title=title,
                    source_topic=source_topic
                )
        
        except Exception as e:
            # 其他异常
            if attempt < max_retries:
                time.sleep(2)  # 网络错误等，等 2 秒重试
                continue
            else:
                return FinancialSignal(
                    direction="中性",
                    asset="未知",
                    strength="低",
                    confidence=0.3,
                    summary=f"提取失败：{str(e)[:20]}",
                    keywords=[],
                    source_title=title,
                    source_topic=source_topic
                )
    
    # 不应该走到这里，但以防万一
    return FinancialSignal(
        direction="中性",
        asset="未知",
        strength="低",
        confidence=0.3,
        summary="未知错误",
        keywords=[],
        source_title=title,
        source_topic=source_topic
    )

# ============================================
# 第 5 步：批量提取信号
# ============================================

print("\n" + "=" * 60)
print("开始批量提取信号")
print("=" * 60)
print(f"待处理新闻数：{len(valid_articles)} 条")
print(f"预计耗时：{len(valid_articles) * 3 // 60} 分钟")
print("请耐心等待...")
print()

# 准备输出文件
today = datetime.now().strftime("%Y%m%d")
output_jsonl = f"{data_dir}/signals_{today}.jsonl"

# 统计变量
success_count = 0        # 成功提取数
failure_count = 0        # 失败数
valid_count = 0          # 有效信号数
all_signals = []         # 存放所有信号对象（用于后续统计）

# 逐条处理新闻
for i, article in enumerate(valid_articles, 1):
    # 获取标题和主题编号
    title = article.get("title", "")
    source_topic = article.get("topic_id", -1)
    
    # 打印进度（每 5 条打印一次，避免刷屏）
    if i % 5 == 0 or i == 1 or i == len(valid_articles):
        print(f"  进度：{i}/{len(valid_articles)} ({i*100//len(valid_articles)}%)")
    
    # 提取信号
    signal = extract_signal_from_title(title, source_topic)
    
    # 统计
    if signal.is_valid():
        success_count += 1
        valid_count += 1
    else:
        failure_count += 1
        # 无效信号也保存（后续可以分析失败原因）
    
    all_signals.append(signal)
    
    # 每处理完一条，立即追加到 JSONL 文件（防止中途崩溃丢失数据）
    with open(output_jsonl, "a", encoding="utf-8") as f:
        f.write(signal.to_json() + "\n")
    
    # 每次 API 调用后稍作暂停，避免触发频率限制
    # DeepSeek 免费版没有严格限制，但加延迟更稳妥
    time.sleep(0.5)

print(f"\n批量提取完成！")
print(f"  成功提取（有效信号）：{valid_count} 条")
print(f"  提取失败（无效信号）：{failure_count} 条")
print(f"  信号文件已保存到：{output_jsonl}")

# ============================================
# 第 6 步：信号统计分析
# ============================================

print("\n" + "=" * 60)
print("📈 信号统计分析")
print("=" * 60)

# 只统计有效信号
valid_signals = [s for s in all_signals if s.is_valid()]

if not valid_signals:
    print("\n⚠️ 没有有效信号，跳过统计分析")
else:
    # --- 方向统计 ---
    direction_counter = Counter(s.direction for s in valid_signals)
    print(f"\n📊 信号方向分布：")
    for direction, count in direction_counter.most_common():
        pct = count / len(valid_signals) * 100
        print(f"  {direction}：{count} 条（{pct:.1f}%）")
    
    # --- 板块统计 ---
    asset_counter = Counter(s.asset for s in valid_signals)
    print(f"\n📊 热门板块 Top 5：")
    for asset, count in asset_counter.most_common(5):
        print(f"  {asset}：{count} 条")
    
    # --- 强度统计 ---
    strength_counter = Counter(s.strength for s in valid_signals)
    print(f"\n📊 信号强度分布：")
    for strength, count in strength_counter.most_common():
        pct = count / len(valid_signals) * 100
        print(f"  {strength}：{count} 条（{pct:.1f}%）")
    
    # --- 置信度统计 ---
    avg_confidence = sum(s.confidence for s in valid_signals) / len(valid_signals)
    high_confidence = sum(1 for s in valid_signals if s.confidence >= 0.8)
    print(f"\n📊 置信度统计：")
    print(f"  平均置信度：{avg_confidence:.2f}")
    print(f"  高置信度信号（≥0.8）：{high_confidence} 条（{high_confidence/len(valid_signals)*100:.1f}%）")
    
    # --- 关键词统计 ---
    all_keywords = []
    for s in valid_signals:
        all_keywords.extend(s.keywords)
    keyword_counter = Counter(all_keywords)
    print(f"\n📊 热门关键词 Top 10：")
    for keyword, count in keyword_counter.most_common(10):
        print(f"  {keyword}：{count} 次")

# ============================================
# 第 7 步：保存统计分析结果
# ============================================

stats = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "source_file": latest_file,
    "total_news": len(valid_articles),
    "total_signals": len(valid_signals),
    "failed_signals": failure_count,
    "direction_distribution": dict(direction_counter) if valid_signals else {},
    "top_assets": dict(asset_counter.most_common(5)) if valid_signals else {},
    "strength_distribution": dict(strength_counter) if valid_signals else {},
    "average_confidence": round(avg_confidence, 2) if valid_signals else 0,
    "high_confidence_count": high_confidence if valid_signals else 0,
    "top_keywords": dict(keyword_counter.most_common(10)) if valid_signals else {},
}

stats_file = f"{data_dir}/signal_stats_{today}.json"
with open(stats_file, "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)

print(f"\n✅ 统计分析已保存到：{stats_file}")

print("\n" + "=" * 60)
print("✅ 全部完成！")
print("=" * 60)