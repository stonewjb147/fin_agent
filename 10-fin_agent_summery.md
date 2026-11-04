# 🎓 金融智能体十练 · 全课程总结

## 学习周期
2026年5月24日 — 2026年6月6日（8周）

## 硬件环境
- MacBook Pro Intel x86
- 8GB 内存 / 256GB SSD
- Python 3.10.18 + Miniforge

---

## 十练全景图

### 第一层：基础能力（第1-2练）

| 练数 | 名称 | 核心技能 | 产出 |
|------|------|---------|------|
| 第1练 | Python环境搭建 | conda环境管理、版本锁定 | fin_agent 环境 |
| 第2练 | Vibe Coding | AI辅助编程、Git | SMA/RSI函数、命令行工具 |

### 第二层：感知能力（第3-5练）

| 练数 | 名称 | 核心技能 | 产出 |
|------|------|---------|------|
| 第3练 | Agentic RAG | FAISS向量库、ReAct智能体 | 年报问答系统（14项测试通过） |
| 第4练 | 全球情报守望者 | BERTopic聚类、信号提取 | 新闻→主题→信号→简报 |
| 第5练 | 24h数字分身 | 飞书机器人、定时推送 | @机器人智能回复+每日简报 |

### 第三层：决策能力（第6-10练）

| 练数 | 名称 | 核心技能 | 产出 |
|------|------|---------|------|
| 第6练 | 深度投研综合体 | Deep Agent、MCP工具封装 | 茅台vs五粮液对比报告 |
| 第7练 | 因子挖掘机 | LangGraph、因子生成验证闭环 | 自动因子挖掘流程 |
| 第8练 | 圆桌辩论会 | 多Agent辩论、裁判裁决 | 多空辩论+四维度评分 |
| 第9练 | 风控子系统 | 规则引擎、LangGraph审批图 | 5道防线+飞书告警 |
| 第10练 | CUFEI-Q主智能体 | 全模块整合、回测验证 | 完整投资决策闭环 |

---

## 技术栈总览

| 层级 | 技术 |
|------|------|
| 环境 | Miniforge、Python 3.10、uv |
| AI模型 | DeepSeek Chat、BAAI/bge-small-zh |
| 框架 | LangChain、LangGraph、Flask |
| 数据库 | FAISS（向量）、JSONL（信号） |
| 聚类 | BERTopic、scikit-learn |
| 监控 | Langfuse |
| 消息 | 飞书机器人、ngrok |
| 搜索 | Tavily API、聚合数据 |
| 回测 | 自建ETF模拟环境 |

---

## 项目文件结构

---

## 核心收获

1. **从工具使用者到系统构建者**：从调用API到构建完整Agent系统
2. **LangGraph图编排**：掌握了State→Node→Edge→Conditional Edge的编程范式
3. **多Agent协作**：理解了Agent之间如何分工、辩论、裁决
4. **风控意识**：任何投资决策都需要经过风控审核
5. **全链路整合**：信号→决策→风控→执行→监控的完整闭环

## 后续方向

1. 接入真实行情数据（AkShare/Tushare）
2. 部署到云服务器（替换ngrok）
3. 增加更多因子类型（动量、波动率、资金流）
4. 实盘模拟交易对接

优先级 调优方向 投入工作量 效果提升 性价比
1 工具/Skill生态建设 中（2-3周） 高（能力边界扩展10倍） ⭐⭐⭐⭐⭐
  优先级 Skill名称 功能 实现难度 投入时间
P0 get_stock_quote 获取实时股价 低（调用免费API） 2小时
P0 get_financial_ratios 获取财务指标（ROE、PE、PB等） 中（对接Tushare/AKShare） 1天
P0 get_industry_performance 获取行业涨跌幅排名 低 2小时
P1 get_macro_data 获取宏观经济数据（GDP、CPI、利率） 中 1天
P1 get_news_sentiment 获取新闻情绪分析（复用第4练） 低（已有） 1小时
P2 backtest_factor 回测因子有效性 高 3-5天
P2 get_fund_flow 获取北向资金流向 中 1天

# 在 deep_tools.py 中添加
import yfinance as yf  # 免费美股数据
# 或使用 akshare（A股数据）

def get_stock_quote(symbol: str) -> str:
    """
    获取股票实时行情
    
    参数：
        symbol: 股票代码，如 "600519.SS"（茅台）或 "AAPL"（苹果）
    
    返回：
        格式化行情字符串
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return f"""
📊 {info.get('longName', symbol)} 实时行情
   最新价：{info.get('regularMarketPrice', 'N/A')}
   涨跌幅：{info.get('regularMarketChangePercent', 'N/A'):.2f}%
   市盈率：{info.get('trailingPE', 'N/A')}
   市值：{info.get('marketCap', 'N/A'):,.0f}
"""
    except Exception as e:
        return f"获取行情失败：{e}"
2 数据源扩展与融合 中（2-3周） 高（信息覆盖率提升） ⭐⭐⭐⭐⭐
数据源 用途 接入成本 效果
Tushare/AKShare A股财务数据、行情数据 免费/低（需注册） 覆盖全市场
yfinance 美股/港股数据 免费 国际市场
新浪财经API 实时A股行情 免费 实时数据
东方财富网 研报、公告 爬虫（需谨慎） 研报数据

# 创建统一的数据获取接口
def get_financial_data(stock_code: str, data_type: str) -> str:
    """
    统一数据接口：根据数据源优先级自动切换
    """
    # 优先级1：缓存数据
    cached = get_from_cache(stock_code, data_type)
    if cached:
        return cached
    
    # 优先级2：Tushare（A股）
    try:
        data = get_from_tushare(stock_code, data_type)
        save_to_cache(stock_code, data_type, data)
        return data
    except:
        pass
    
    # 优先级3：yfinance（美股/港股）
    try:
        data = get_from_yfinance(stock_code, data_type)
        save_to_cache(stock_code, data_type, data)
        return data
    except:
        pass
    
    # 优先级4：网络搜索（兜底）
    return web_search(f"{stock_code} {data_type}")
3 推理质量优化 低（1周） 中（准确率提升20-30%） ⭐⭐⭐⭐
优化点 当前问题 优化方法 预期效果
提示词工程 格式解析偶尔失败 增加 few-shot 示例 减少50%格式错误
迭代次数 5-10次不够复杂任务 动态调整 max_iterations 复杂任务完成率提升
错误恢复 出错直接中断 增加重试和 fallback 稳定性提升
结果验证 直接输出不做检查 增加 self-check 节点 准确性提升

# 在 react_template 中添加 few-shot 示例
react_template = """你是一个专业的投研分析助手。

【工具使用示例】
Question: 茅台和五粮液谁营收更高？
Thought: 我需要先搜索茅台和五粮液的营收数据
Action: 网络搜索
Action Input: 贵州茅台 2025 年营收
Observation: 茅台 2025 年营收 1580 亿元
Thought: 现在搜索五粮液
Action: 网络搜索
Action Input: 五粮液 2025 年营收
Observation: 五粮液 2025 年营收 950 亿元
Thought: 可以对比了
Final Answer: 茅台营收 1580 亿，五粮液 950 亿，茅台更高。

【你的任务】
{tools}

用户问题：{input}
{agent_scratchpad}"""
4 持续学习机制 高（1-2月） 高（长期价值） ⭐⭐⭐（长期）
功能 实现方式 复杂度
对话记忆 用户级向量库存储历史问答 中
偏好学习 记录用户关注的股票/行业，主动推送 中
反馈循环 收集用户对答案的评价，优化检索 高
策略迭代 根据回测结果自动调整因子权重 高

# 在 master_state.py 中添加
user_memory = {}  # 存储用户偏好
# 示例：记录用户常问的股票
if "茅台" in user_query:
    user_memory["favorite_stocks"] = user_memory.get("favorite_stocks", [])
    if "茅台" not in user_memory["favorite_stocks"]:
        user_memory["favorite_stocks"].append("茅台")

