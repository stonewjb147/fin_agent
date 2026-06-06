# ============================================
# 信号汇总模块
# 功能：统一调用前六周的各个模块，收集四路信号
# 四路信号：
#   1. RAG 研报分析（第3练）
#   2. 新闻信号（第4练）
#   3. 因子信号（第6练）
#   4. 辩论结论（第6练）
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime
from typing import Dict


# ============================================
# 信号1：RAG 研报分析
# ============================================

def get_rag_signal(query: str = "当前最值得投资的板块") -> str:
    """
    调用第3练的 RAG 模块，从年报中检索相关信息
    
    参数：
        query: 要查询的问题
    
    返回：
        RAG 分析结果文本
    """
    try:
        # 导入 RAG 相关模块（从 week2）
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week2"))
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
        
        # 加载向量索引
        index_dir = os.path.join(os.path.dirname(__file__), "..", "faiss_index")
        
        if not os.path.exists(index_dir):
            return "⚠️ RAG 索引未找到，请先运行 week2/embed_store.py 构建向量索引"
        
        # 加载嵌入模型
        embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # 加载 FAISS 索引
        vectorstore = FAISS.load_local(
            folder_path=index_dir,
            embeddings=embeddings,
            allow_dangerous_deserialization=True
        )
        
        # 检索相关内容
        docs = vectorstore.similarity_search(query, k=3)
        
        if not docs:
            return "⚠️ RAG 未检索到相关内容"
        
        # 格式化结果
        lines = ["📚 RAG 研报分析："]
        for i, doc in enumerate(docs, 1):
            content = doc.page_content[:200].replace("\n", " ")
            lines.append(f"  {i}. {content}...")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ RAG 模块调用失败：{str(e)[:100]}"


# ============================================
# 信号2：新闻信号
# ============================================

def get_news_signal() -> str:
    """
    读取第4练生成的最新信号数据
    
    返回：
        新闻信号摘要文本
    """
    try:
        # 查找最新信号文件
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        
        signal_files = [
            f for f in os.listdir(data_dir)
            if f.startswith("signals_") and f.endswith(".jsonl")
        ]
        
        if not signal_files:
            return "⚠️ 新闻信号文件未找到，请先运行 week3/batch_extract.py"
        
        # 取最新文件
        signal_files.sort(reverse=True)
        latest_file = os.path.join(data_dir, signal_files[0])
        
        # 读取信号
        signals = []
        with open(latest_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        s = json.loads(line)
                        if s.get("is_valid", False):
                            signals.append(s)
                    except json.JSONDecodeError:
                        continue
        
        if not signals:
            return "⚠️ 新闻信号文件为空"
        
        # 按置信度排序
        signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        # 格式化输出
        lines = [f"📰 新闻信号（共 {len(signals)} 条有效信号）："]
        
        # 按方向统计
        from collections import Counter
        dir_count = Counter(s.get("direction") for s in signals)
        lines.append(f"  看多：{dir_count.get('看多', 0)} | 看空：{dir_count.get('看空', 0)} | 中性：{dir_count.get('中性', 0)}")
        
        # Top 5 信号
        for i, s in enumerate(signals[:5], 1):
            icon = {"看多": "🔴", "看空": "🟢", "中性": "⚪"}
            lines.append(f"  {icon.get(s.get('direction', ''), '')} {i}. [{s.get('direction', '')}] {s.get('asset', '')} | 置信度 {s.get('confidence', 0):.0%}")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 新闻信号加载失败：{str(e)[:100]}"


# ============================================
# 信号3：因子信号
# ============================================

def get_factor_signal() -> str:
    """
    调用第6练的因子生成模块，生成一个简单因子
    
    返回：
        因子信号文本
    """
    try:
        # 导入因子生成模块
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week6"))
        from gen_factor_node import generate_factor
        
        # 生成一个 ETF 相关的因子
        factor = generate_factor("低估值 ETF 且近期成交量放大的投资机会")
        
        if factor.is_valid():
            lines = [
                "📊 因子信号：",
                f"  因子名称：{factor.display_name}",
                f"  因子类型：{factor.factor_type}",
                f"  因子代码：{factor.code}",
                f"  因子描述：{factor.description}",
                f"  所需数据：{', '.join(factor.data_requirements)}",
                f"  置信度：有效因子"
            ]
            return "\n".join(lines)
        else:
            return "⚠️ 因子生成失败：因子定义不完整"
    
    except Exception as e:
        return f"⚠️ 因子模块调用失败：{str(e)[:100]}"


# ============================================
# 信号4：辩论结论
# ============================================

def get_debate_signal(topic: str = "当前应该投资宽基ETF还是行业ETF？") -> str:
    """
    调用第6练的辩论模块，执行快节奏辩论并返回结论
    
    参数：
        topic: 辩论话题
    
    返回：
        辩论结论文本
    """
    try:
        # 导入辩论模块
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "week6"))
        from debate_agent import run_debate
        from judge_agent import judge_debate
        
        # 执行快速辩论（1轮，节省时间）
        record = run_debate(topic, max_rounds=1)
        
        # 裁判裁决
        verdict = judge_debate(record)
        
        # 格式化结果
        winner = verdict.get("winner", "平局")
        bullish_score = verdict.get("bullish_score", {}).get("total", 0)
        bearish_score = verdict.get("bearish_score", {}).get("total", 0)
        reasoning = verdict.get("reasoning", "")
        
        lines = [
            "🏛️ 辩论结论：",
            f"  辩题：{topic}",
            f"  胜方：{winner}",
            f"  多头得分：{bullish_score}/100",
            f"  空头得分：{bearish_score}/100",
            f"  裁决理由：{reasoning[:150]}..."
        ]
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 辩论模块调用失败：{str(e)[:100]}"


# ============================================
# 汇总函数：收集所有信号
# ============================================

def aggregate_all_signals(query: str = "") -> Dict[str, str]:
    """
    汇总所有四路信号
    
    参数：
        query: 用户查询（用于 RAG 搜索）
    
    返回：
        包含四路信号的字典
    """
    print("\n" + "=" * 50)
    print("📡 信号汇总中...")
    print("=" * 50)
    
    # 1. RAG 信号
    print("\n[1/4] 获取 RAG 研报信号...")
    rag = get_rag_signal(query or "当前最值得投资的板块")
    print(f"   {rag[:100]}...")
    
    # 2. 新闻信号
    print("\n[2/4] 获取新闻信号...")
    news = get_news_signal()
    print(f"   {news[:100]}...")
    
    # 3. 因子信号
    print("\n[3/4] 获取因子信号...")
    factor = get_factor_signal()
    print(f"   {factor[:100]}...")
    
    # 4. 辩论结论（可选，耗时较长）
    print("\n[4/4] 获取辩论结论...")
    debate = get_debate_signal()
    print(f"   {debate[:100]}...")
    
    return {
        "rag": rag,
        "news": news,
        "factor": factor,
        "debate": debate,
        "summary": f"{rag}\n\n{news}\n\n{factor}\n\n{debate}"
    }


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 信号汇总模块测试")
    print("=" * 60)
    print()
    print("注意：辩论模块会调用 LLM，耗时较长")
    print("测试时可以选择跳过辩论（在代码中注释掉）")
    print()
    
    # 测试 RAG
    print("\n── 测试 RAG 信号 ──")
    rag = get_rag_signal("白酒板块投资价值")
    print(rag)
    
    # 测试新闻
    print("\n── 测试新闻信号 ──")
    news = get_news_signal()
    print(news)
    
    # 测试因子
    print("\n── 测试因子信号 ──")
    factor = get_factor_signal()
    print(factor)
    
    # 测试辩论（如果时间允许）
    print("\n── 测试辩论 ──")
    debate = get_debate_signal("ETF 投资应侧重宽基还是行业？")
    print(debate)
    
    print("\n" + "=" * 60)
    print("✅ 信号汇总模块测试完成")
    print("=" * 60)