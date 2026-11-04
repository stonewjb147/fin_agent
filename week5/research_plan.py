# ============================================
# DIKW：金字塔模型，关于数据挖掘需要的理论基础。
#人类分析师的行为 AI Agent的工程实现
#调研 (Research) 感知市场，获取信息，data
#数据分析 (Analysis) 处理信息，提炼逻辑 information
#报告 (Report) 形成观点，输出结论 knowledge
#反思 (Reflection) 审视结论，发现漏洞 wisdom


# 调研计划模板
# 功能：定义深度投研分析的标准流程
# 包含四个阶段：调研计划 → 数据收集 → 对比分析 → 报告输出
# Agent 会按照这个框架来组织思考过程
# ============================================

from datetime import datetime  # 用于生成时间戳
from typing import List, Dict, Any  # 类型注解，让代码更清晰


class ResearchPlan:
    """
    调研计划类
    
    定义一个完整的投研分析计划，包含：
    - 用户原始问题
    - 分解后的子任务列表
    - 每个子任务的执行状态
    - 最终报告内容
    """
    
    def __init__(self, question: str):
        """
        初始化调研计划
        
        参数：
            question: 用户提出的投研问题，例如"茅台和五粮液谁更值得投资？"
        """
        # 用户原始问题
        self.question = question
        
        # 计划生成时间
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 子任务列表，每个子任务是一个字典：
        # {
        #   "step": 步骤序号,
        #   "phase": "调研"/"数据"/"分析"/"报告",
        #   "description": "做什么",
        #   "tool": "使用哪个工具",
        #   "params": {"参数名": "参数值"},
        #   "status": "pending" | "running" | "done" | "failed",
        #   "result": "执行结果"
        # }
        self.tasks: List[Dict[str, Any]] = []
        
        # 最终报告内容
        self.final_report: str = ""
        
        # 当前执行到第几步
        self.current_step: int = 0
    
    def add_task(
        self,
        phase: str,
        description: str,
        tool: str,
        params: Dict[str, Any]
    ) -> None:
        """
        添加一个子任务到计划中
        
        参数：
            phase: 所属阶段（"调研"/"数据"/"分析"/"报告"）
            description: 任务描述，告诉 Agent 这一步要做什么
            tool: 使用的工具名称，如"网络搜索"、"计算器"、"金融信号查询"
            params: 传给工具的参数，如 {"query": "茅台营收"}
        """
        # 步骤序号自动递增
        step = len(self.tasks) + 1
        
        # 创建任务字典
        task = {
            "step": step,                    # 步骤编号
            "phase": phase,                   # 所属阶段
            "description": description,       # 任务描述
            "tool": tool,                     # 使用的工具
            "params": params,                 # 工具参数
            "status": "pending",              # 初始状态：等待执行
            "result": ""                      # 执行结果：初始为空
        }
        
        # 添加到任务列表
        self.tasks.append(task)
    
    def get_next_task(self) -> Dict[str, Any]:
        """
        获取下一个待执行的任务
        
        返回：
            下一个 pending 状态的任务字典
            如果没有待执行任务，返回空字典
        """
        # 遍历所有任务，找到第一个状态为 pending 的
        for task in self.tasks:
            if task["status"] == "pending":
                return task
        
        # 没有待执行任务
        return {}
    
    def mark_task_done(self, step: int, result: str) -> None:
        """
        标记某个任务为已完成
        
        参数：
            step: 步骤序号
            result: 工具执行返回的结果字符串
        """
        # 遍历查找对应步骤
        for task in self.tasks:
            if task["step"] == step:
                # 更新状态和结果
                task["status"] = "done"
                task["result"] = result
                break
    
    def mark_task_failed(self, step: int, error: str) -> None:
        """
        标记某个任务为执行失败
        
        参数：
            step: 步骤序号
            error: 错误信息
        """
        # 遍历查找对应步骤
        for task in self.tasks:
            if task["step"] == step:
                # 更新状态和错误信息
                task["status"] = "failed"
                task["result"] = error
                break
    
    def get_progress(self) -> str:
        """
        获取当前执行进度摘要
        
        返回：
            格式化的进度字符串，包含完成/失败/待执行数量
        """
        # 统计各状态的任务数量
        total = len(self.tasks)            # 总任务数
        done = sum(1 for t in self.tasks if t["status"] == "done")     # 已完成
        failed = sum(1 for t in self.tasks if t["status"] == "failed")  # 失败
        pending = sum(1 for t in self.tasks if t["status"] == "pending") # 待执行
        
        # 构建进度字符串
        return f"进度：{done}/{total} 完成，{failed} 失败，{pending} 待执行"
    
    def to_summary(self) -> str:
        """
        生成整个计划的摘要（给 Agent 看）
        
        返回：
            格式化的计划摘要文本
        """
        # 构建摘要行列表
        lines = []
        lines.append("=" * 60)
        lines.append(f"📋 调研计划：{self.question}")
        lines.append(f"   创建时间：{self.created_at}")
        lines.append(f"   总步骤数：{len(self.tasks)}")
        lines.append("=" * 60)
        lines.append("")
        
        # 按阶段分组显示任务
        phases = ["调研", "数据", "分析", "报告"]
        for phase in phases:
            # 筛选属于当前阶段的任务
            phase_tasks = [t for t in self.tasks if t["phase"] == phase]
            
            # 如果当前阶段没有任务，跳过
            if not phase_tasks:
                continue
            
            # 阶段标题
            lines.append(f"【{phase}阶段】")
            
            # 逐个显示任务
            for task in phase_tasks:
                # 状态图标
                status_icon = {
                    "pending": "⏳",    # 待执行
                    "running": "🔄",    # 执行中
                    "done": "✅",       # 已完成
                    "failed": "❌"      # 失败
                }.get(task["status"], "❓")
                
                # 显示步骤信息
                lines.append(
                    f"  {status_icon} 步骤{task['step']}: {task['description']}"
                )
                lines.append(f"     工具: {task['tool']}")
                lines.append(f"     参数: {task['params']}")
                
                # 如果有结果，显示结果摘要
                if task["result"]:
                    result_preview = task["result"][:100].replace("\n", " ")
                    lines.append(f"     结果: {result_preview}...")
            
            lines.append("")
        
        return "\n".join(lines)


# ============================================
# 预定义的分析模板
# ============================================

def create_comparison_plan(question: str, entity_a: str, entity_b: str) -> ResearchPlan:
    """
    创建一个"两家公司对比分析"的标准调研计划
    
    参数：
        question: 用户原始问题
        entity_a: 第一家公司的名称，如"贵州茅台"
        entity_b: 第二家公司的名称，如"五粮液"
    
    返回：
        包含标准对比步骤的 ResearchPlan 对象
    """
    # 创建计划对象
    plan = ResearchPlan(question)
    
    # 调研阶段：搜索两家公司的基本信息
    plan.add_task(
        phase="调研",
        description=f"搜索{entity_a}最新财务数据（营收、利润、增长率）",
        tool="网络搜索",
        params={"query": f"{entity_a} 2025年 营收 净利润 增长率"}
    )
    plan.add_task(
        phase="调研",
        description=f"搜索{entity_b}最新财务数据（营收、利润、增长率）",
        tool="网络搜索",
        params={"query": f"{entity_b} 2025年 营收 净利润 增长率"}
    )
    plan.add_task(
        phase="调研",
        description=f"搜索白酒行业最新政策和市场动态",
        tool="网络搜索",
        params={"query": "白酒行业 2025年 政策 市场趋势"}
    )
    
    # 数据阶段：查询本地信号数据
    plan.add_task(
        phase="数据",
        description=f"查询{entity_a}相关的最新金融信号",
        tool="金融信号查询",
        params={"asset": "白酒"}
    )
    
    # 分析阶段：关键指标对比
    plan.add_task(
        phase="分析",
        description=f"对比{entity_a}和{entity_b}的营收增长率",
        tool="计算器",
        params={"expression": "0"}  # 占位，实际计算由 Agent 根据搜索结果填入
    )
    
    # 报告阶段：汇总
    plan.add_task(
        phase="报告",
        description="汇总所有数据，输出结构化对比分析报告",
        tool="无",  # 报告阶段不需要工具
        params={}
    )
    
    return plan


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("调研计划模板测试")
    print("=" * 60)
    
    # 创建一个对比分析计划
    plan = create_comparison_plan(
        question="贵州茅台和五粮液谁更值得投资？",
        entity_a="贵州茅台",
        entity_b="五粮液"
    )
    
    # 打印计划摘要
    print(plan.to_summary())
    
    # 测试获取下一个任务
    print("下一个待执行任务：")
    next_task = plan.get_next_task()
    print(f"  步骤{next_task['step']}: {next_task['description']}")
    
    # 测试标记完成
    plan.mark_task_done(1, "茅台2025年营收1500亿，净利润800亿，增长率20%")
    print(f"\n{plan.get_progress()}")