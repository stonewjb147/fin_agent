# ============================================
# 新闻主题聚类脚本
# 功能：加载新闻 JSON → BERTopic 聚类 → 输出主题报告
# 输入：../data/news_YYYYMMDD.json
# 输出：../data/news_clustered_YYYYMMDD.json（带主题标签）
#       ../data/topic_report_YYYYMMDD.md（可读报告）
# 运行时间：30-60 秒（8GB Intel Mac）
# ============================================

# --- 系统配置（放在最前面） ---
import os
# 消除 huggingface tokenizers 的并行警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import json
from datetime import datetime
import warnings
# 忽略 BERTopic 的一些非关键提示，保持终端输出整洁
warnings.filterwarnings("ignore")

# ============================================
# 第 1 步：加载新闻数据
# ============================================

print("=" * 60)
print("📊 新闻主题聚类分析")
print("=" * 60)

# 定位最新的新闻数据文件
data_dir = "/users/stonewjb/fin_agent_projects/data"

# 找到所有以 news_ 开头、以 .json 结尾的文件
json_files = [
    f for f in os.listdir(data_dir)
    if f.startswith("news_tkshare") and f.endswith(".json")
]

# 如果没有找到文件，直接报错退出
if not json_files:
    raise FileNotFoundError(
        "未找到新闻数据文件，请先运行 news_fetcher.py 抓取新闻"
    )

# 按文件名排序（日期在文件名里，最新的在最后）
json_files.sort(reverse=True)
latest_file = os.path.join(data_dir, json_files[0])

print(f"\n正在加载新闻数据：{latest_file}")

# 读取 JSON 文件，encoding='utf-8' 确保中文正常显示
with open(latest_file, "r", encoding="utf-8") as f:
    articles = json.load(f)

print(f"成功加载 {len(articles)} 条新闻")

# ============================================
# 第 2 步：提取新闻文本
# ============================================

# BERTopic 的输入是一个文本列表，每条新闻对应一个字符串
# 我们把标题和描述拼接起来，形成完整的文档
docs = []  # 存放处理后的文档列表

for article in articles:
    # 获取标题，如果没有就用空字符串
    title = article.get("title", "")
    # 获取描述
    description = article.get("description", "")

    # 如果描述不为空且和标题不同，就拼接起来
    if description and description != title:
        full_text = f"{title}。{description}"
    else:
        # 否则只用标题
        full_text = title

    # 过滤掉空文本和太短的文本（少于 10 个字符无意义）
    if full_text and len(full_text) > 5:
        docs.append(full_text)
    else:
        # 太短的标记为"无内容"
        docs.append("无内容")

print(f"有效文档数（文本长度 > 10）：{len([d for d in docs if d != '无内容'])}")

# 打印前 3 条文档，预览数据质量
print("\n文档预览（前 3 条，各显示 100 字）：")
for i, doc in enumerate(docs[:8], 1):
    print(f"  {i}. {doc[:100]}...")

# ============================================
# 第 3 步：使用 BERTopic 进行主题聚类
# ============================================

from bertopic import BERTopic

print("\n" + "=" * 60)
print("正在进行主题聚类...")
print("（在 8GB Intel Mac 上约需 30-60 秒，请耐心等待）")
print("=" * 60)

# 初始化 BERTopic 模型
# 各参数含义：
#   language="multilingual" → 支持中文等多语言
#   min_topic_size=3        → 至少 3 篇文档才能形成独立主题
#   verbose=True            → 显示进度信息
topic_model = BERTopic(
    language="multilingual",
    min_topic_size=3,
    verbose=True
)

# fit_transform 执行实际聚类
# 返回值：
#   topics → 列表，长度=文档数，每个值是该文档的主题编号
#            -1 表示"噪声"（不属于任何主题）
#   probs  → 列表，长度=文档数，每个文档属于其主题的置信度
topics, probs = topic_model.fit_transform(docs)

# 统计主题数量
# set(topics) 去重后得到所有主题编号
# 如果 -1 存在，需要减掉（-1 是噪声，不算真正主题）
unique_topics = set(topics)
noise_count = list(topics).count(-1)
topic_count = len(unique_topics) - (1 if -1 in unique_topics else 0)

print(f"\n聚类完成！")
print(f"  识别主题数：{topic_count} 个")
print(f"  噪声文档数：{noise_count} 条（无法归类的新闻）")

# ============================================
# 第 4 步：查看每个主题的关键词
# ============================================

print("\n" + "=" * 60)
print("📌 主题关键词汇总")
print("=" * 60)

# get_topic_info() 返回 DataFrame，包含每个主题的统计信息
topic_info = topic_model.get_topic_info()
print(f"\n主题统计表：")
print(topic_info.to_string())

# 逐个打印每个主题的 Top 5 关键词
print("\n" + "-" * 40)
print("各主题 Top 5 关键词：")
print("-" * 40)

for topic_id in sorted(set(topics)):
    # 跳过噪声主题（编号为 -1）
    if topic_id == -1:
        continue

    # get_topic(topic_id) 返回 [(关键词, 权重), ...]
    words = topic_model.get_topic(topic_id)
    if words:
        # 只取前 5 个关键词
        top_words = [word for word, weight in words[:5]]
        # 统计属于该主题的文档数
        doc_count = sum(1 for t in topics if t == topic_id)
        print(f"\n主题 {topic_id}（{doc_count} 篇文档）：")
        print(f"  关键词：{' | '.join(top_words)}")

# ============================================
# 第 5 步：把聚类结果附加到原始数据上
# ============================================

print("\n" + "=" * 60)
print("保存聚类结果")
print("=" * 60)

# 遍历原始新闻数据，给每条加上 topic_id 和置信度
for i, article in enumerate(articles):
    if i < len(topics):
        # 主题编号，Python int 转 JSON 会保留为整数
        article["topic_id"] = int(topics[i])
        # 置信度，保留 4 位小数
        if i < len(probs):
            article["topic_probability"] = round(float(probs[i]), 4)
        else:
            article["topic_probability"] = 0.0
    else:
        article["topic_id"] = -1
        article["topic_probability"] = 0.0

# 保存为带日期的新文件
today = datetime.now().strftime("%Y%m%d")
clustered_file = f"{data_dir}/news_clustered_{today}.json"

with open(clustered_file, "w", encoding="utf-8") as f:
    # ensure_ascii=False 确保中文不被转义
    # indent=2 让 JSON 格式化，便于人类阅读
    json.dump(articles, f, ensure_ascii=False, indent=2)

# 打印文件大小，确认保存成功
file_size_kb = os.path.getsize(clustered_file) / 1024
print(f"聚类结果已保存到：{clustered_file}")
print(f"文件大小：{file_size_kb:.1f} KB")

# ============================================
# 第 6 步：生成 Markdown 主题报告
# ============================================

# 构建报告内容（逐行添加到列表，最后一次性写入）
report_lines = []

# 报告标题
report_lines.append("# 金融新闻主题聚类报告")
report_lines.append("")
report_lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append(f"**新闻总数**：{len(articles)} 条")
report_lines.append(f"**识别主题数**：{topic_count} 个")
report_lines.append(f"**噪声文档数**：{noise_count} 条")
report_lines.append("")

report_lines.append("## 各主题详情")
report_lines.append("")

# 遍历每个主题，生成详细描述
for topic_id in sorted(set(topics)):
    if topic_id == -1:
        continue

    # 获取关键词
    words = topic_model.get_topic(topic_id)
    top_words = [word for word, _ in words[:5]]
    doc_count = sum(1 for t in topics if t == topic_id)

    # 主题小标题
    report_lines.append(f"### 主题 {topic_id}：{' / '.join(top_words[:3])}")
    report_lines.append("")
    report_lines.append(f"- **文档数量**：{doc_count} 篇")
    report_lines.append(f"- **关键词**：{', '.join(top_words)}")
    report_lines.append("")

    # 找该主题下置信度最高的 3 篇新闻作为代表
    topic_articles = []
    for i, t in enumerate(topics):
        if t == topic_id and i < len(articles):
            topic_articles.append(articles[i])

    # 按置信度降序排序
    topic_articles.sort(
        key=lambda x: x.get("topic_probability", 0),
        reverse=True
    )

    report_lines.append("- **代表性新闻**：")
    for article in topic_articles[:3]:
        title = article.get("title", "无标题")
        prob = article.get("topic_probability", 0)
        report_lines.append(f"  - {title}（置信度：{prob:.2f})")
    report_lines.append("")

# 保存报告
report_file = f"{data_dir}/topic_report_{today}.md"
with open(report_file, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print(f"Markdown 报告已保存到：{report_file}")

print("\n" + "=" * 60)
print("✅ 全部完成！")
print("=" * 60)