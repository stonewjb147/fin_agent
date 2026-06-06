# ============================================
# 裁判 Agent
# 功能：在多头和空头辩论结束后，做出公正裁决
# 评分标准：
#   1. 证据质量（30分）——是否引用了具体数据和来源
#   2. 逻辑严密性（30分）——推理是否严谨、有无漏洞
#   3. 说服力（20分）——语言是否有力、论据是否充分
#   4. 反驳能力（20分）——是否能有效应对对方论点
# 总分 100 分，得分高者获胜
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 解析
from typing import Dict  # 类型注解

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# 导入辩论记录类
from debate_agent import DebateRecord

# ============================================
# 第 1 步：初始化服务
# ============================================

# Langfuse 监控
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# 大模型（裁判需要更谨慎，温度最低）
llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.0,                              # 裁判必须公正，温度设为 0
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    callbacks=[langfuse_handler]
)

# ============================================
# 第 2 步：定义裁判的评分提示词
# ============================================

judge_template = """你是一位公正、专业的投资辩论裁判。请根据以下辩论记录，做出客观裁决。

【辩论话题】
{topic}

【完整辩论记录】
{debate_record}

【评分标准】
请从以下四个维度对多头和空头分别评分（每项 0-25 分，总分 100 分）：

1. 证据质量（25分）：
   - 是否引用了具体的数据和事实？
   - 数据来源是否可靠？
   - 证据是否与论点直接相关？

2. 逻辑严密性（25分）：
   - 推理链条是否完整？
   - 是否存在逻辑漏洞或偷换概念？
   - 因果关系是否成立？

3. 说服力（25分）：
   - 语言表达是否清晰有力？
   - 论据是否充分？
   - 是否抓住了问题的关键？

4. 反驳能力（25分）：
   - 是否有效回应了对方的论点？
   - 是否发现了对方论证的漏洞？
   - 反驳是否有理有据？

【输出格式】
请严格按照以下 JSON 格式输出裁决结果：

{{
  "winner": "多头" 或 "空头" 或 "平局",
  "bullish_score": {{
    "evidence_quality": 分数,
    "logic_rigor": 分数,
    "persuasiveness": 分数,
    "rebuttal_ability": 分数,
    "total": 总分
  }},
  "bearish_score": {{
    "evidence_quality": 分数,
    "logic_rigor": 分数,
    "persuasiveness": 分数,
    "rebuttal_ability": 分数,
    "total": 总分
  }},
  "reasoning": "裁决理由（200字以内）",
  "key_factors": ["关键因素1", "关键因素2", "关键因素3"],
  "suggestion": "对投资者的建议（100字以内）"
}}

【JSON 输出】"""

# 创建提示词模板
judge_prompt = PromptTemplate(
    template=judge_template,
    input_variables=["topic", "debate_record"]
)


# ============================================
# 第 3 步：裁判裁决函数
# ============================================

def judge_debate(record: DebateRecord) -> Dict:
    """
    对一场辩论进行裁决
    
    流程：
    1. 读取完整辩论记录
    2. 调用 LLM 按四个维度评分
    3. 返回结构化的裁决结果
    
    参数：
        record: 辩论记录对象
    
    返回：
        裁决结果字典，包含双方的各维度得分、总分、胜者、理由
    """
    print(f"\n⚖️ [裁判 Agent] 正在分析辩论记录...")
    print(f"   辩论话题：{record.topic}")
    print(f"   总轮次：{len(record.rounds)} 轮")
    
    # 获取完整辩论记录文本
    debate_text = record.to_full_report()
    
    # 构建提示词
    judge_input = judge_prompt.format(
        topic=record.topic,
        debate_record=debate_text[:6000]  # 取前 6000 字符，避免 Token 超限
    )
    
    # 调用 LLM 进行裁决
    try:
        print(f"   正在分析双方表现...")
        response = llm.invoke(judge_input)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # 清理可能的 Markdown 标记
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]   # 去掉开头的 ```json
        if response_text.startswith("```"):
            response_text = response_text[3:]    # 去掉开头的 ```
        if response_text.endswith("```"):
            response_text = response_text[:-3]   # 去掉结尾的 ```
        response_text = response_text.strip()
        
        # 解析 JSON
        verdict = json.loads(response_text)
        
        # 打印裁决结果
        print(f"\n   ╔══════════════════════════════╗")
        print(f"   ║       裁  决  结  果         ║")
        print(f"   ╠══════════════════════════════╣")
        print(f"   ║ 胜者：{verdict.get('winner', '未知'):<20} ║")
        
        bullish_total = verdict.get("bullish_score", {}).get("total", 0)
        bearish_total = verdict.get("bearish_score", {}).get("total", 0)
        print(f"   ║ 多头总分：{bullish_total:<18} ║")
        print(f"   ║ 空头总分：{bearish_total:<18} ║")
        print(f"   ╚══════════════════════════════╝")
        print(f"\n   裁决理由：{verdict.get('reasoning', '')[:150]}...")
        
        # 更新辩论记录
        record.verdict = f"""
## 裁决结果

**胜者**：{verdict.get('winner', '未知')}

### 多头得分（总分 {bullish_total}/100）
- 证据质量：{verdict.get('bullish_score', {}).get('evidence_quality', 0)}/25
- 逻辑严密性：{verdict.get('bullish_score', {}).get('logic_rigor', 0)}/25
- 说服力：{verdict.get('bullish_score', {}).get('persuasiveness', 0)}/25
- 反驳能力：{verdict.get('bullish_score', {}).get('rebuttal_ability', 0)}/25

### 空头得分（总分 {bearish_total}/100）
- 证据质量：{verdict.get('bearish_score', {}).get('evidence_quality', 0)}/25
- 逻辑严密性：{verdict.get('bearish_score', {}).get('logic_rigor', 0)}/25
- 说服力：{verdict.get('bearish_score', {}).get('persuasiveness', 0)}/25
- 反驳能力：{verdict.get('bearish_score', {}).get('rebuttal_ability', 0)}/25

### 裁决理由
{verdict.get('reasoning', '')}

### 关键因素
{chr(10).join(f'- {f}' for f in verdict.get('key_factors', []))}

### 投资建议
{verdict.get('suggestion', '')}
"""
        
        return verdict
    
    except json.JSONDecodeError as e:
        print(f"   ❌ 裁决 JSON 解析失败：{e}")
        return {
            "winner": "平局",
            "bullish_score": {"total": 0},
            "bearish_score": {"total": 0},
            "reasoning": f"裁决解析异常：{str(e)[:50]}",
            "key_factors": [],
            "suggestion": "请重新进行辩论"
        }
    
    except Exception as e:
        print(f"   ❌ 裁决异常：{e}")
        return {
            "winner": "平局",
            "bullish_score": {"total": 0},
            "bearish_score": {"total": 0},
            "reasoning": f"裁决异常：{str(e)[:50]}",
            "key_factors": [],
            "suggestion": "请重新进行辩论"
        }


# ============================================
# 第 4 步：创建完整辩论+裁决流程
# ============================================

def run_full_debate_with_verdict(topic: str, max_rounds: int = 3) -> DebateRecord:
    """
    执行完整辩论流程（辩论 + 裁决）
    
    参数：
        topic: 辩论话题
        max_rounds: 最大辩论轮数
    
    返回：
        包含裁决结果的完整辩论记录
    """
    # 导入辩论函数
    from debate_agent import run_debate
    
    # 第一步：执行辩论
    print(f"\n{'=' * 60}")
    print(f"第一阶段：双方辩论")
    print(f"{'=' * 60}")
    
    record = run_debate(topic, max_rounds)
    
    # 第二步：裁判裁决
    print(f"\n{'=' * 60}")
    print(f"第二阶段：裁判裁决")
    print(f"{'=' * 60}")
    
    verdict = judge_debate(record)
    
    return record


# ============================================
# 第 5 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("⚖️ 裁判 Agent 测试")
    print("=" * 60)
    
    # 测试话题
    topic = "新能源板块当前是否被高估？"
    
    print(f"\n辩论话题：{topic}")
    print()
    print("注意：辩论会调用网络搜索，裁决会分析全部发言")
    print("预计耗时：60-90 秒")
    print()
    
    # 执行完整辩论+裁决
    record = run_full_debate_with_verdict(topic, max_rounds=2)
    
    # 输出完整报告
    full_report = record.to_full_report()
    
    print("\n" + "=" * 60)
    print("📄 完整辩论+裁决报告")
    print("=" * 60)
    print(full_report[:3000])
    print("...")
    
    # 保存报告
    import os as _os
    from datetime import datetime
    
    data_dir = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "..", "data"
    )
    _os.makedirs(data_dir, exist_ok=True)
    
    filename = f"debate_verdict_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = _os.path.join(data_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_report)
    
    print(f"\n✅ 完整报告已保存到：{filepath}")