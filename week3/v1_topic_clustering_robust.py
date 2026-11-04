#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
================================================================================
新闻主题聚类脚本（通用健壮版）
功能：加载任意格式的新闻JSON文件 → 自动识别字段 → BERTopic聚类 → 输出报告
特点：
    1. 自动适配多种字段命名（title/tag/新闻标题, content/summary/新闻内容等）
    2. 处理空数据、小样本等边界情况，避免崩溃
    3. 详细日志输出，便于调试
    4. 模块化设计，易于添加新数据源适配器
================================================================================
"""

import os
import sys
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import warnings
warnings.filterwarnings("ignore")

# 设置环境变量，消除 tokenizers 的并行警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ============================================
# 第一部分：配置与日志
# ============================================

# 配置参数（可在此调整）
CONFIG = {
    "min_text_length": 10,           # 有效文本的最小长度（字符）
    "min_docs_for_cluster": 3,       # 聚类所需的最小有效文档数
    "bertopic_min_topic_size": 2,    # BERTopic 主题最小文档数
    "bertopic_language": "multilingual",  # 模型语言
    "verbose": True,                 # 是否打印详细信息
}

# 字段别名映射（按优先级排列）
FIELD_ALIASES = {
    "title": ["title", "tag", "新闻标题", "name", "subject", "headline"],
    "content": ["content", "summary", "description", "新闻内容", "正文", "text", "body"],
    "time": ["pub_time", "datetime", "date", "发布时间", "publish_time", "ctime"],
    "source": ["source", "来源", "media_name", "source_name"],
}

# ============================================
# 第二部分：数据加载与字段自动识别
# ============================================

def find_latest_json_file(data_dir: str, patterns: List[str] = None) -> Optional[str]:
    """
    在指定目录下查找最新的JSON文件（支持多个文件名模式）
    
    参数：
        data_dir: 数据目录路径
        patterns: 文件名模式列表，如 ["news_primary_", "akshare_news_", "news_"]
    
    返回：
        最新文件的完整路径，若未找到则返回 None
    """
    if patterns is None:
        patterns = ["news_primary_", "akshare_news_", "news_", "primary_news_"]
    
    json_files = []
    for pattern in patterns:
        json_files.extend([
            f for f in os.listdir(data_dir)
            if f.startswith(pattern) and f.endswith(".json")
        ])
    
    if not json_files:
        return None
    
    # 按文件名排序（字典序，通常日期在开头）
    json_files.sort(reverse=True)
    return os.path.join(data_dir, json_files[0])


def get_field_value(obj: Dict, field_candidates: List[str]) -> str:
    """
    从字典中按候选字段列表获取第一个非空字符串值
    
    参数：
        obj: 数据字典
        field_candidates: 候选字段名列表（按优先级）
    
    返回：
        找到的第一个非空值，否则返回空字符串
    """
    for field in field_candidates:
        if field in obj and obj[field]:
            val = str(obj[field]).strip()
            if val:
                return val
    return ""


def extract_article_text(article: Dict) -> Tuple[str, str]:
    """
    从单条新闻数据中提取标题和内容（自动适配字段名）
    
    参数：
        article: 新闻数据字典
    
    返回：
        (title, content) 元组
    """
    title = get_field_value(article, FIELD_ALIASES["title"])
    content = get_field_value(article, FIELD_ALIASES["content"])
    
    # 如果标题或内容为空，尝试从其他字段补充
    if not title and content:
        # 从内容截取前30字作为标题
        title = content[:30] + ("..." if len(content) > 30 else "")
    elif not content and title:
        # 内容为空时用标题填充
        content = title
    
    return title, content


# ============================================
# 第三部分：文本预处理与质量检查
# ============================================

def is_valid_text(text: str, min_len: int = CONFIG["min_text_length"]) -> bool:
    """
    检查文本是否有效（非空、非占位符、长度足够）
    
    参数：
        text: 待检查的文本
        min_len: 最小有效长度
    
    返回：
        True 表示有效，False 表示无效
    """
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    if len(text) < min_len:
        return False
    # 排除常见占位符
    placeholders = ["无内容", "无标题", "无摘要", "周刊提前读", "周刊精选", "None", "null", "NaN"]
    if text in placeholders:
        return False
    # 排除纯标点符号
    if re.match(r'^[\s\-_—\.,;:!?()\[\]{}""\'\n\r\t]*$', text):
        return False
    return True


def preprocess_text(title: str, content: str) -> str:
    """
    将标题和内容拼接为完整文本，并进行初步清洗
    
    参数：
        title: 标题
        content: 内容
    
    返回：
        清洗后的完整文本
    """
    # 去除首尾空白
    title = title.strip()
    content = content.strip()
    
    # 如果内容为空，只用标题
    if not content:
        return title
    
    # 如果标题为空，只用内容
    if not title:
        return content
    
    # 标题和内容都非空时拼接
    # 避免标题和内容重复
    if content.startswith(title):
        return content
    else:
        return f"{title}。{content}"


# ============================================
# 第四部分：文档列表构建
# ============================================

def build_document_list(articles: List[Dict]) -> Tuple[List[str], List[Dict]]:
    """
    从原始文章列表中提取有效文档，并记录对应的原始文章
    
    参数：
        articles: 原始文章列表
    
    返回：
        (有效文档列表, 对应的原始文章列表)
    """
    docs = []
    valid_articles = []
    
    for article in articles:
        title, content = extract_article_text(article)
        full_text = preprocess_text(title, content)
        
        if is_valid_text(full_text, CONFIG["min_text_length"]):
            docs.append(full_text)
            valid_articles.append(article)
        else:
            # 记录无效文档（仅当 verbose 开启时）
            if CONFIG["verbose"]:
                print(f"   ⚠️ 跳过无效文档: {title[:30] if title else '(无标题)'}")
    
    return docs, valid_articles


# ============================================
# 第五部分：BERTopic 聚类封装
# ============================================

def perform_clustering(docs: List[str]) -> Tuple[Any, List[int], List[float]]:
    """
    执行 BERTopic 聚类
    
    参数：
        docs: 文档列表
    
    返回：
        (topic_model, topics, probs) 元组
    """
    from bertopic import BERTopic
    
    print("\n" + "=" * 60)
    print("正在进行主题聚类（约 30-60 秒，请耐心等待）...")
    print("=" * 60)
    
    topic_model = BERTopic(
        language=CONFIG["bertopic_language"],
        min_topic_size=CONFIG["bertopic_min_topic_size"],
        verbose=CONFIG["verbose"],
        # 可添加其他参数，如 embedding_model 等
    )
    
    topics, probs = topic_model.fit_transform(docs)
    
    return topic_model, topics, probs


# ============================================
# 第六部分：结果保存与报告生成
# ============================================

def save_clustered_data(articles: List[Dict], topics: List[int], probs: List[float], output_file: str):
    """为原始文章添加主题标签并保存"""
    for i, article in enumerate(articles):
        if i < len(topics):
            article["topic_id"] = int(topics[i])
            article["topic_probability"] = round(float(probs[i]), 4) if i < len(probs) else 0.0
        else:
            article["topic_id"] = -1
            article["topic_probability"] = 0.0
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"✅ 聚类结果已保存至: {output_file}")


def generate_markdown_report(topic_model, topics: List[int], probs: List[float], articles: List[Dict], output_file: str):
    """生成 Markdown 格式的主题报告"""
    from bertopic import BERTopic  # 仅用于类型提示，实际已导入
    
    unique_topics = set(topics)
    noise_count = list(topics).count(-1)
    topic_count = len(unique_topics) - (1 if -1 in unique_topics else 0)
    
    lines = []
    lines.append("# 新闻主题聚类报告")
    lines.append("")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**文档总数**：{len(articles)} 条")
    lines.append(f"**识别主题数**：{topic_count} 个")
    lines.append(f"**噪声文档数**：{noise_count} 条")
    lines.append("")
    
    lines.append("## 各主题详情")
    lines.append("")
    
    for topic_id in sorted(unique_topics):
        if topic_id == -1:
            continue
        
        words = topic_model.get_topic(topic_id)
        if not words:
            continue
        top_words = [w for w, _ in words[:5]]
        doc_count = sum(1 for t in topics if t == topic_id)
        
        lines.append(f"### 主题 {topic_id}：{' / '.join(top_words[:3])}")
        lines.append("")
        lines.append(f"- **文档数量**：{doc_count} 篇")
        lines.append(f"- **关键词**：{', '.join(top_words)}")
        lines.append("")
        
        # 查找代表性新闻（置信度最高的前3条）
        topic_articles = []
        for i, t in enumerate(topics):
            if t == topic_id and i < len(articles):
                topic_articles.append((articles[i], probs[i] if i < len(probs) else 0.0))
        
        topic_articles.sort(key=lambda x: x[1], reverse=True)
        
        lines.append("- **代表性新闻**：")
        for article, prob in topic_articles[:3]:
            # 尝试从多种字段获取标题
            title = (article.get("title") or article.get("tag") or 
                     article.get("新闻标题") or article.get("name") or "无标题")
            lines.append(f"  - {title}（置信度：{prob:.2f})")
        lines.append("")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 报告已保存至: {output_file}")


# ============================================
# 第七部分：主函数
# ============================================

def main():
    """主流程：加载数据 → 提取文档 → 聚类 → 保存结果"""
    print("=" * 60)
    print("📊 新闻主题聚类分析（通用健壮版）")
    print("=" * 60)
    
    # 1. 定位数据目录和文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "..", "data")
    data_dir = os.path.abspath(data_dir)
    
    print(f"📁 数据目录: {data_dir}")
    
    latest_file = find_latest_json_file(data_dir)
    if not latest_file:
        print("❌ 未找到任何新闻数据文件（支持模式：news_primary_, akshare_news_, news_）")
        print("请先运行抓取脚本生成数据文件。")
        sys.exit(1)
    
    print(f"📂 加载数据文件: {latest_file}")
    
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            articles = json.load(f)
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        sys.exit(1)
    
    if not articles:
        print("⚠️ 文件为空，无数据可处理")
        sys.exit(0)
    
    print(f"📊 原始数据条数: {len(articles)}")
    
    # 2. 构建文档列表
    docs, valid_articles = build_document_list(articles)
    print(f"📝 有效文档数: {len(docs)} / {len(articles)}")
    
    if len(docs) < CONFIG["min_docs_for_cluster"]:
        print(f"❌ 有效文档数少于 {CONFIG['min_docs_for_cluster']} 条，无法进行聚类")
        print("请检查数据质量或调整抓取逻辑。")
        sys.exit(0)
    
    # 3. 预览前几条文档
    print("\n📄 文档预览（前 5 条）：")
    for i, doc in enumerate(docs[:5], 1):
        # 截取前100字符显示
        preview = doc[:100].replace('\n', ' ')
        print(f"  {i}. {preview}...")
    
    # 4. 执行聚类
    try:
        topic_model, topics, probs = perform_clustering(docs)
    except Exception as e:
        print(f"❌ 聚类过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # 5. 统计结果
    unique_topics = set(topics)
    noise_count = list(topics).count(-1)
    topic_count = len(unique_topics) - (1 if -1 in unique_topics else 0)
    print(f"\n✅ 聚类完成！")
    print(f"   识别主题数：{topic_count} 个")
    print(f"   噪声文档数：{noise_count} 条")
    
    # 6. 保存结果
    today = datetime.now().strftime("%Y%m%d")
    clustered_file = os.path.join(data_dir, f"news_clustered_{today}.json")
    save_clustered_data(valid_articles, topics, probs, clustered_file)
    
    # 7. 生成报告
    report_file = os.path.join(data_dir, f"topic_report_{today}.md")
    generate_markdown_report(topic_model, topics, probs, valid_articles, report_file)
    
    print("\n" + "=" * 60)
    print("✅ 全部处理完成！")
    print("=" * 60)


# ============================================
# 脚本入口
# ============================================
if __name__ == "__main__":
    main()