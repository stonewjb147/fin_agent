cfa-prompt-engineering/
├── config/
│   ├── cfa_system_prompt.py      # 全局约束提示词
│   ├── cfa_role_definition.py    # 身份定义
│   └── cfa_constraints.py        # 合规+知识+层级约束
├── branch_1_study/               # 分支1：学习答疑系统
│   ├── knowledge_qa.py
│   ├── chapter_summary.py
│   ├── error_analysis.py
│   └── dual_case_generator.py
├── branch_2_research/            # 分支2：专业投研系统
│   ├── financial_analysis.py
│   ├── valuation_engine.py
│   ├── statistical_models.py
│   └── portfolio_analysis.py
├── rag_adapter/                  # RAG适配层
│   ├── retriever_optimizer.py
│   ├── source_tracer.py
│   └── context_compressor.py
├── safety_layer/                 # 兜底纠错体系
│   ├── error_corrector.py
│   ├── misuse_blocker.py
│   └── wild_view_filter.py
├── tests/
│   └── test_suite.py            # 每日测试用例
└── main.py                       # 统一调度入口

cfa知识库提示词工程体系如下：
CFA知识库提示词工程体系
├─ 底层核心基础（全局通用）
│  ├─ 身份约束：CFA持证人+投研专家+金融教研专家
│  ├─ 知识约束：优先本地向量库、杜绝幻觉、对标CFA官方教材
│  ├─ 层级约束：自动适配CFA一/二/三级难度
│  └─ 合规约束：理论教学≠投资建议
├─ 分支1：CFA学习答疑系统（核心诉求1）
│  ├─ 核心功能
│  │  ├─ 知识点精准问答&定义解读
│  │  ├─ 章节考点总结&重难点梳理
│  │  ├─ 易错点拆解&避坑指导
│  │  └─ 知识点双案例拓展（应试案例+金融实务案例）
│  ├─ 输出规范
│  │  ├─ 公式标准化
│  │  ├─ 考点明确化
│  │  └─ 场景落地化
│  └─ 增值能力：知识点关联、知识体系复盘
├─ 分支2：CFA专业投研分析系统（核心诉求2）
│  ├─ 核心分析维度
│  │  ├─ 上市公司财务深度分析（CFA财报框架）
│  │  ├─ 企业基本面价值研判
│  │  ├─ 行业周期&竞争格局分析
│  │  ├─ CFA统计模型实操应用（回归/时序/检验）
│  │  ├─ 资产估值与定价分析（权益/固收/衍生品）
│  │  └─ 投资组合理论分析与优化
│  ├─ 核心规则
│  │  ├─ 模型驱动输出
│  │  ├─ 客观中性无主观臆断
│  │  └─ 必写模型局限性与适用边界
│  └─ 输出标准：机构级结构化投研报告
├─ RAG向量库专属适配层
│  ├─ 优先检索本地CFA知识库
│  ├─ 溯源输出，拒绝模型原生幻觉知识
│  ├─ 长文本分片适配，降低内存卡顿
│  └─ 动态提示词轻量化优化
└─ 兜底纠错体系
   ├─ 知识点错误自动修正
   ├─ 模型误用场景拦截
   ├─ 非CFA野观点过滤
   └─ 输出不专业内容标准化修正

依赖关系
   CFAGlobalConstraints (Day1)
     ↓
CFARAGEngine (Day2)        ← FAISS + 嵌入模型 + DeepSeek
     ↓
CFAStudySystem (Day3-4)    ← 学习答疑
FinancialAnalysisAgent (Day5) ← 财务分析
ValuationAgent (Day6)      ← 估值分析
QuantitativeAgent (Day7)   ← 量化+组合
CorrectionSystem (Day8)    ← 兜底纠错

天数 核心主题 关键交付 对应脑图模块
Day1 底层约束系统 cfa_global_constraints.py 底层核心基础（全部）
Day2 RAG适配层 cfa_rag_engine.py（FAISS+嵌入+DeepSeek） RAG向量库专属适配层
Day3 学习答疑基础 cfa_study_system.py 分支1：知识点问答+章节总结
Day4 学习答疑进阶 error_and_case.py 分支1：易错点拆解+双案例
Day5 财务深度分析 financial_analysis.py 分支2：财务分析
Day6 估值定价引擎 valuation_engine.py 分支2：估值与定价
Day7 量化与组合 quant_models.py 分支2：统计模型+组合优化
Day8 兜底纠错 correction_system.py 兜底纠错体系（全部）
Day9 系统集成 main.py + full_test_suite.py 全局整合
Day10 文档与交付 README.md + 最终测试 项目交付

下是 Day 10 的完整交付内容：项目文档、最终优化与10天总结。这是整个10天实战计划的收尾，确保你的 CFA 智能体可交付、可维护。

---

📅 Day 10：文档撰写、最终测试与项目交付

今日主题：将10天的成果转化为一个完整的、可交付的项目。
今日目标：编写 README.md 项目文档，优化关键参数，进行最终全链路测试，并输出10天总览总结。

---

🕘 第1小时 | 概念理解：项目文档与交付标准

核心知识点：

1. 好的 README 包含什么？
   · 项目简介（是什么、解决什么问题）
   · 系统架构图（文字版或图片）
   · 环境依赖与安装步骤
   · 快速开始（如何运行）
   · 项目结构说明
   · 各模块功能介绍
   · 测试方法
   · 常见问题
2. 最终交付检查清单
   · ✅ 所有 .py 文件无语法错误
   · ✅ 集成测试通过率 ≥ 80%
   · ✅ 合规检查 100% 通过（无投资建议、无价格预测）
   · ✅ README 完整、清晰
3. 优化点
   · 检索参数 k 可根据实际体验微调
   · 纠错系统的黑名单/白名单可扩充
   · 提示词模板可继续迭代

---

🕙 第2-3小时 | 文档撰写与代码微调

文件1：README.md

在项目根目录 /Users/stonewjb/fin_agent_projects/prompts/ 下创建：

```markdown
# CFA 智能体提示词工程实战

基于 CFA 知识库的智能问答与投研分析系统，使用 DeepSeek 大模型、FAISS 向量库和自定义提示词工程。

## 系统架构

```

用户输入 → 意图路由 → 专业模块 → 纠错流水线 → 合规检查 → 最终输出
├── 学习答疑系统（知识点问答/章节总结/易错拆解/双案例）
├── 投研分析系统（财务分析/估值定价/量化模型）
└── 兜底纠错体系（知识修正/模型拦截/观点过滤/标准化）

```

## 环境依赖

- Python 3.10+
- DeepSeek API Key（设置环境变量 `DEEPSEEK_API_KEY`）
- FAISS 向量库（已包含 CFA 教材的嵌入向量）
- 依赖库安装：

```bash
pip install openai langchain langchain-community faiss-cpu sentence-transformers
```

项目结构

```
prompts/
├── config/                    # 全局约束系统
│   └── cfa_global_constraints.py
├── rag_adapter/               # RAG 引擎（FAISS + 嵌入）
│   └── cfa_rag_engine.py
├── branch_1_study/            # 学习答疑系统
│   ├── cfa_study_system.py
│   └── error_and_case.py
├── branch_2_research/         # 投研分析系统
│   ├── financial_analysis.py
│   ├── valuation_engine.py
│   └── quant_models.py
├── safety_layer/              # 兜底纠错
│   └── correction_system.py
├── tests/                     # 测试
│   └── full_test_suite.py
├── main.py                    # 统一入口（交互模式）
└── README.md
```

快速开始

1. 设置 API Key

```bash
export DEEPSEEK_API_KEY="你的key"
```

2. 确保 FAISS 向量库路径正确

修改 main.py 中 CFAAssistant 初始化时的 persist_dir 参数为你的实际路径，例如：

```python
assistant = CFAAssistant(persist_dir="/Users/stonewjb/fin_agent_projects/data/Face")
```

3. 运行交互式助手

```bash
python main.py
```

输入问题，例如：

· “什么是 WACC？”
· “总结权益估值模型章节重点”
· “对贵州茅台进行财务分析”
· “用 DCF 模型为茅台估值”
· “构建一个最小方差投资组合”

4. 运行集成测试

```bash
python tests/full_test_suite.py
```

功能模块说明

底层核心基础

· 身份约束：CFA持证人 + 投研专家 + 金融教研专家
· 知识约束：优先使用本地向量库，杜绝幻觉
· 合规约束：理论教学 ≠ 投资建议

分支1：学习答疑

· 知识点精准问答（三层响应模型）
· 章节考点总结（考点地图 + 重难点 + 例题）
· 易错点拆解（错误 → 根源 → 正解 → 锚点）
· 双案例拓展（应试 + 实务）

分支2：专业投研

· 上市公司财务深度分析（六步法）
· 资产估值与定价（绝对估值 + 相对估值 + 敏感性分析）
· 统计模型实操（回归、时序、假设检验）
· 投资组合优化（有效前沿、最小方差组合）

兜底纠错

· 知识点错误自动修正
· 模型误用场景拦截
· 非CFA观点过滤
· 输出标准化（术语 + 合规声明）

测试

集成测试覆盖所有主要模块，运行：

```bash
python tests/full_test_suite.py
```

常见问题

Q：向量库中没有相关数据怎么办？
A：系统会声明“该知识点暂未收录”，并将回答标注为教学演示。你可以随时将新的教材/年报向量化后存入 FAISS。

Q：如何更换嵌入模型？
A：修改 cfa_rag_engine.py 中的 EMBEDDING_MODEL_NAME 并重建向量库。

Q：DeepSeek 调用失败？
A：检查 DEEPSEEK_API_KEY 环境变量，并确认网络可访问 api.deepseek.com。

后续优化方向

· 将提示词模板迁移到独立的 YAML 文件
· 增加多轮对话的长期记忆
· 引入 Rerank 模型提升检索精度
· 支持更多本地模型（如 vLLM 部署）

---

本项目遵循 CFA 协会道德准则，所有输出均为教育性分析，不构成投资建议。

```

### 文件2：最终参数优化（可选）

在 `main.py` 的 `CFAAssistant.__init__` 中，你可以根据运行体验调整：

```python
self.rag = CFARAGEngine(persist_dir=persist_dir, k=8)  # 检索数量
```

纠错系统的黑名单可在 correction_system.py 的 non_cfa_terms 列表中按需增删。

---

🕛 第4小时 | 最终验证与10天总结

验证步骤：

1. 从头到尾运行集成测试：
   ```bash
   python tests/full_test_suite.py
   ```
   预期结果：6个测试至少通过5个，且所有合规检查均为 ✅。
2. 交互测试：运行 python main.py，随意问几个问题，体验全流程。
3. 检查项目结构：确认所有文件都已创建在正确位置。

10天总览总结：

天数 核心主题 关键交付 对应脑图模块
Day1 底层约束系统 cfa_global_constraints.py 底层核心基础（全部）
Day2 RAG适配层 cfa_rag_engine.py（FAISS+嵌入+DeepSeek） RAG向量库专属适配层
Day3 学习答疑基础 cfa_study_system.py 分支1：知识点问答+章节总结
Day4 学习答疑进阶 error_and_case.py 分支1：易错点拆解+双案例
Day5 财务深度分析 financial_analysis.py 分支2：财务分析
Day6 估值定价引擎 valuation_engine.py 分支2：估值与定价
Day7 量化与组合 quant_models.py 分支2：统计模型+组合优化
Day8 兜底纠错 correction_system.py 兜底纠错体系（全部）
Day9 系统集成 main.py + full_test_suite.py 全局整合
Day10 文档与交付 README.md + 最终测试 项目交付

---

✅ 最终交付物清单

· 完整可运行的 Python 项目（所有模块）
· 统一交互入口 main.py
· 端到端集成测试套件
· 详细的 README.md 文档
· 10天学习路线与代码注释

---

🎉 恭喜！ 你已经完成了基于 CFA 知识库的提示词工程10天实战。你现在拥有一个可扩展的、专业的金融智能体框架。下一步可以根据实际使用反馈，继续迭代提示词、丰富向量库、或对接更多数据源。

# cfa_study_system.py
import yaml
import os

class CFAStudySystem:
    def __init__(self, rag_engine):
        self.rag = rag_engine
        
        # 加载独立的 YML 提示词文件
        yml_path = os.path.join(os.path.dirname(__file__), 'prompts', 'cfa_study_system.yml')
        with open(yml_path, 'r', encoding='utf-8') as f:
            prompt_templates = yaml.safe_load(f)
        
        # 从加载的数据中获取模板
        self.qa_prompt_template = prompt_templates['knowledge_qa']
        self.summary_prompt_template = prompt_templates['chapter_summary']
    
    def knowledge_qa(self, question):
        # 和之前一样使用
        prompt = self.qa_prompt_template.format(context=..., question=question)
        with open(yml_path, 'r', encoding='utf-8') as f:
    prompt_templates = yaml.safe_load(f)
