# ============================================
# 最终整合版 Deep Agent
# 整合本周全部能力：
#   - MCP 统一工具调用（周二）
#   - 调研计划模板（周三）
#   - 反思自动纠错（周四）
#   - 报告生成与保存（周五）
#
# 实战任务：贵州茅台 vs 五粮液 对比分析
# ============================================

import os
# 必须在最前面设置环境变量
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# 把当前目录加入 Python 模块搜索路径
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 解析
from datetime import datetime  # 时间戳

# 导入 MCP 工具注册中心（周二）
from mcp_tools import registry

# 导入反思检查器（周四）
from reflector import (
    search_with_reflection,      # 带反思的搜索
    calculate_with_reflection,   # 带反思的计算
    reflect_data_completeness    # 数据完整性检查
)

# 导入大模型
from langchain_deepseek import ChatDeepSeek
from langchain.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

# ============================================
# 第 1 步：初始化服务
# ============================================

print("=" * 60)
print("🤖 最终整合版 Deep Agent 初始化")
print("=" * 60)

# Langfuse 监控
print("\n[1/3] 连接 Langfuse 监控...")
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),       # 公钥
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),       # 私钥
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")  # 服务地址
)
print("✅ Langfuse 已连接")

# 大模型
print("[2/3] 连接 DeepSeek 模型...")
llm = ChatDeepSeek(
    model="deepseek-v4-flash",                      # 模型名称
    temperature=0.3,                             # 温度参数
    api_key=os.getenv("DEEPSEEK_API_KEY"),      # API 密钥
    callbacks=[langfuse_handler]                # 绑定监控
)
print("✅ DeepSeek 已连接")

# 工具注册中心
print("[3/3] 加载 MCP 工具...")
available_tools = registry.list_names()
for name in available_tools:
    tool = registry.get(name)
    desc = tool.description[:60] if tool else ""  # 截取描述前 60 字
    print(f"   🔧 {name}: {desc}...")
print("✅ 工具加载完成")
print()

# ============================================
# 第 2 步：定义报告生成提示词
# ============================================

# 报告提示词模板
report_template = """你是一位资深投研分析师，请根据以下调研数据撰写一份专业的对比分析报告。

【用户问题】
{question}

【已收集数据】
{collected_data}

【报告要求】
1. 结构完整，包含以下章节：
   ## 一、核心摘要
   - 用 2-3 句话总结核心发现
   
   ## 二、数据对比
   - 用表格展示两家公司的关键指标
   - 至少包含：营收、净利润、增长率
   
   ## 三、深度分析
   - 对数据进行解读
   - 分析差异背后的原因
   - 结合行业背景做判断
   
   ## 四、风险提示
   - 列出 3-5 个需要注意的风险因素
   
   ## 五、结论
   - 给出明确的对比结论
   - 说明哪家公司当前更具投资价值

2. 格式规范：
   - 使用 Markdown 格式
   - 数据要标注来源
   - 表格对齐清晰
   - 语言专业但通俗易懂

3. 数据原则：
   - 所有数据必须来自提供的调研数据
   - 如果某数据缺失，诚实说明"数据暂未获取到"
   - 不要编造任何数字

请输出完整分析报告："""

# 创建提示词模板对象
report_prompt = PromptTemplate(
    template=report_template,
    input_variables=["question", "collected_data"]  # 两个输入参数
)

# ============================================
# 第 3 步：核心执行函数
# ============================================

def run_full_analysis(question: str, company_a: str, company_b: str) -> str:
    """
    执行完整的对比分析流程
    
    流程包含 6 个阶段：
    1. 搜索公司 A 数据
    2. 搜索公司 B 数据
    3. 搜索行业背景
    4. 查询本地信号
    5. 计算对比指标
    6. 生成最终报告
    
    参数：
        question: 用户问题
        company_a: 公司 A 名称，如"贵州茅台"
        company_b: 公司 B 名称，如"五粮液"
    
    返回：
        完整的 Markdown 格式分析报告
    """
    
    # 用于累积所有收集到的数据
    collected_data = ""
    # 步骤计数器
    step = 0
    # 已执行步骤记录
    steps_log = []
    
    print(f"\n{'=' * 60}")
    print(f"📋 分析任务：{question}")
    print(f"   对比对象：{company_a} vs {company_b}")
    print(f"{'=' * 60}")
    
    # ============================================
    # 阶段 1：搜索公司 A 的财务数据
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 1/6】搜索 {company_a} 财务数据")
    print(f"{'─' * 50}")
    
    step += 1
    print(f"\n步骤 {step}：搜索 {company_a} 营收和净利润...")
    
    # 使用带反思的搜索（自动检查结果质量，不好会换词重试）
    result_a = search_with_reflection(
        goal=f"获取{company_a}最新营收和净利润数据",
        initial_query=f"{company_a} 2025年 营业收入 净利润 同比增长"
    )
    
    # 将结果追加到数据池
    collected_data += f"\n## {company_a} 财务数据\n\n{result_a}\n"
    steps_log.append(f"✅ 步骤{step}: 获取{company_a}数据完成")
    
    # ============================================
    # 阶段 2：搜索公司 B 的财务数据
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 2/6】搜索 {company_b} 财务数据")
    print(f"{'─' * 50}")
    
    step += 1
    print(f"\n步骤 {step}：搜索 {company_b} 营收和净利润...")
    
    # 使用带反思的搜索
    result_b = search_with_reflection(
        goal=f"获取{company_b}最新营收和净利润数据",
        initial_query=f"{company_b} 2025年 营业收入 净利润 同比增长"
    )
    
    # 将结果追加到数据池
    collected_data += f"\n## {company_b} 财务数据\n\n{result_b}\n"
    steps_log.append(f"✅ 步骤{step}: 获取{company_b}数据完成")
    
    # ============================================
    # 阶段 3：搜索行业背景
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 3/6】搜索白酒行业背景")
    print(f"{'─' * 50}")
    
    step += 1
    print(f"\n步骤 {step}：搜索白酒行业最新动态...")
    
    # 搜索行业信息
    result_industry = search_with_reflection(
        goal="获取光模块行业最新政策、市场趋势、竞争格局",
        initial_query="光模块行业 2025年 2026年季报 政策 市场趋势 竞争格局，行业技术天花板，龙头企业，发展趋势，护城河，未来空间"
    )
    
    # 将结果追加到数据池
    collected_data += f"\n## 电子化学行业背景\n\n{result_industry}\n"
    steps_log.append(f"✅ 步骤{step}: 获取行业数据完成")
    
    # ============================================
    # 阶段 4：查询本地金融信号
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 4/6】查询本地金融信号")
    print(f"{'─' * 50}")
    
    step += 1
    print(f"\n步骤 {step}：查询白酒板块信号...")
    
    # 从本地信号数据库查询
    signal_result = registry.execute("金融信号查询", {"asset": "光模块"})
    
    # 将结果追加到数据池
    collected_data += f"\n## 本地金融信号\n\n{signal_result}\n"
    steps_log.append(f"✅ 步骤{step}: 获取信号数据完成")
    
    # ============================================
    # 阶段 5：计算对比指标
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 5/6】计算对比指标")
    print(f"{'─' * 50}")
    
    step += 1
    print(f"\n步骤 {step}：尝试从数据中提取并计算增长率...")
    
    # 尝试计算（如果数据中有具体数字）
    # 这里使用示例表达式，实际可以由 LLM 动态生成
    calc_expression = "0"  # 占位，实际值需要从搜索结果中提取
    calc_result = "注意：具体增长率需从搜索结果中提取实际数值后计算。以下为示例格式：\n"
    calc_result += "- 营收增长率 = (本期营收 - 上期营收) / 上期营收 × 100%\n"
    calc_result += "- 净利润增长率 = (本期净利润 - 上期净利润) / 上期净利润 × 100%\n"
    
    # 将结果追加到数据池
    collected_data += f"\n## 指标计算说明\n\n{calc_result}\n"
    steps_log.append(f"✅ 步骤{step}: 指标计算框架完成")
    
    # ============================================
    # 阶段 6：数据完整性检查
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"【阶段 6/6】数据完整性检查")
    print(f"{'─' * 50}")
    
    # 检查数据是否足够得出结论
    completeness = reflect_data_completeness(
        question=question,
        collected_data=collected_data,
        steps_summary="\n".join(steps_log)
    )
    
    # 判断数据是否完整
    is_complete = completeness.get("complete", True)
    missing_info = completeness.get("missing", "")
    suggestion = completeness.get("suggestion", "")
    
    if not is_complete:
        # 数据不完整，记录缺失信息
        print(f"   ⚠️ 数据可能不完整：{missing_info}")
        print(f"   💡 建议：{suggestion}")
        collected_data += f"\n## 数据完整性说明\n\n⚠️ 可能缺少：{missing_info}\n\n💡 建议：{suggestion}\n"
    else:
        # 数据完整
        print(f"   ✅ 数据完整性检查通过")
        collected_data += f"\n## 数据完整性说明\n\n✅ 数据收集完整，可以生成报告\n"
    
    # ============================================
    # 生成最终报告
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"📝 正在生成分析报告...")
    print(f"{'─' * 50}")
    
    # 构建提示词
    report_input = report_prompt.format(
        question=question,
        collected_data=collected_data
    )
    
    # 调用大模型生成报告
    report_response = llm.invoke(report_input)
    
    # 提取报告文本
    final_report = report_response.content if hasattr(report_response, 'content') else str(report_response)
    
    print(f"✅ 报告生成完成，共 {len(final_report)} 字")
    
    # ============================================
    # 打印执行摘要
    # ============================================
    print(f"\n{'─' * 50}")
    print(f"📊 执行摘要")
    print(f"{'─' * 50}")
    for log in steps_log:
        print(f"   {log}")
    print(f"   ✅ 报告生成完成")
    
    return final_report


# ============================================
# 第 4 步：报告保存函数
# ============================================

def save_report(report: str, filename: str) -> str:
    """
    将分析报告保存为 Markdown 文件
    
    参数：
        report: 报告文本内容
        filename: 文件名（不含路径）
    
    返回：
        保存的完整文件路径
    """
    # 构建保存路径（保存到 data 目录）
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),  # week5/ 目录
        "..",                                         # 上一级
        "data"                                        # data/ 目录
    )
    
    # 如果 data 目录不存在则创建
    os.makedirs(data_dir, exist_ok=True)
    
    # 完整文件路径
    filepath = os.path.join(data_dir, filename)
    
    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        # 添加生成时间戳
        f.write(f"# 投研分析报告\n\n")
        f.write(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**生成方式**：AI Deep Agent 自动调研\n\n")
        f.write("---\n\n")
        f.write(report)
    
    print(f"✅ 报告已保存到：{filepath}")
    print(f"   文件大小：{os.path.getsize(filepath) / 1024:.1f} KB")
    
    return filepath


# ============================================
# 第 5 步：主程序入口
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📊 实战任务：茅台 vs 五粮液 对比分析")
    print("=" * 60)
    print()
    print("本程序将自动执行以下步骤：")
    print("  1. 搜索贵州茅台最新财务数据")
    print("  2. 搜索五粮液最新财务数据")
    print("  3. 搜索白酒行业背景信息")
    print("  4. 查询本地金融信号数据库")
    print("  5. 计算关键对比指标")
    print("  6. 生成完整分析报告")
    print()
    print("预计耗时：30-60 秒（取决于 API 响应速度）")
    print()
    
    # 等待用户确认
    input("按 Enter 键开始执行...")
    
    # 执行分析
    report = run_full_analysis(
        question="对比分析光库科技和华工科技，哪家公司更具投资价值？",
        company_a="光库科技",
        company_b="华工科技"
    )
    
    # 打印报告
    print(f"\n{'=' * 60}")
    print("📄 完整分析报告")
    print(f"{'=' * 60}\n")
    print(report)
    
    # 保存报告
    filename = f"maotai_vs_wuliangye_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = save_report(report, filename)
    
    print(f"\n{'=' * 60}")
    print("✅ 实战任务完成！")
    print(f"{'=' * 60}")
    print(f"\n报告文件：{filepath}")
    print(f"\n你可以：")
    print(f"  1. 在 VS Code 中打开查看")
    print(f"  2. 通过飞书机器人推送到群聊")
    print(f"  3. 分享给同事讨论")