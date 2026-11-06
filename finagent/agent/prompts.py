"""Prompts and the machine-checkable contract for the LLM report."""

from __future__ import annotations

from finagent.agent.evidence import EvidenceBundle, ReportFacts, format_evidence

REQUIRED_SECTIONS = ["## 结论", "## 信号", "## 组合", "## 数据与限制", "## 证伪条件"]
MUST_INCLUDE = ["validated=false", "存续偏差", "不构成投资建议"]
FORBIDDEN = ["稳赚", "必涨", "保证收益", "推荐买入", "建议买入", "满仓", "抄底"]
MIN_CITATIONS = 10

SYSTEM_PROMPT = """你是 finagent 的研究报告撰写器。你的唯一职责是把给定的证据表组织成中文研究报告。

硬性规则：
1. 只允许使用证据表中的数字。任何数字必须原样来自证据表（百分比已在证据表中换算好），不得推算、加总、平均或估计。
2. 至少给出 10 处引用；每个带数字或结论的句子后面必须写引用，格式为 [snap:<证据ID>]，ID 必须逐字来自证据表。
3. 必须使用且只使用这五个二级标题（顺序固定）：
   ## 结论
   ## 信号
   ## 组合
   ## 数据与限制
   ## 证伪条件
4. 必须原样出现这三个词组：validated=false、存续偏差、不构成投资建议。
5. 绝对禁止出现：稳赚、必涨、保证收益、推荐买入、建议买入、满仓、抄底。
6. 回测与因子检验只能描述为研究结果，不得说成已验证、可靠或可实盘；不要给出买卖建议。
7. 不要写证据表之外的数字；日期可以正常写，ETF 六位代码可以写。不要写 signal_id。
8. 输出 Markdown 正文，不要用代码块包裹，不要加一级标题以外的解释。"""


def user_prompt(bundle: EvidenceBundle, facts: ReportFacts) -> str:
    missing = "、".join(bundle.missing) if bundle.missing else "无"
    news = (facts.signals.get("overlays") or {}).get("news") or {}
    if news.get("available"):
        news_line = "新闻叠加可用"
    else:
        news_line = f"新闻叠加不可用（{news.get('reason', '未提供原因')}）"
    return f"""请为 {bundle.as_of} 撰写一份 600~900 字的研究报告（正文不超过 900 个汉字，
不要逐条罗列全部证据；五个标题和必须词组必须完整保留）。

证据表（唯一可用的数字来源）：
{format_evidence(bundle)}

补充事实（不含数字）：
- 信号文件：{facts.sources.get('signals', '')}
- 缺失的工件：{missing}
- {news_line}
- 本报告是研究记录，不是投资建议。

请按五个标题组织内容；每个数字后附 [snap:<ID>]。"""


def repair_prompt(bundle: EvidenceBundle, previous: str, failures: list[str]) -> str:
    return f"""上一版报告没有通过机器校验，问题如下：
{chr(10).join(f'- {failure}' for failure in failures)}

请重写全文（不是局部修补），只使用下面证据表中的数字和 ID，保留五个二级标题，
并确保出现 validated=false、存续偏差、不构成投资建议。

证据表：
{format_evidence(bundle)}

上一版（仅用于定位问题，不要照抄其中的数字）：
--- 开始 ---
{previous[:4000]}
--- 结束 ---"""
