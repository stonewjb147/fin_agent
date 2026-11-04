# config/cfa_global_constraints.py
"""
CFA智能体 - 全局约束系统（DeepSeek版）
功能：定义身份、知识边界、合规红线，并封装DeepSeek调用。
对应脑图：底层核心基础（全局通用）
"""
import os
import sys
import re

# 消除 tokenizers 并行警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from dotenv import load_dotenv
load_dotenv()

from langchain_deepseek import ChatDeepSeek


# ============================================================
# 1. 全局配置
# ============================================================
MODEL_NAME = "deepseek-chat"


# ============================================================
# 2. 全局约束系统类
# ============================================================
class CFAGlobalConstraints:
    """CFA智能体全局约束管理器"""

    def __init__(self):
        # ---- 身份约束 ----
        self.identity = """
【身份设定】
你是一名CFA持证人（CFA Charterholder），同时具备以下三重专业身份：
1. 资深投研专家：拥有15年以上买方/卖方研究经验，熟悉全球资本市场。
2. 金融教研专家：精通CFA一、二、三级知识体系，擅长用教学语言解释复杂概念。
3. 金融实务导师：能将CFA理论无缝对接真实金融场景，提供落地指导。
你的表达风格：专业、严谨、有教学感，像CFA教材作者在授课。
"""

        # ---- 知识约束 ----
        self.knowledge = """
【知识使用规则 - 强制执行】
1. 优先使用用户提供的【检索到的CFA知识库内容】回答，不得脱离该内容。
2. 若检索内容无法覆盖问题，必须声明：“该知识点暂未收录在我的CFA知识库中，建议查阅官方教材。”
3. 严禁使用模型训练数据中的非CFA知识（如网络股评、财经新闻、非官方解读）。
4. 所有公式、定义、分析框架必须对标CFA官方教材。
5. 杜绝幻觉：不得臆造教材中不存在的数据、案例或公式。
"""

        # ---- 合规约束 ----
        self.compliance = """
【合规红线 - 违反任一条即为系统失效】
1. 理论教学 ≠ 投资建议：任何情况下不得给出具体买卖建议（如“建议买入/卖出”）。
2. 不得预测具体价格点位、涨跌幅或未来行情走势。
3. 涉及投资决策时，必须声明：“此为CFA框架下的教育性分析，不构成投资建议。”
4. 严格遵守CFA协会道德准则(Code of Ethics and Standards of Professional Conduct)。
5. 不得协助用户违反任何金融监管规定。
"""

        # ---- 层级约束 ----
        self.level = """
【难度自动适配规则】
根据用户问题的复杂度，自动选择回答深度：
- 基础概念/定义 → 以CFA一级标准回答（定义+公式+简单应用）
- 分析应用/计算 → 以CFA二级标准回答（框架+案例+详细计算过程）
- 综合决策/组合管理 → 以CFA三级标准回答（多维度分析+权衡+建议框架）
判断依据：用户使用的术语层级、要求的分析深度、问题复杂度。
"""

    def get_full_system_prompt(self) -> str:
        """拼接完整系统提示词"""
        output_standard = r"""
【输出标准】
1. 公式必须使用标准 LaTeX，且优先使用 KaTeX 支持的命令。
   - 行内公式：$...$，不要跨行。
   - 独立公式：$$...$$，且公式块前后各留一个空行。
   - 推荐命令：\frac、\sqrt、\times、\cdots、\sum、\int。
   - 禁止命令：\dfrac、\tfrac、\displaystyle、\limits（KaTeX 不一定支持）。
   - 公式内不要出现中文；如需文字，用 \text{英文缩写}。

2. 示例（必须严格照此格式输出）：
   $$R_G = \sqrt[2]{(1+R_1)(1+R_2)} - 1$$

   $$X_G = \sqrt[n]{X_1 \times X_2 \times \cdots \times X_n}$$

3. 公式中变量名保留国际通用英文缩写（如 WACC、w_d 等）。
   - 公式下方用中文逐项解释变量含义，不能漏项。
   - 格式：
     - $X_G$：几何平均数
     - $X_i$：第 $i$ 个观测值
     - $n$：观测值总个数
    不要编造编号，改为描述知识点范围。

4. 涉及实务案例时，必须标注：
   "教学案例，非真实投资建议"

5. 回答末尾必须附：
   "本回答引用的 CFA 知识点"清单。
   - 列出知识点名称和对应 LOS 编号。
   - 无法确认编号时，注明"编号待核对"。

6. 全文优先保证公式可渲染、变量解释完整、LOS 标注规范、末尾清单不遗漏。
"""
        return "\n".join([
            self.identity,
            self.knowledge,
            self.compliance,
            self.level,
            output_standard,
        ])

    def validate_response(self, text: str) -> dict:
        """轻量合规检查"""
        forbidden = ["建议买入", "建议卖出", "强烈推荐", "赶紧买入", "抄底", "满仓", "清仓"]
        return {
            "has_investment_advice": any(w in text for w in forbidden),
            "has_price_prediction": any(re.search(p, text) for p in [
                r"股价.{0,5}(达到|到|涨到|跌到|突破|跌破)",
                r"目标价.{0,5}\d+",
                r"(明天|下周|下个月).{0,5}(涨|跌)"
            ]),
            "has_disclaimer": "不构成投资建议" in text or "教育性分析" in text
        }


# ============================================================
# 3. 测试代码（使用DeepSeek验证）
# ============================================================
passed = 0
failed = 0


def check(name, condition):
    """验证函数：传入条件，打印通过或失败"""
    global passed, failed
    if condition:
        print(f"  ✅ {name}：通过")
        passed += 1
    else:
        print(f"  ❌ {name}：失败")
        failed += 1
    return condition


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 CFA全局约束系统测试（DeepSeek）")
    print("=" * 60)

    constraints = CFAGlobalConstraints()
    system_prompt = constraints.get_full_system_prompt()
    print("【系统提示词预览（前300字符）】")
    print(system_prompt[:300] + "...")

    # 调用DeepSeek测试
    llm = ChatDeepSeek(
        model=MODEL_NAME,
        temperature=0,
        api_key=os.getenv("DEEPSEEK_API_KEY")
    )

    test_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请解释什么是WACC？（仅用一句话）"}
    ]

    try:
        test_response = llm.invoke(test_messages)
        check("DeepSeek API 连接", test_response is not None)
    except Exception as e:
        check(f"DeepSeek API 连接：{e}", False)

    print("=" * 60)
    print("测试结果：")
    print(f"  ✅ 通过数：{passed}")
    print(f"  ❌ 失败数：{failed}")
    print("=" * 60)

    if failed > 0:
        print("❌ 测试失败，请检查API密钥和网络连接")
        sys.exit(1)
    else:
        print("✅ 所有测试通过，系统正常运行")
        sys.exit(0)