#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tavily 金融信号日报生成器
功能：
1. 根据关键词列表进行 Tavily 实时搜索
2. 对每条结果提取结构化金融信号
3. 聚合生成日报（Markdown + JSON）
4. 支持飞书推送（可选）

依赖：
    pip install tavily-python langchain-openai python-dotenv
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import requests

# LangChain 组件
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

# Tavily 客户端
from tavily import TavilyClient

# 加载环境变量
load_dotenv()

# ============================================================
# 配置
# ============================================================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not TAVILY_API_KEY or not DEEPSEEK_API_KEY:
    raise ValueError("请在 .env 中设置 TAVILY_API_KEY 和 DEEPSEEK_API_KEY")

# 搜索参数
SEARCH_DEPTH = "basic"       # "basic" 消耗1积分，"advanced" 消耗2积分
MAX_RESULTS_PER_QUERY = 5    # 每个关键词返回的结果数
TOPIC = "finance"            # 金融领域优化

# 关键词列表（可根据需要修改）
KEYWORDS = [
    "A股 热点 板块 轮动",
    "美股 纳斯达克 科技股",
    "半导体 芯片 行业动态",
    "新能源 光伏 储能",
    "美联储 利率 政策",
    "茅台 白酒 消费",
]

# 日报输出路径
OUTPUT_DIR = os.path.expanduser("~/fin_agent_projects/data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 第一步：Tavily 搜索封装
# ============================================================

def search_finance_news(keywords: List[str]) -> List[Dict]:
    """
    使用 Tavily 搜索金融新闻，返回去重后的结果列表
    """
    client = TavilyClient(api_key=TAVILY_API_KEY)
    all_results = []
    seen_urls = set()

    for query in keywords:
        logger.info(f"🔍 搜索关键词: {query}")
        try:
            response = client.search(
                query=query,
                search_depth=SEARCH_DEPTH,
                max_results=MAX_RESULTS_PER_QUERY,
                topic=TOPIC,
                include_answer=False,       # 不包含AI摘要，我们后续用大模型提取信号
                include_raw_content=False,  # 不返回原始HTML
            )
            results = response.get("results", [])
            for item in results:
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append({
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                        "url": url,
                        "source": item.get("source", ""),
                        "published": item.get("published", ""),
                        "query": query,  # 记录触发的关键词
                    })
            logger.info(f"   ✅ 获取 {len(results)} 条结果")
        except Exception as e:
            logger.error(f"   ❌ 搜索失败: {e}")

    logger.info(f"📊 共获取 {len(all_results)} 条去重新闻")
    return all_results

# ============================================================
# 第二步：信号提取（使用 DeepSeek）
# ============================================================

SIGNAL_EXTRACTION_PROMPT = ChatPromptTemplate.from_template("""
你是一位专业的金融信号分析师。请根据以下新闻内容提取投资信号。

【新闻标题】
{title}

【新闻内容】
{content}

【发布时间】
{published}

【分析要求】
1. 判断信号方向：看多 / 看空 / 中性
2. 识别涉及的资产/板块（如：白酒板块、AI概念、银行股）
3. 评估信号强度：高 / 中 / 低
4. 评估置信度：0.0 到 1.0 之间
5. 提取 2-4 个关键词
6. 写一句话摘要（不超过30字）

【输出格式】
请严格按照以下 JSON 格式输出，不要添加任何其他内容：

{{
  "direction": "看多",
  "asset": "白酒板块",
  "strength": "高",
  "confidence": 0.85,
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "summary": "一句话摘要"
}}
""")

def extract_signal(title: str, content: str, published: str) -> Dict:
    """
    使用大模型从单条新闻中提取结构化信号
    """
    llm = ChatOpenAI(
        model="deepseek-chat",
        temperature=0.2,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )
    chain = SIGNAL_EXTRACTION_PROMPT | llm | JsonOutputParser()
    
    try:
        signal = chain.invoke({
            "title": title[:200],
            "content": content[:2000],
            "published": published,
        })
        return signal
    except Exception as e:
        logger.error(f"信号提取失败: {e}")
        return {
            "direction": "中性",
            "asset": "未知",
            "strength": "低",
            "confidence": 0.0,
            "keywords": [],
            "summary": "提取失败"
        }

# ============================================================
# 第三步：日报生成
# ============================================================

def generate_daily_report(articles: List[Dict], signals: List[Dict]) -> str:
    """
    生成 Markdown 格式的日报
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(articles)
    
    # 统计信号方向
    directions = {}
    assets = {}
    strengths = {}
    for s in signals:
        d = s.get("direction", "中性")
        directions[d] = directions.get(d, 0) + 1
        a = s.get("asset", "未知")
        assets[a] = assets.get(a, 0) + 1
        st = s.get("strength", "低")
        strengths[st] = strengths.get(st, 0) + 1

    md = []
    md.append(f"# 📈 金融信号日报")
    md.append(f"**生成时间**: {now}")
    md.append(f"**新闻总数**: {total}")
    md.append("")
    md.append("## 📊 信号统计")
    md.append("| 方向 | 数量 |")
    md.append("|------|------|")
    for d, cnt in directions.items():
        md.append(f"| {d} | {cnt} |")
    md.append("")
    md.append("| 资产/板块 | 提及次数 |")
    md.append("|-----------|----------|")
    for a, cnt in sorted(assets.items(), key=lambda x: -x[1])[:5]:
        md.append(f"| {a} | {cnt} |")
    md.append("")
    md.append("| 强度 | 数量 |")
    md.append("|------|------|")
    for st, cnt in strengths.items():
        md.append(f"| {st} | {cnt} |")
    md.append("")
    md.append("## 📰 详细信号列表")
    for i, (article, signal) in enumerate(zip(articles, signals), 1):
        title = article.get("title", "无标题")
        direction = signal.get("direction", "中性")
        asset = signal.get("asset", "未知")
        strength = signal.get("strength", "低")
        confidence = signal.get("confidence", 0.0)
        summary = signal.get("summary", "")
        keywords = ", ".join(signal.get("keywords", []))
        md.append(f"### {i}. {title}")
        md.append(f"- **方向**: {direction}  |  **板块**: {asset}  |  **强度**: {strength}  |  **置信度**: {confidence:.2f}")
        md.append(f"- **摘要**: {summary}")
        if keywords:
            md.append(f"- **关键词**: {keywords}")
        md.append(f"- **来源**: [{article.get('source', '')}]({article.get('url', '#')})")
        md.append("")
    
    return "\n".join(md)

def save_report(markdown: str, signals: List[Dict], articles: List[Dict]):
    """
    保存日报文件（.md 和 .json）
    """
    date_str = datetime.now().strftime("%Y%m%d")
    md_file = os.path.join(OUTPUT_DIR, f"daily_report_{date_str}.md")
    json_file = os.path.join(OUTPUT_DIR, f"daily_report_{date_str}.json")
    
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(markdown)
    logger.info(f"✅ Markdown 报告已保存: {md_file}")
    
    # 保存 JSON（包含完整数据）
    data = {
        "date": date_str,
        "timestamp": datetime.now().isoformat(),
        "total": len(articles),
        "articles": articles,
        "signals": signals,
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ JSON 数据已保存: {json_file}")

# ============================================================
# 第四步：飞书推送（可选）
# ============================================================

def push_to_feishu(markdown: str, webhook_url: str = None):
    """
    推送日报到飞书（通过自定义机器人 Webhook）
    """
    if not webhook_url:
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("未配置飞书 Webhook，跳过推送")
        return
    
    try:
        # 飞书消息最大长度限制，分段发送
        payload = {
            "msg_type": "text",
            "content": {"text": markdown[:4000]}  # 截断
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("✅ 飞书推送成功")
        else:
            logger.warning(f"飞书推送失败: {resp.text}")
    except Exception as e:
        logger.error(f"飞书推送异常: {e}")

# ============================================================
# 主流程
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("🚀 Tavily 金融信号日报生成器")
    logger.info("=" * 60)
    
    # 1. 搜索
    logger.info("🔍 开始搜索金融新闻...")
    articles = search_finance_news(KEYWORDS)
    if not articles:
        logger.error("未获取到任何新闻，退出")
        return
    
    # 2. 提取信号
    logger.info("🧠 开始提取信号...")
    signals = []
    for idx, article in enumerate(articles, 1):
        logger.info(f"  处理 {idx}/{len(articles)}: {article.get('title', '')[:30]}...")
        signal = extract_signal(
            title=article.get("title", ""),
            content=article.get("content", ""),
            published=article.get("published", "")
        )
        signals.append(signal)
    
    # 3. 生成日报
    logger.info("📝 生成日报...")
    markdown = generate_daily_report(articles, signals)
    
    # 4. 保存
    save_report(markdown, signals, articles)
    
    # 5. 推送（可选）
    webhook = os.getenv("FEISHU_WEBHOOK_URL")
    if webhook:
        push_to_feishu(markdown, webhook)
    
    logger.info("✅ 日报生成完成！")
    logger.info(f"📂 查看报告: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()