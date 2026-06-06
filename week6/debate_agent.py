# ============================================
# 辩论 Agent
# 功能：创建多头和空头两个对立 Agent
# 每个 Agent 会调用网络搜索工具为自己的立场搜集证据
# 支持多轮辩论——发言、反驳、总结陈词
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 解析
from typing import List, Dict  # 类型注解
from datetime import datetime  # 时间戳

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# 导入第五周的网络搜索工具
from mcp_tools import registry

# ============================================
# 第 1 步：初始化服务
# ============================================

# Langfuse 监控
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# 大模型实例
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.5,                              # 辩论需要一定创造性，温度稍高
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# ============================================
# 第 2 步：定义辩论记录数据结构
# ============================================

class DebateRecord:
    """
    辩论记录类
    
    记录整场辩论的所有发言、证据和最终裁决
    
    属性：
    - topic: 辩论话题
    - rounds: 每轮的发言记录列表
    - verdict: 最终裁决（周五实现）
    """
    
    def __init__(self, topic: str):
        """
        初始化辩论记录
        
        参数：
            topic: 辩论话题，如"新能源板块当前是否高估？"
        """
        self.topic = topic                          # 辩论话题
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 创建时间
        self.rounds: List[Dict] = []                # 每轮发言记录
        self.verdict: str = ""                      # 最终裁决
    
    def add_speech(self, round_num: int, speaker: str, speech: str, evidence: str) -> None:
        """
        添加一条发言记录
        
        参数：
            round_num: 第几轮
            speaker: 发言者（多头/空头）
            speech: 发言内容
            evidence: 支撑证据（搜索结果摘要）
        """
        # 构建发言记录字典
        record = {
            "round": round_num,        # 轮次
            "speaker": speaker,        # 发言者
            "speech": speech,          # 发言内容
            "evidence": evidence,      # 证据
            "time": datetime.now().strftime("%H:%M:%S")  # 发言时间
        }
        # 添加到记录列表
        self.rounds.append(record)
    
    def get_history(self, speaker: str = None) -> str:
        """
        获取辩论历史（给 Agent 看，帮它理解上下文）
        
        参数：
            speaker: 如果指定，只返回该发言者的历史
        
        返回：
            格式化的辩论历史文本
        """
        if not self.rounds:
            return "（辩论尚未开始）"
        
        lines = []
        # 筛选发言记录
        filtered = self.rounds if speaker is None else [r for r in self.rounds if r["speaker"] == speaker]
        
        for record in filtered:
            lines.append(f"【第{record['round']}轮 · {record['speaker']}】")
            lines.append(f"{record['speech'][:300]}")
            lines.append("")
        
        return "\n".join(lines)
    
    def to_full_report(self) -> str:
        """
        生成完整的辩论记录报告
        
        返回：
            格式化的 Markdown 报告
        """
        lines = []
        lines.append(f"# 辩论记录：{self.topic}")
        lines.append(f"**时间**：{self.created_at}")
        lines.append(f"**总轮次**：{len(self.rounds)} 轮")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 逐轮输出
        for record in self.rounds:
            speaker_icon = "🔴" if record["speaker"] == "多头" else "🟢"
            lines.append(f"## 第{record['round']}轮 · {speaker_icon} {record['speaker']}")
            lines.append("")
            lines.append(f"**发言**：")
            lines.append(record["speech"])
            lines.append("")
            lines.append(f"**证据**：")
            lines.append(record["evidence"][:500])
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # 如果有裁决
        if self.verdict:
            lines.append(f"## ⚖️ 最终裁决")
            lines.append(self.verdict)
        
        return "\n".join(lines)


# ============================================
# 第 3 步：定义辩论 Agent 的提示词模板
# ============================================

# 多头 Agent 的提示词
bullish_template = """你是一位专业的**多头分析师**，你的任务是为以下投资话题寻找**看多/利多**的证据。

【辩论话题】
{topic}

【你的立场】
你坚定看多！你的任务是：
1. 搜索支持看多的最新数据、新闻、研究报告
2. 用数据和逻辑论证为什么应该看好
3. 如果对手提出利空观点，找到反证来反驳

【当前辩论阶段】
{stage_description}

【之前的辩论记录】
{history}

【对手上一轮发言】
{opponent_last_speech}

【你的任务】
请先思考需要搜索什么关键词来支持你的立场，然后调用网络搜索工具。
搜索完成后，用搜索结果组织你的发言。

发言要求：
1. 明确表达看多立场
2. 引用具体数据（从搜索结果中来）
3. 语言有力、逻辑清晰
4. 如果是反驳阶段，要先指出对手论点的漏洞

请开始你的发言（先说明要搜索什么，然后给出完整发言）："""

# 空头 Agent 的提示词
bearish_template = """你是一位专业的**空头分析师**，你的任务是为以下投资话题寻找**看空/利空**的证据。

【辩论话题】
{topic}

【你的立场】
你坚定看空！你的任务是：
1. 搜索支持看空的最新数据、新闻、研究报告
2. 用数据和逻辑论证为什么应该警惕
3. 如果对手提出利多观点，找到反证来反驳

【当前辩论阶段】
{stage_description}

【之前的辩论记录】
{history}

【对手上一轮发言】
{opponent_last_speech}

【你的任务】
请先思考需要搜索什么关键词来支持你的立场，然后调用网络搜索工具。
搜索完成后，用搜索结果组织你的发言。

发言要求：
1. 明确表达看空立场
2. 引用具体数据（从搜索结果中来）
3. 语言有力、逻辑清晰
4. 如果是反驳阶段，要先指出对手论点的漏洞

请开始你的发言（先说明要搜索什么，然后给出完整发言）："""

# 创建提示词模板
bullish_prompt = PromptTemplate(
    template=bullish_template,
    input_variables=["topic", "stage_description", "history", "opponent_last_speech"]
)

bearish_prompt = PromptTemplate(
    template=bearish_template,
    input_variables=["topic", "stage_description", "history", "opponent_last_speech"]
)


# ============================================
# 第 4 步：辩论发言函数
# ============================================

def agent_speak(
    role: str,           # 角色：多头 或 空头
    topic: str,           # 辩论话题
    stage: str,           # 当前阶段：开场陈述/反驳/总结
    history: str,         # 辩论历史
    opponent_speech: str  # 对手上一轮发言
) -> tuple:
    """
    让一个 Agent 发言
    
    流程：
    1. 构建提示词（告诉 Agent 它的立场和任务）
    2. Agent 决定搜索什么关键词
    3. 调用网络搜索获取证据
    4. Agent 根据搜索结果组织发言
    
    参数：
        role: 角色（"多头" 或 "空头"）
        topic: 辩论话题
        stage: 当前阶段
        history: 之前的辩论记录
        opponent_speech: 对手上一轮发言
    
    返回：
        (发言内容, 搜索证据)
    """
    # 选择对应的提示词模板
    if role == "多头":
        prompt = bullish_prompt
    else:
        prompt = bearish_prompt
    
    # 构建提示词输入
    prompt_input = prompt.format(
        topic=topic,
        stage_description=stage,
        history=history,
        opponent_last_speech=opponent_speech if opponent_speech else "（无，这是第一轮发言）"
    )
    
    # 第一步：Agent 思考要搜索什么
    print(f"\n🤔 [{role}] 正在思考搜索策略...")
    thinking_response = llm.invoke(prompt_input)
    thinking_text = thinking_response.content if hasattr(thinking_response, 'content') else str(thinking_response)
    
    # 从 Agent 的思考中提取搜索关键词
    # Agent 会在发言开头说明要搜索什么，我们提取出来
    search_query = extract_search_query(thinking_text, topic)
    
    # 第二步：执行搜索
    print(f"🔍 [{role}] 正在搜索：{search_query}")
    try:
        search_result = registry.execute("网络搜索", {"query": search_query})
        evidence = search_result[:1500]  # 取前 1500 字符作为证据
    except Exception as e:
        evidence = f"搜索失败：{str(e)[:100]}"
        print(f"   ⚠️ 搜索异常：{e}")
    
    # 第三步：Agent 根据搜索结果组织正式发言
    speech_prompt = f"""基于以下搜索结果，组织你的辩论发言。

【你的立场】{role}
【辩论话题】{topic}
【辩论阶段】{stage}
【搜索结果】
{evidence}

请用专业、有力的语言发表你的观点。引用搜索结果中的具体数据。
发言长度：200-400 字。"""

    print(f"📝 [{role}] 正在组织发言...")
    speech_response = llm.invoke(speech_prompt)
    speech = speech_response.content if hasattr(speech_response, 'content') else str(speech_response)
    
    return speech, evidence


def extract_search_query(thinking_text: str, topic: str) -> str:
    """
    从 Agent 的思考中提取搜索关键词
    
    参数：
        thinking_text: Agent 的思考文本
        topic: 辩论话题
    
    返回：
        搜索关键词字符串
    """
    # 简单策略：从话题中提取关键词
    # 实际可以由 LLM 精确提取，这里简化处理
    
    # 如果思考文本中明确提到了搜索词，尝试提取
    if "搜索" in thinking_text:
        # 找到"搜索"后面的内容
        lines = thinking_text.split("\n")
        for line in lines:
            if "搜索" in line or "查询" in line or "关键词" in line:
                # 提取冒号或引号后的内容
                if "：" in line:
                    return line.split("：")[-1].strip().strip("「」\"\"")
                if ":" in line:
                    return line.split(":")[-1].strip().strip("「」\"\"")
    
    # 默认从话题生成搜索词
    return f"{topic} 最新数据 分析"


# ============================================
# 第 5 步：完整辩论流程
# ============================================

def run_debate(topic: str, max_rounds: int = 3) -> DebateRecord:
    """
    执行完整的辩论流程
    
    流程：
    1. 第一轮：双方开场陈述
    2. 第二轮：双方互相反驳
    3. 第三轮：双方总结陈词
    
    参数：
        topic: 辩论话题
        max_rounds: 最大辩论轮数（默认 3 轮）
    
    返回：
        完整的辩论记录
    """
    print(f"\n{'=' * 60}")
    print(f"🏛️ 圆桌辩论会")
    print(f"{'=' * 60}")
    print(f"辩论话题：{topic}")
    print(f"辩论轮数：{max_rounds} 轮")
    print(f"辩手：🔴 多头分析师 vs 🟢 空头分析师")
    print()
    
    # 创建辩论记录
    record = DebateRecord(topic)
    
    # 对手上一轮发言（初始为空）
    bull_last = ""   # 多头上一轮
    bear_last = ""   # 空头上一轮
    
    # 逐轮辩论
    for round_num in range(1, max_rounds + 1):
        print(f"\n{'─' * 50}")
        print(f"第 {round_num} 轮")
        print(f"{'─' * 50}")
        
        # 确定当前阶段
        if round_num == 1:
            stage = "开场陈述——请用数据和逻辑论证你的立场"
        elif round_num == max_rounds:
            stage = "总结陈词——请总结你的核心论点，并最终说服裁判"
        else:
            stage = f"反驳阶段——请针对对手上一轮的论点进行反驳，同时强化自己的立场"
        
        # === 多头发言 ===
        print(f"\n🔴 多头分析师发言：")
        bull_speech, bull_evidence = agent_speak(
            role="多头",
            topic=topic,
            stage=stage,
            history=record.get_history("多头"),
            opponent_speech=bear_last
        )
        
        print(f"   发言：{bull_speech[:150]}...")
        record.add_speech(round_num, "多头", bull_speech, bull_evidence)
        bull_last = bull_speech
        
        # === 空头发言 ===
        print(f"\n🟢 空头分析师发言：")
        bear_speech, bear_evidence = agent_speak(
            role="空头",
            topic=topic,
            stage=stage,
            history=record.get_history("空头"),
            opponent_speech=bull_last
        )
        
        print(f"   发言：{bear_speech[:150]}...")
        record.add_speech(round_num, "空头", bear_speech, bear_evidence)
        bear_last = bear_speech
    
    print(f"\n{'─' * 50}")
    print(f"辩论结束，共 {max_rounds} 轮")
    print(f"{'─' * 50}")
    
    return record


# ============================================
# 第 6 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏛️ 圆桌辩论会测试")
    print("=" * 60)
    
    # 选择辩论话题
    topic = "新能源板块当前是否被高估？"
    print(f"\n辩论话题：{topic}")
    print()
    print("注意：每轮辩论都会调用网络搜索，请确保 Tavily API 额度充足")
    print()
    
    # 执行辩论
    record = run_debate(topic, max_rounds=2)  # 测试用 2 轮，实际可用 3 轮
    
    # 输出完整记录
    print("\n" + "=" * 60)
    print("📄 完整辩论记录")
    print("=" * 60)
    
    full_report = record.to_full_report()
    print(full_report[:2000])
    print("...")
    
    # 保存辩论记录
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data"
    )
    os.makedirs(data_dir, exist_ok=True)
    
    filename = f"debate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = os.path.join(data_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_report)
    
    print(f"\n✅ 辩论记录已保存到：{filepath}")