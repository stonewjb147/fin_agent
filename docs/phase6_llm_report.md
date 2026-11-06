# Phase 6：证据约束的 LLM 报告与评测

Phase 6 只做一件事：让 LLM 把已经算好的数字写成中文研究报告，同时**不让它发明任何数字**。
数字仍由 pandas/numpy 产出，报告只负责组织、对比、写限制与证伪条件。人做最终决策。

> 操作、排障与扩展见 [`phase6_manual.md`](phase6_manual.md)；本文保留设计与实测记录。

## 0. 一页结论

| 项目 | 结果 |
|---|---|
| 报告输入 | `signals`（必需）+ `portfolio` / `factor_report` / `health` / `phase_eval`（可选） |
| 证据表 | 2026-11-05 共 **104** 条，条目有稳定 ID、显示值和来源 |
| 本机真实 LLM 跑 | `deepseek-chat`，第 **1** 次尝试通过；**81/81** 引用有效，**86** 个数字全部可追溯（采样有波动，数量会变，门禁比例不变） |
| 确定性模板 | 同样通过门禁；不需要 key、不联网 |
| 无 key / 调用失败 / 输出不合格 | 自动回退模板，`fallback_reason` 写入 JSON |
| 测试 | 全量 **225 passed**；新增 10 个报告测试、6 个客户端/环境测试、2 个指标测试 |

报告不会改变信号，也不会把 `validated=false` 改成 `true`。它是一份**可审计的研究记录**，不是交易指令。

---

## 1. 为什么需要门禁

LLM 写研究报告有四种典型失败：

1. **编数字**：把 14.78% 写成 15%，或者写出证据里没有的收益率。
2. **编来源**：引用一个不存在的 `[snap:xxx]`，看起来有依据。
3. **过度自信**：把 0 个显著因子写成「因子有效」，把回测说成「可实盘」。
4. **漏结构**：只写结论，不写数据限制和证伪条件。

所以本项目把「叙事」放在一个很窄的管道里：

```
artefacts → ReportFacts → EvidenceBundle（唯一数字集合）
          → prompt（证据表 + 硬规则）
          → LLM
          → gates（结构 / 必需词 / 禁用词 / 引用 / 严格数字）
          → 通过：保存；不通过：重试一次；仍不通过：确定性模板
```

LLM 不被信任，模板也不被信任：两者走同一套 `verify_report`。

---

## 2. 证据表

`finagent/agent/evidence.py` 把五类产物读成 `ReportFacts`，再压成 `EvidenceBundle`。

每条证据：

```python
Evidence(
    id="portfolio:2026-11-05:portfolio_vol_pct",
    label="组合年化波动率",
    value=14.78,        # 已经是正文要用的单位：百分数，不是 0.1478
    unit="%",
    note="",
)
```

要点：

- **显示单位统一**：百分比在证据层就乘 100 并四舍五入，避免 LLM 把 0.1478 写成 0.15%。
- **值先取整再加门禁**：合成得分保留 2 位、IC 保留 4 位、q 值保留 3 位。证据里没有的精度，正文也不许出现。
- **ID 稳定可读**：`signals:<date>:n_signals`、`signal:<symbol>:composite`、`factor:<name>:h<h>:ic_neutral`、`backtest:<strategy>:cagr_pct`。引用直接写 `[snap:<ID>]`。
- **缺件不猜**：可选工件缺失时记进 `bundle.missing`，模板会写「相关结论从略」，不会用默认值补。
- **只收聚合数字**：证据表不塞原始 DataFrame，避免 prompt 过长，也避免 LLM 从明细里「自己算」。

2026-11-05 当天证据表 104 条，覆盖信号计数、前 5 多/前 5 空、组合权重与类别暴露、9 项因子检验、健康检查、有效广度和回测基准。

---

## 3. 门禁规则

`finagent/agent/report.py::verify_report` 复用 `finagent/evals/metrics.py`，并加了一条更严格的数字规则：

| 门禁 | 规则 | 失败后的处理 |
|---|---|---|
| 五段结构 | 必须出现 `## 结论 / ## 信号 / ## 组合 / ## 数据与限制 / ## 证伪条件` | 重试 |
| 必需词组 | `validated=false`、`存续偏差`、`不构成投资建议` | 重试 |
| 禁用词 | `稳赚 / 必涨 / 保证收益 / 推荐买入 / 建议买入 / 满仓 / 抄底` | 重试 |
| 引用 | 所有 `[snap:ID]` 必须在证据表里；至少 10 处 | 重试 |
| 严格数字 | **每个数字**都必须是某个证据值按所写小数位四舍五入的结果 | 重试 |

为什么另加「严格数字」：

- 通用评测 `numeric_traceability` 允许 1% 相对误差，并且只要 95% 的数字可追溯就算通过。对 eval 套件合适，对每日报告太松：86 个数字里混进 1 个假数字仍然是 0.988。
- 1% 容差还会放过「多写精度」：证据是 1.3，正文写 1.30341 也能通过。读者会以为系统算到了 5 位小数。
- `strict_untraceable` 的判定是 `value == round(evidence_value, decimals_in_text)`。所以 `14.8%` 可以由 `14.78` 四舍五入得到，`1.30341` 不能由 `1.3` 得到，`48` 不能由 `49` 得到。

重试策略是**一次**：把失败原因和上一版一起发回去，要求重写全文。两次都不合格就回退。重试三次以上只是在为同一类错误付更多 token，且会让「报告是否可靠」依赖运气。

---

## 4. 标识符不是数字声明

严格门禁最先误伤的是标识符：

- 日期 `2026-11-05` 会被 `NUMBER_RE` 拆成 2026、-11、-05；
- ETF 代码 `510300`、产品名 `沪深300ETF`、策略名 `hs300_buyhold`、因子名 `momentum_20` 都含数字；
- 年份 `2024` 也不是证据值。

处理方式分三层：

1. `DATE_RE` 在抽取数字前删掉 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY年M月D日`、`YYYYMMDD`。
2. `ignore_values` 忽略六位 ETF 代码。
3. `ignore_terms` 在抽取前把已知产品名、代码、因子名、策略名整体替换成空格。产品名里的数字属于名字，不属于结论。

这也是为什么本机第一次真实运行时，报告因为 `hs300_buyhold` 里的 `300` 被判不合格；把策略名加入 `ignore_terms` 后通过。**门禁误伤标识符时要修掩码，不要放宽数字规则。**

---

## 5. 确定性回退

`finagent/agent/template.py` 用同一份证据表生成报告：

- 所有数字通过 `_show(bundle, "<ID>")` 读取，绝不从原始 JSON 直接取；
- 结构、必需词、禁用词与 LLM 完全相同；
- 模板自己也过 `verify_report`，不通过就抛 `ReportError`，而不是写一份坏报告。

三种回退原因都会写进 JSON：

```json
{
  "mode": "template",
  "fallback_reason": "DEEPSEEK_API_KEY not configured"
}
```

```json
{
  "mode": "template",
  "attempts": 2,
  "fallback_reason": "LLM output rejected after 2 attempt(s): untraceable numbers: [300.0]"
}
```

```json
{
  "mode": "template",
  "fallback_reason": "LLM unavailable: LLM returned HTTP 401"
}
```

因此服务器上没有 DeepSeek key 也能每天产出报告，只是 `mode=template`。这比「LLM 不可用就跳过」更符合运维习惯：产物始终存在，质量差异可查。

---

## 6. 实测

### 6.1 本机 LLM 报告（2026-11-05）

```bash
python -m finagent.cli report --date 2026-11-05
```

```
Report for 2026-11-05
Mode        : llm (model deepseek-chat, 1 attempt(s))
Gate        : PASS
Citations   : 81/81 valid
Numbers     : 86 checked, 0 untraceable
Markdown    : data/reports/report_2026-11-05.md
JSON        : data/reports/report_2026-11-05.json
```

JSON 关键字段：

- `evidence.items`：104 条
- `checks.numeric_strict`：`{"score": 1.0, "checked": 86, "untraceable": []}`
- `prompt_sha256`：可复现的提示词指纹
- `missing`：`[]`
- 正文里没有 API key；JSON 也不记录 key。

### 6.2 确定性模板

```bash
python -m finagent.cli report --date 2026-11-05 --no-llm
```

```
Mode        : template
Gate        : PASS
Citations   : 51/51 valid
Numbers     : 51 checked, 0 untraceable
```

模板比 LLM 写得克制：只覆盖核心计数、前三条多空、组合波动与类别预算、健康检查、有效广度和证伪条件。

### 6.3 调试中遇到的三个真问题

| 现象 | 根因 | 修复 |
|---|---|---|
| 真实调用返回 HTTP 401 | `.env` 里同一个 `DEEPSEEK_API_KEY` 出现两次，旧 loader 先到先得，用了过期的那条 | `load_env` 改为文件内后出现的值覆盖先出现的值；真实进程环境仍然优先（不覆盖已有变量） |
| 输出在「组合」段中间截断，缺两个标题 | `max_tokens=1800` 不够写完整份中文报告 | 提到 4096，并在 prompt 里限制 900 汉字、不要逐条罗列 |
| 报告因 `300` 不合格 | `hs300_buyhold` 是策略名，不是数字声明 | 把策略名/基准名加入 `ignore_terms` |

另外发现通用 95% 数字门禁会放过 1 个假数字和多余精度，于是新增 `strict_untraceable`，报告层要求 100%。

### 6.4 云端实测

2026-11-06 在服务器容器内实测。先测无 key 的降级路径，再在 `.env` 配置 `DEEPSEEK_API_KEY` 后测真实调用：

```bash
# 无 key（或 --no-llm）
docker compose run --rm app python -m finagent.cli report --date 2026-11-05
# Mode: template / Gate PASS / Citations 51/51 / Numbers 51 checked, 0 untraceable
# Fallback: DEEPSEEK_API_KEY not configured

# 配置 key 后
docker compose run --rm app python -m finagent.cli report --date 2026-11-05
# Mode: llm (model deepseek-chat, 1 attempt(s)) / Gate PASS
# Citations 75/75 valid / Numbers 77 checked, 0 untraceable
```

两次输出与本机同口径：同一份证据表、同一套门禁，云端只多了网络调用。配置 key 只需编辑服务器 `.env` 并 `chmod 600`，不必重建镜像；key 只出现在请求头，不进入镜像、日志或报告 JSON。若复制了 `.env` 里过期的那条 key，会得到 `HTTP 401` 并回退模板——本轮就遇到过一次，用指纹（长度 + SHA-256 前缀）比对定位，没有打印 key 本身。

---

## 7. 代码地图

| 文件 | 职责 |
|---|---|
| `finagent/agent/evidence.py` | 读五类产物、生成 `Evidence` 表、缺失记录、标识符掩码列表 |
| `finagent/agent/llm.py` | `LLMConfig`、DeepSeek OpenAI-compatible 客户端（`requests`，无新依赖），key 不落日志 |
| `finagent/agent/prompts.py` | system / user / repair 提示词，以及五段结构、必需词、禁用词、最少引用数 |
| `finagent/agent/template.py` | 确定性回退报告，所有数字经证据 ID 读取 |
| `finagent/agent/report.py` | 生成流程、重试、严格门禁、写 `.md` / `.json` |
| `finagent/evals/metrics.py` | 新增 `DATE_RE`、`ignore_values` / `ignore_terms`、`min_citations`、`strict_untraceable` |
| `finagent/integrations/feishu.py` | `load_env` 修正重复键语义（后出现的值生效） |
| `finagent/cli.py` | `report --date --no-llm --model --out --json` |

测试：

- `tests/test_agent_report.py`（10）：证据唯一性、缺件报错、模板过门禁、仅 signals 也能出报告、LLM 通过、假数字重试后回退、无 key 回退、调用失败回退、多写精度被拒、key 不落盘。
- `tests/test_agent_llm.py`（6）：请求体、非 200、空响应、无 key、环境变量读取、重复键语义。
- `tests/test_evals_metrics.py` 新增日期/标识符与 `min_citations` 两个断言。

阅读顺序：`evidence.py` → `prompts.py` → `report.py` → `template.py` → `llm.py`。

---

## 8. 学习笔记

### 8.1 证据表是信任边界

不要给 LLM 原始 DataFrame，也不要给它「自己去算」的机会。证据表把「能说什么数字」变成一个闭集；prompt 只是把闭集排版，门禁只是检查正文没有越界。闭集越小，越容易审计。

### 8.2 为什么百分比在证据层就换算

如果证据值是 0.1478，LLM 很可能在正文写 0.15%，或者 14.78 不带 %。让证据值直接等于正文要写的数（14.78，单位 %），比较逻辑就只有一种。代价是原始小数在证据层丢失——需要原始值时去读 JSON，而不是从报告反推。

### 8.3 95% 可追溯为什么不够

比例门禁有三个漏洞：数字越多，一个假数字越容易被稀释；1% 相对误差会放过整数级错误（49 vs 48 的误差是 1，恰好落在 `max(1, |a|)` 的容差里）；多写精度看起来更专业，实际上是在编造分辨率。报告层的规则必须是「每个都过」，不是「大部分过」。

### 8.4 标识符掩码要精确

不能简单地「忽略所有六位数」，否则一个真实的六位数金额也会被放过；也不能忽略所有含数字的词，否则 `momentum_20` 的 20 会被误伤。正确做法是：先从产物里收集已知标识符（代码、产品名、因子名、策略名），再整体替换。新增一类产物时，记得把它的名字加进 `ignore_terms`。

### 8.5 模板不是降级玩具

模板和 LLM 走同一套门禁，意味着模板是**可执行的规格说明**：它告诉你一份合格报告最少需要哪些句子、哪些引用、哪些限制。LLM 只是把同样的骨架写得更自然。没有模板，门禁很容易变成「LLM 说什么就检查什么」；有了模板，门禁才有稳定的正例。

### 8.6 重试一次的经济学

第一次失败通常是结构性问题（截断、漏标题、多写精度），repair prompt 把失败原因说清楚就够。第二次还失败，说明模型在当前证据/长度下不稳定；继续重试只会增加延迟和成本，还会让「今天有没有报告」变成随机事件。回退模板是确定性的。

### 8.7 日期、年份、代码都不是声明

`2026-11-05` 不是「2026 这个数字」；`沪深300ETF` 不是「300 这个预测」；`momentum_20` 不是「20 这个收益」。抽取数字前先做标识符和日期清洗，是数字门禁的第一道工程问题，不是统计问题。

### 8.8 prompt 指纹与可复现性

`prompt_sha256` 让人能回答「这份报告是用哪版提示词生成的」。模型本身有随机性，但提示词、证据、门禁是确定的；出问题时先比对 hash 和 evidence，再怀疑模型。

### 8.9 报告不改变信号

Phase 6 是只读层：它读 `data/signals`、`data/portfolio`、`data/quality`，写 `data/reports`。它不追加账本、不改权重、不改 `validated`。这样报告出问题不会污染研究链路；反过来，信号链路也不需要知道报告是否存在。

### 8.10 成本与延迟

一次报告约 100 条证据、几千 token 输入、一两千 token 输出；本机一次调用在数十秒量级。它适合按需运行或收盘后一次，不适合放进高频循环。没有 key 时零成本、零网络，适合服务器默认路径。

---

## 9. 常见错误

| 错误 | 现象 | 处理 |
|---|---|---|
| 证据值没取整 | LLM 抄出很长的小数，严格门禁判「多余精度」 | 在 `build_evidence` 里统一 `_num/_pct` |
| 新增产物没加标识符 | 报告因产品名/策略名里的数字被拒 | 把名字加入 `ignore_terms` |
| 门禁失败就调低阈值 | 假数字被放过 | 修证据或修掩码；报告层保持 100% |
| 没设 `max_tokens` | 报告在中间截断，缺标题 | 4096，并在 prompt 限制长度 |
| 用 `.env` 里的旧 key | HTTP 401 | 修正重复键语义，或只保留一条 |
| 把模板当「兜底随便写」 | 模板自己过不了门禁 | 模板所有数字必须经证据 ID |
| 在日志里打印请求头 | key 泄露 | 只记录状态码和异常类型 |

---

## 10. 练习

1. 给证据表加一条「组合换手率」，要求它在模板和 LLM 报告里都能被引用，并补一个门禁测试。
2. 把 `MIN_CITATIONS` 从 10 提到 20，观察模板是否仍然通过；如果失败，说明模板的哪些句子缺引用。
3. 写一个 fake client，第一次返回缺 `## 证伪条件` 的文本，第二次返回完整文本，验证 `attempts=2` 且 `mode=llm`。
4. 构造一份报告，把证据值 14.78 写成 15%（1 位小数）。严格门禁应该通过还是不通过？先判断，再运行。
5. 给 `strict_untraceable` 加一个反例：证据 100，正文写 100.0；解释为什么它应该通过。
6. 在服务器上不配置 key 跑一次 `report`，检查 JSON 的 `fallback_reason` 和 `checks`。
7. 如果让 LLM 写「建议买入 510300」，哪几条门禁会拦住它？分别写出失败信息。

---

## 11. 下一步

Phase 6 完成后，报告链路具备「数字可追溯 + 结构可检查 + 失败可回退」。Phase 7 已按以下方向落地，见 [`phase7_risk_compliance.md`](phase7_risk_compliance.md)：

- 组合层面的硬约束检查（行业/单标的/流动性/回撤预算），失败时阻止报告给出「正常」结论；
- 报告中的风险披露与合规词表，和 Phase 6 的禁用词合并成一份配置；
- 把 `validated=false` 的升级条件写成机器可读的门槛（结算样本数、命中率区间、成本后超额），而不是人工判断。

在账本攒够结算样本之前，Phase 6 的报告仍然只是研究记录，不是策略验证。
