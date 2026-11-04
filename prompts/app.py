# app.py
"""
CFA 智能体 - Streamlit Web 界面
运行方式：streamlit run app.py
"""
import streamlit as st
import sys
import os
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 页面配置（必须是第一个 Streamlit 命令）
# ============================================================
st.set_page_config(
    page_title="CFA 智能体",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# 自定义 CSS 美化
# ============================================================
st.markdown("""
<style>
    /* 主标题样式 */
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1f4e79;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    /* 合规徽章 */
    .badge-pass {
        background-color: #d4edda;
        color: #155724;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-fail {
        background-color: #f8d7da;
        color: #721c24;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    /* 来源卡片 */
    .source-card {
        background-color: #f8f9fa;
        border-left: 3px solid #1f4e79;
        padding: 8px 12px;
        margin: 5px 0;
        font-size: 0.85rem;
        border-radius: 4px;
    }
    /* 聊天消息 */
    .stChatMessage {
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 缓存初始化智能体（避免重复加载模型）
# ============================================================
@st.cache_resource(show_spinner="正在加载 CFA 智能体，首次加载较慢...")
def load_assistant(persist_dir: str, k: int):
    """加载智能体，使用缓存避免重复初始化"""
    from rag_adapter.cfa_rag_engine import CFARAGEngine
    from branch1.cfa_study_system import CFAStudySystem
    from branch1.error_and_case import AdvancedStudySystem
    from branch2.financial_analysis import FinancialAnalysisAgent
    from branch2.valuation_engine import ValuationAgent
    from branch2.quant_models import QuantitativeAgent
    from safety_layer.correction_system import CorrectionSystem

    rag = CFARAGEngine(persist_dir=persist_dir, k=k)

    return {
        "rag": rag,
        "study": CFAStudySystem(rag),
        "advanced_study": AdvancedStudySystem(rag),
        "financial": FinancialAnalysisAgent(rag),
        "valuation": ValuationAgent(rag),
        "quant": QuantitativeAgent(rag),
        "corrector": CorrectionSystem(),
    }


# ============================================================
# 侧边栏配置
# ============================================================
with st.sidebar:
    st.markdown("## ⚙️ 配置面板")

    # 向量库路径
    persist_dir = st.text_input(
        "FAISS 向量库路径",
        value="/Users/stonewjb/fin_agent_projects/faiss_index",
        help="你的 FAISS 向量库所在目录"
    )

    # 检索数量
    k_value = st.slider(
        "检索文档数量 (k)",
        min_value=3, max_value=15, value=8,
        help="每次检索返回的最相关文档数，越大上下文越丰富但速度越慢"
    )

    st.divider()

    # 功能选择
    st.markdown("## 🎯 功能模块")
    module = st.radio(
        "选择功能",
        options=[
            "💬 学习答疑",
            "🔍 易错与案例",
            "📈 财务分析",
            "💰 估值定价",
            "📊 量化与组合",
            "🛡️ 纠错演示",
        ],
        label_visibility="collapsed"
    )

    st.divider()

    # 知识库状态
    st.markdown("## 📚 知识库状态")
    if os.path.exists(persist_dir):
        faiss_file = os.path.join(persist_dir, "index.faiss")
        pkl_file = os.path.join(persist_dir, "index.pkl")
        if os.path.exists(faiss_file) and os.path.exists(pkl_file):
            st.success("✅ 向量库已就绪")
        else:
            st.warning("⚠️ 缺少 index.faiss 或 index.pkl")
    else:
        st.error("❌ 向量库路径不存在")

    st.divider()

    # 清空对话
    if st.button("🗑️ 清空对话历史", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.caption("CFA 智能体 v1.0 · 仅供教育用途")


# ============================================================
# 主区域
# ============================================================
st.markdown('<div class="main-title">📊 CFA 智能体</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">基于 CFA 知识库的智能问答与投研分析系统 · '
    'DeepSeek + FAISS + bge-small-zh</div>',
    unsafe_allow_html=True
)

# 初始化会话状态
if "messages" not in st.session_state:
    st.session_state.messages = []


# ============================================================
# 通用结果渲染函数
# ============================================================
def render_result(result: dict, answer_key: str = "answer"):
    """统一渲染结果：回答 + 合规检查 + 来源"""
    answer = result.get(answer_key) or result.get("report") or result.get("summary") or result.get("analysis") or result.get("cases", "")

    # 合规徽章
    validation = result.get("validation", {})
    if validation:
        has_advice = validation.get("has_investment_advice", False)
        has_price = validation.get("has_price_prediction", False)
        if not has_advice and not has_price:
            st.markdown(
                '<span class="badge-pass">✅ 合规检查通过 · 无投资建议 · 无价格预测</span>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<span class="badge-fail">⚠️ 合规警告 · 检测到潜在违规内容</span>',
                unsafe_allow_html=True
            )

    # 回答内容
    st.markdown(answer)

    # 来源展示
    sources = result.get("sources", [])
    if sources:
        with st.expander(f"📎 检索来源（{len(sources)} 条）"):
            for i, src in enumerate(sources, 1):
                if isinstance(src, dict):
                    content = src.get("content", "")[:200]
                    meta = src.get("metadata", src)
                    source_name = meta.get("source", "未知")
                    chapter = meta.get("chapter", "未知")
                    st.markdown(
                        f'<div class="source-card"><b>[{i}]</b> 来源：{source_name} | '
                        f'章节：{chapter}<br>{content}...</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(f'<div class="source-card"><b>[{i}]</b> {str(src)[:200]}</div>',
                                unsafe_allow_html=True)


# ============================================================
# 模块1：学习答疑
# ============================================================
if module == "💬 学习答疑":
    st.markdown("### 💬 CFA 学习答疑")
    st.caption("知识点精准问答 · 三层响应模型（定义 → 理解 → 应用）")

    # 模式选择
    qa_mode = st.radio(
        "选择答疑模式",
        ["知识点精准问答", "章节考点总结"],
        horizontal=True
    )

    # 对话历史
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_result(msg["data"])
            else:
                st.markdown(msg["content"])

    # 输入框
    placeholder = "例如：什么是WACC？如何计算？" if qa_mode == "知识点精准问答" else "例如：权益估值模型"
    if prompt := st.chat_input(placeholder):
        # 显示用户消息
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 生成回答
        with st.chat_message("assistant"):
            with st.spinner("正在检索 CFA 知识库并生成回答..."):
                try:
                    assistant = load_assistant(persist_dir, k_value)
                    if qa_mode == "知识点精准问答":
                        result = assistant["study"].knowledge_qa(prompt)
                    else:
                        result = assistant["study"].chapter_summary(prompt)
                    render_result(result)
                    st.session_state.messages.append(
                        {"role": "assistant", "data": result}
                    )
                except Exception as e:
                    st.error(f"出错：{e}")


# ============================================================
# 模块2：易错与案例
# ============================================================
elif module == "🔍 易错与案例":
    st.markdown("### 🔍 易错点拆解 & 双案例拓展")
    st.caption("错误表象 → 根源 → 正解 → 记忆锚点 → 变体练习")

    case_mode = st.radio(
        "选择功能",
        ["易错点拆解", "双案例生成"],
        horizontal=True
    )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_result(msg["data"], answer_key="analysis")
            else:
                st.markdown(msg["content"])

    placeholder = "输入知识点，例如：WACC计算" if case_mode == "易错点拆解" else "输入知识点，例如：杜邦分析"
    if prompt := st.chat_input(placeholder):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("正在分析..."):
                try:
                    assistant = load_assistant(persist_dir, k_value)
                    if case_mode == "易错点拆解":
                        result = assistant["advanced_study"].error_analysis(prompt)
                        render_result(result, answer_key="analysis")
                    else:
                        result = assistant["advanced_study"].dual_case(prompt)
                        render_result(result, answer_key="cases")
                    st.session_state.messages.append(
                        {"role": "assistant", "data": result}
                    )
                except Exception as e:
                    st.error(f"出错：{e}")


# ============================================================
# 模块3：财务分析
# ============================================================
elif module == "📈 财务分析":
    st.markdown("### 📈 上市公司财务深度分析")
    st.caption("CFA 六步法：盈利质量 → 杜邦分析 → 比率全景 → 预测 → 风险 → 结论")

    col1, col2 = st.columns([1, 2])
    with col1:
        company_name = st.text_input("公司名称", value="贵州茅台")
    with col2:
        company_data = st.text_area(
            "补充财务数据（可选）",
            placeholder="粘贴年报关键数据，留空则基于向量库检索",
            height=80
        )

    if st.button("🚀 开始分析", type="primary", use_container_width=True):
        with st.spinner(f"正在对 {company_name} 进行 CFA 财务深度分析..."):
            try:
                assistant = load_assistant(persist_dir, k_value)
                result = assistant["financial"].analyze(
                    company_name=company_name,
                    company_data=company_data
                )
                st.divider()
                render_result(result, answer_key="report")
            except Exception as e:
                st.error(f"分析出错：{e}")


# ============================================================
# 模块4：估值定价
# ============================================================
elif module == "💰 估值定价":
    st.markdown("### 💰 资产估值与定价分析")
    st.caption("DCF / 相对估值 / 敏感性分析 · 输出估值区间而非单一目标价")

    col1, col2 = st.columns([1, 2])
    with col1:
        asset_name = st.text_input("资产名称", value="贵州茅台")
    with col2:
        asset_info = st.text_area(
            "补充假设与信息（可选）",
            placeholder="例如：无风险利率2.5%，市场风险溢价6%",
            height=80
        )

    if st.button("🚀 开始估值", type="primary", use_container_width=True):
        with st.spinner(f"正在对 {asset_name} 进行估值分析..."):
            try:
                assistant = load_assistant(persist_dir, k_value)
                result = assistant["valuation"].valuation_report(
                    asset_name=asset_name,
                    asset_info=asset_info
                )
                st.divider()
                render_result(result, answer_key="report")
            except Exception as e:
                st.error(f"估值出错：{e}")


# ============================================================
# 模块5：量化与组合
# ============================================================
elif module == "📊 量化与组合":
    st.markdown("### 📊 CFA 量化模型 & 投资组合优化")
    st.caption("回归分析 · 时间序列 · 假设检验 · 马科维茨有效前沿")

    quant_mode = st.radio(
        "选择功能",
        ["统计模型分析", "投资组合优化"],
        horizontal=True
    )

    if quant_mode == "统计模型分析":
        col1, col2 = st.columns([1, 2])
        with col1:
            model_name = st.text_input("模型名称", value="Fama-French三因子模型")
        with col2:
            user_request = st.text_area(
                "分析请求",
                placeholder="例如：用茅台2020-2025月度收益数据演示回归分析",
                height=80
            )
        if st.button("🚀 开始分析", type="primary", use_container_width=True):
            with st.spinner("正在进行统计模型分析..."):
                try:
                    assistant = load_assistant(persist_dir, k_value)
                    result = assistant["quant"].statistical_analysis(
                        model_name=model_name,
                        user_request=user_request
                    )
                    st.divider()
                    render_result(result, answer_key="report")
                except Exception as e:
                    st.error(f"出错：{e}")
    else:
        user_request = st.text_area(
            "组合优化请求",
            placeholder="例如：从沪深300中选取5只股票，构建最小方差组合",
            height=100
        )
        if st.button("🚀 开始优化", type="primary", use_container_width=True):
            with st.spinner("正在构建投资组合..."):
                try:
                    assistant = load_assistant(persist_dir, k_value)
                    result = assistant["quant"].portfolio_optimization(user_request)
                    st.divider()
                    render_result(result, answer_key="report")
                except Exception as e:
                    st.error(f"出错：{e}")


# ============================================================
# 模块6：纠错演示
# ============================================================
elif module == "🛡️ 纠错演示":
    st.markdown("### 🛡️ 兜底纠错体系演示")
    st.caption("知识点修正 · 模型误用拦截 · 非CFA观点过滤 · 输出标准化")

    st.markdown("**输入一段可能包含问题的回答，系统将自动纠错：**")

    test_answer = st.text_area(
        "待检测文本",
        value="""根据DCF估值，贵州茅台的合理股价应该在2500元左右。
我们采用了CAPM模型，假设贝塔为1.2。
从波浪理论的角度看，股价处于第三浪主升浪，建议买入。
该公司的股本回报率高达30%。""",
        height=120
    )

    if st.button("🔍 执行纠错", type="primary", use_container_width=True):
        try:
            from safety_layer.correction_system import CorrectionSystem
            cs = CorrectionSystem()
            result = cs.full_pipeline(test_answer, [])

            st.divider()
            st.markdown("#### 📝 纠错后输出")
            st.markdown(result["final_output"])

            st.markdown("#### 📋 纠错详情")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("知识点修正", len(result["steps"]["knowledge_correction"]["corrections"]))
            with col2:
                st.metric("模型误用", len(result["steps"]["misuse_interception"]["misuses_found"]))
            with col3:
                st.metric("非CFA术语", len(result["steps"]["view_filtering"]["non_cfa_terms_found"]))
            with col4:
                st.metric("标准化修改", len(result["steps"]["standardization"]["changes"]))

            with st.expander("查看详细日志"):
                st.json(result["steps"])
        except Exception as e:
            st.error(f"纠错出错：{e}")