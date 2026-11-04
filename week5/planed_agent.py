# ============================================
# 基于调研计划的 Deep Agent
# 功能：
#   1. 接收用户问题后，先制定调研计划
#   2. 按计划逐步执行（搜索 → 数据 → 分析 → 报告）
#   3. 每步执行完检查结果，决定是否调整后续步骤
#   4. 最终输出结构化分析报告
# ============================================

import os
# 必须在导入其他模块之前加载环境变量
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# 把当前目录加入 Python 路径
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # 用于解析 JSON 格式数据

# 导入调研计划模板
from research_plan import ResearchPlan, create_comparison_plan

# 导入 MCP 工具注册中心（周二创建的）
from mcp_tools import registry

# 导入 DeepSeek 大模型
from langchain_deepseek import ChatDeepSeek

# 导入 LangChain Prompt 模板
from langchain.prompts import PromptTemplate

# 导入 Langfuse 回调（用于监控）
from langfuse.callback import CallbackHandler

print("=" * 60)
print("📊 基于计划的深度投研 Agent")
print("=" * 60)

# ============================================
# 第 1 步：创建 Langfuse 回调（监控用）
# ============================================

# 创建回调处理器，用于追踪每次 LLM 调用
langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),      # 从 .env 读取公钥
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),      # 从 .env 读取私钥
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")  # Langfuse 服务地址
)
print("✅ Langfuse 监控已连接")

# ============================================
# 第 2 步：创建 DeepSeek 模型（绑定 Langfuse）
# ============================================

# 创建大模型实例
llm = ChatDeepSeek(
    model="deepseek-chat",                     # 使用 DeepSeek 聊天模型
    temperature=0.3,                            # 温度设为 0.3，保留一点灵活性但不过于随机
    api_key=os.getenv("DEEPSEEK_API_KEY"),     # 从 .env 读取 API 密钥
    callbacks=[langfuse_handler]               # 绑定 Langfuse 回调，自动追踪每次调用
)
print("✅ DeepSeek 模型已连接")

# ============================================
# 第 3 步：定义计划生成的提示词
# ============================================

# 这个提示词告诉 LLM 如何制定调研计划
planning_template = """你是一个专业的投研分析师。请根据用户的问题，制定一个详细的调研计划。

【用户问题】
{question}

【可用工具】
{tools_description}

【要求】
1. 将计划分为四个阶段：调研 → 数据 → 分析 → 报告
2. 每个阶段列出具体的步骤
3. 每个步骤指定使用哪个工具和什么参数
4. 调研阶段至少包含 2-3 个搜索任务

【输出格式】
请严格按照以下 JSON 格式输出计划：

{{
  "phases": [
    {{
      "name": "调研",
      "steps": [
        {{"description": "任务描述", "tool": "工具名称", "params": {{"参数": "值"}}}}
      ]
    }},
    {{
      "name": "数据",
      "steps": [...]
    }},
    {{
      "name": "分析",
      "steps": [...]
    }},
    {{
      "name": "报告",
      "steps": [{{"description": "汇总输出报告", "tool": "无", "params": {{}}}}]
    }}
  ]
}}

请输出计划 JSON："""

# 创建 Prompt 模板对象
planning_prompt = PromptTemplate(
    template=planning_template,
    input_variables=["question", "tools_description"]  # 需要传入的参数
)

# ============================================
# 第 4 步：定义报告生成的提示词
# ============================================

# 这个提示词告诉 LLM 如何汇总所有数据生成报告
report_template = """你是一个专业的投研分析师。请根据以下调研数据，输出一份结构化的分析报告。

【用户问题】
{question}

【调研数据】
{collected_data}

【要求】
1. 报告包含以下部分：
   - 摘要：一句话总结核心结论
   - 数据对比：关键指标的对比表格
   - 分析：对数据的深度解读
   - 风险提示：需要注意的风险因素
   - 结论：投资建议或判断
2. 用 Markdown 格式输出
3. 数据要引用来源
4. 语言专业但易读

请输出分析报告："""

# 创建 Prompt 模板对象
report_prompt = PromptTemplate(
    template=report_template,
    input_variables=["question", "collected_data"]  # 需要传入的参数
)


# ============================================
# 第 5 步：核心函数——执行调研计划
# ============================================

def execute_research_plan(question: str) -> str:
    """
    执行一个完整的调研计划
    
    流程：
    1. 调用 LLM 生成调研计划
    2. 按计划逐步执行每个任务
    3. 每步执行后记录结果
    4. 汇总所有数据，生成最终报告
    
    参数：
        question: 用户的投研问题
    
    返回：
        完整的分析报告文本
    """
    print(f"\n{'=' * 60}")
    print(f"📋 分析问题：{question}")
    print(f"{'=' * 60}")
    
    # --- 步骤 1：生成调研计划 ---
    print("\n📝 正在制定调研计划...")
    
    # 获取所有可用工具的描述
    tools_desc = "\n".join([
        f"- {name}: {tool.description}"
        for name, tool in registry._tools.items()
    ])
    
    # 调用 LLM 生成计划
    planning_input = planning_prompt.format(
        question=question,
        tools_description=tools_desc
    )
    planning_response = llm.invoke(planning_input)
    
    # 解析 LLM 返回的计划 JSON
    plan_text = planning_response.content if hasattr(planning_response, 'content') else str(planning_response)
    
    # 清理可能的 Markdown 代码块标记
    plan_text = plan_text.strip()
    if plan_text.startswith("```json"):
        plan_text = plan_text[7:]  # 去掉开头的 ```json
    if plan_text.startswith("```"):
        plan_text = plan_text[3:]  # 去掉开头的 ```
    if plan_text.endswith("```"):
        plan_text = plan_text[:-3]  # 去掉结尾的 ```
    plan_text = plan_text.strip()
    
    try:
        # 解析为 Python 字典
        plan_data = json.loads(plan_text)
        phases = plan_data.get("phases", [])
        print(f"✅ 计划生成成功，共 {len(phases)} 个阶段")
    except json.JSONDecodeError:
        # 如果 LLM 输出的 JSON 格式错误，使用默认计划
        print("⚠️ 计划 JSON 解析失败，使用默认对比模板")
        # 尝试从问题中提取两个实体名称
        default_plan = create_comparison_plan(question, "公司A", "公司B")
        phases = [
            {"name": "调研", "steps": [
                {"description": t["description"], "tool": t["tool"], "params": t["params"]}
                for t in default_plan.tasks if t["phase"] == "调研"
            ]},
            {"name": "数据", "steps": [
                {"description": t["description"], "tool": t["tool"], "params": t["params"]}
                for t in default_plan.tasks if t["phase"] == "数据"
            ]},
            {"name": "分析", "steps": [
                {"description": t["description"], "tool": t["tool"], "params": t["params"]}
                for t in default_plan.tasks if t["phase"] == "分析"
            ]},
            {"name": "报告", "steps": [
                {"description": t["description"], "tool": t["tool"], "params": t["params"]}
                for t in default_plan.tasks if t["phase"] == "报告"
            ]},
        ]
    
    # --- 步骤 2：逐步执行计划 ---
    all_results = []  # 存放每一步的执行结果
    step_counter = 0  # 步骤计数器
    
    for phase in phases:
        # 获取阶段名称
        phase_name = phase.get("name", "未知阶段")
        # 获取该阶段的所有步骤
        steps = phase.get("steps", [])
        
        print(f"\n{'─' * 40}")
        print(f"【{phase_name}阶段】共 {len(steps)} 步")
        print(f"{'─' * 40}")
        
        for step in steps:
            # 步骤序号递增
            step_counter += 1
            # 获取步骤描述
            description = step.get("description", "无描述")
            # 获取工具名称
            tool_name = step.get("tool", "")
            # 获取工具参数
            params = step.get("params", {})
            
            print(f"\n步骤{step_counter}：{description}")
            print(f"   工具：{tool_name}")
            print(f"   参数：{params}")
            
            # 报告阶段不需要调用工具，直接跳过
            if tool_name == "无" or phase_name == "报告":
                all_results.append({
                    "step": step_counter,
                    "description": description,
                    "tool": "无",
                    "result": ""
                })
                print(f"   ⏭️ 报告阶段，跳过工具调用")
                continue
            
            # 调用 MCP 工具执行
            try:
                result = registry.execute(tool_name, params)
                
                # 打印结果摘要（前 150 字符）
                result_preview = result[:150].replace("\n", " ")
                print(f"   ✅ 结果：{result_preview}...")
                
                # 保存结果
                all_results.append({
                    "step": step_counter,
                    "description": description,
                    "tool": tool_name,
                    "params": params,
                    "result": result
                })
            
            except Exception as e:
                # 工具调用失败
                error_msg = f"工具调用失败：{str(e)[:100]}"
                print(f"   ❌ {error_msg}")
                
                # 保存错误信息
                all_results.append({
                    "step": step_counter,
                    "description": description,
                    "tool": tool_name,
                    "result": error_msg
                })
    
    # --- 步骤 3：汇总数据，生成报告 ---
    print(f"\n{'─' * 40}")
    print("【汇总报告】")
    print(f"{'─' * 40}")
    
    # 把收集到的所有数据拼接成字符串
    collected_data = ""
    for item in all_results:
        collected_data += f"\n### 步骤{item['step']}：{item['description']}\n"
        collected_data += f"工具：{item['tool']}\n"
        collected_data += f"结果：{item.get('result', '无')}\n"
        collected_data += "\n"
    
    # 调用 LLM 生成报告
    report_input = report_prompt.format(
        question=question,
        collected_data=collected_data
    )
    report_response = llm.invoke(report_input)
    final_report = report_response.content if hasattr(report_response, 'content') else str(report_response)
    
    print(f"✅ 报告生成完成")
    
    return final_report


# ============================================
# 第 6 步：交互式测试
# ============================================

if __name__ == "__main__":
    print("\n可用工具：")
    # 列出所有已注册的工具
    for name in registry.list_names():
        tool = registry.get(name)
        # 截取描述的前 60 个字符显示
        desc = tool.description[:60] if tool else ""
        print(f"  🔧 {name}: {desc}...")
    
    print()
    print("示例问题：")
    print("  - 贵州茅台和五粮液谁的营收增长率更高？")
    print("  - 当前市场对白酒板块的看法如何？")
    print("  - 分析茅台的投资价值")
    print()
    
    while True:
        try:
            # 获取用户输入
            user_input = input("💬 请输入分析问题（quit 退出）：").strip()
            
            # 跳过空输入
            if not user_input:
                continue
            
            # 退出条件
            if user_input.lower() in ["quit", "exit", "退出"]:
                print("👋 再见！")
                break
            
            # 执行调研计划
            report = execute_research_plan(user_input)
            
            # 输出最终报告
            print(f"\n{'=' * 60}")
            print("📄 最终分析报告")
            print(f"{'=' * 60}\n")
            print(report)
            print()
            
        except KeyboardInterrupt:
            # 用户按 Ctrl+C 退出
            print("\n👋 再见！")
            break
        except Exception as e:
            # 捕获其他未预期的异常
            print(f"\n❌ 执行异常：{e}")
            print("请重试或输入 quit 退出")