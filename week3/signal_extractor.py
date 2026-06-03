# ============================================
# 金融信号提取脚本
# 功能：使用 DeepSeek 从新闻中提取结构化信号
# 输入：聚类后的新闻 JSON
# 输出：signals.jsonl（每行一个 JSON 信号对象）
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime

# 导入我们刚才定义的信号模型
from signal_model import FinancialSignal

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek

# 导入 Prompt 模板
from langchain.prompts import PromptTemplate

print("=" * 60)
print("📊 金融信号提取器")
print("=" * 60)

# ============================================
# 第 1 步：加载聚类后的新闻数据
# ================================

data_dir = "/users/stonewjb/fin_agent_projects/data"

# 找到最新的聚类新闻文件
json_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("news_clustered_") and f.endswith(".json")
]

if not json_files:
    raise FileNotFoundError("未找到聚类新闻文件，请先运行 topic_clustering.py")

# 按文件名排序，取最新的
json_files.sort(reverse=True)
latest_file = os.path.join(data_dir, json_files[0])
print(f"\n正在加载新闻数据：{latest_file}")

with open(latest_file, "r", encoding="utf-8") as f:
    articles = json.load(f)

print(f"成功加载 {len(articles)} 条新闻")

# ============================================
# 第 2 步：创建 DeepSeek 模型实例
# ============================================

print("\n正在连接 DeepSeek 模型...")

llm = ChatDeepSeek(
    model="deepseek-chat",                      # DeepSeek 聊天模型
    temperature=0,                               # 温度 0，输出最稳定
    api_key=os.getenv("DEEPSEEK_API_KEY")       # 从 .env 读取密钥
)

print("DeepSeek 模型连接成功")

# ============================================
# 第 3 步：定义信号提取的提示词模板
# ============================================

# 这是给 DeepSeek 的"任务说明书"
# 它告诉模型：你是一个信号提取专家，按指定 JSON 格式输出
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

# 创建 Prompt 模板
prompt = PromptTemplate(
    template=extraction_template,
    input_variables=["title"]  # 只需要新闻标题作为输入
)

print("提示词模板创建完成")

# ============================================
# 第 4 步：定义信号提取函数
# ============================================

def extract_signal_from_title(title: str, source_topic: int) -> FinancialSignal:
    """
    从单条新闻标题中提取金融信号
    
    参数：
        title: 新闻标题文本
        source_topic: 新闻所属主题编号
    
    返回：
        FinancialSignal 对象
    
    如果提取失败，返回一个"中性"的默认信号
    """
    try:
        # 用提示词模板生成完整的提示词
        full_prompt = prompt.format(title=title)
        
        # 调用 DeepSeek 大模型
        response = llm.invoke(full_prompt)
        
        # 获取模型返回的文本内容
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # 清理响应文本（去掉可能的 Markdown 代码块标记）
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]  # 去掉 ```json
        if response_text.startswith("```"):
            response_text = response_text[3:]  # 去掉 ```
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
        
        return signal
    
    except json.JSONDecodeError:
        # JSON 解析失败（模型输出格式不对）
        print(f"  ⚠️ JSON 解析失败，使用默认信号")
        print(f"     原始标题：{title[:60]}...")
        print(f"     模型输出：{response_text[:100]}...")
        return FinancialSignal(
            direction="中性",
            asset="未知",
            strength="低",
            confidence=0.3,
            summary="信号提取失败",
            keywords=[],
            source_title=title,
            source_topic=source_topic
        )
    
    except Exception as e:
        # 其他异常
        print(f"  ⚠️ 信号提取异常：{e}")
        return FinancialSignal(
            direction="中性",
            asset="未知",
            strength="低",
            confidence=0.3,
            summary=f"提取失败：{str(e)[:30]}",
            keywords=[],
            source_title=title,
            source_topic=source_topic
        )

# ============================================
# 第 5 步：测试单条信号提取
# ============================================

print("\n" + "=" * 60)
print("测试单条信号提取")
print("=" * 60)

# 取第一条有意义的新闻进行测试
test_title = ""
for article in articles:
    title = article.get("title", "")
    if title and len(title) > 10:
        test_title = title
        break

if test_title:
    print(f"\n测试标题：{test_title}")
    print("\n正在提取信号...")
    
    # 调用提取函数
    test_topic = articles[0].get("topic_id", -1) if articles else -1
    test_signal = extract_signal_from_title(test_title, test_topic)
    
    # 打印结果
    print(f"\n提取结果：")
    print(f"  方向：{test_signal.direction}")
    print(f"  资产：{test_signal.asset}")
    print(f"  强度：{test_signal.strength}")
    print(f"  置信度：{test_signal.confidence}")
    print(f"  摘要：{test_signal.summary}")
    print(f"  关键词：{', '.join(test_signal.keywords)}")
    print(f"  信号有效性：{test_signal.is_valid()}")
else:
    print("\n⚠️ 未找到有效的测试标题")

# ============================================
# 第 6 步：确认是否需要批量处理
# ============================================

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
print()
print("单条信号提取验证通过！")
print()
print("注意：由于 DeepSeek API 按 Token 计费，")
print("批量处理所有新闻将在周四的脚本中执行。")
print("今天的重点是验证信号模型和提取逻辑是否正确。")