# Phase 1–4 学习笔记

配套 [`docs/phase1_4_eval.md`](phase1_4_eval.md)（验收与数字）阅读。那篇回答「做到了没有、值多少钱」；这篇回答「为什么这样做、坑在哪、下次能不能照抄」。

> 阅读指引：先读 §0 一张表，再按 Phase 顺序读 §1–§4；§5 是跨阶段的方法论，§6 是代码地图，赶时间可以直接从这里开始按顺序看代码。

## 0. 四个阶段各解决一个问题

| Phase | 解决的问题 | 一句话结论 | 留下的资产 |
|---|---|---|---|
| 1 数据层 | 数字从哪来、可不可信 | 50 只 ETF、111 个数据集、111/111 校验和一致，缺口只有登记过的 3 个 | 缓存 + manifest + 快照血缘 + 质量报告 |
| 2 因子内核 | 因子测的是不是自己以为的东西 | 名义 50 只，实际只有 **2.64 个独立押注**；类别中性后 9 个检验 **0 个显著** | 可逐位复现的因子面板 + 中性 IC / BH-FDR / DSR |
| 3 组合与信号 | 研究结论怎么变成能执行的约束 | 49 只持仓、约束全部满足；组合波动 14.78% vs 加权 20.79% | 政策预算 + 逆波动 + 有界倾斜 + 可结算的信号与账本 |
| 4 回测 | 这套东西到底值不值钱 | 22 项硬检查全过；**纯因子 Top-10 在真实成本下是负价值** | 按股数记账的引擎 + PBO/DSR/CPCV + 净成本增量 |

一句话串起来：**Phase 1 让数字可信，Phase 2 让测量可信，Phase 3 让结论可执行，Phase 4 让结论可证伪。** 顺序不能换——如果先写因子再补数据层，前面所有结论都要重做。

---

## 1. Phase 1：先让数字可信

### 1.1 数据层要回答的四个问题

| 问题 | 本项目的答案 | 代码 |
|---|---|---|
| 这个数从哪来？ | 每个数据集/key 一个 parquet + manifest（来源、行数、日期范围、抓取时间、checksum） | `data/cache.py` 的 `ParquetCache` / `CacheManifest` |
| 数据坏了怎么办？ | manifest 校验和；快照对每个数据集文件再算一次哈希，`snapshot --id` 可整体验证 | `data/lineage.py` 的 `SnapshotStore` |
| 源挂了怎么办？ | Provider 按路径 fallback（东财 → 同花顺 → 新浪），每次记录实际用的来源 | `data/provider.py`、`data/akshare_provider.py` |
| 缺口怎么处理？ | 按 `kind=coverage / error` 分类；已知缺口在 `configs/catalog.yaml` 里登记 `available: false`，不伪造 | `data/quality.py`、`data/catalog.py` |

### 1.2 四个容易踩的坑

1. **前向填充 / 静默补全**：看起来数据完整，实际是在编数字。本项目宁可留 `NaN + coverage`，也不补。
2. **没有 checksum 的缓存**：文件写一半、版本升级换了字段，只有校验和能发现。
3. **用统计期当可得日**：宏观数据必须按 `available_at` 过滤——PMI +1 天、CPI/PPI +10 天、M2 +15 天、LPR 当日。用「几月数据」当「几月可得」是最常见的前视。
4. **用今天的池子回测昨天**：ETF 池是当前存续池，有存续偏差。本项目每月归档 `universe.yaml`，并在所有结论旁声明这一点；2023 年初只有 39 只有完整数据，中途上市的新 ETF 只在上市后进入横截面。

### 1.3 学习点

- 数据层的第一职责不是「把数据拿全」，而是**可证伪**：每个数能追到一个文件、一个抓取时间、一个来源。
- 缺口要被记录成「已知缺口」，而不是被空值、0 或前值悄悄代替。评测里「缺口恰好是已登记的 3 个」是一条硬检查，就是防止缺口悄悄变多。
- **`slice_as_of` 只负责截断，不负责断言**。PIT 断言由调用方（回测、因子构建）另行执行——一个函数不要同时做截断和保证，否则 docstring 和实际行为很容易漂移（本项目就修过这个：docstring 说会 raise，实际静默丢弃）。

---

## 2. Phase 2：先测准，再谈预测

### 2.1 测量口径的六个决定

| 决定 | 写法 | 如果反过来会怎样 |
|---|---|---|
| 因子值保持原始方向 | `momentum_20` 就是涨幅，`direction` 只在解读时用 | 方向写反但测试仍通过，回测里再翻一次就双重取反 |
| IC 用每日截面 Spearman | `cross_sectional_ic` | Pearson 会被极端值主导 |
| 前向收益从 T+1 起算 | `P(t+1+h)/P(t+1)-1` | 用 `P(t+h)/P(t)` 等于假设 T 日收盘就能成交，前视 |
| 重叠收益用 Newey-West | 滞后 `max(h-1, 4*(n/100)^(2/9))` | t 值虚高，20 日 horizon 尤其严重 |
| 多重检验用 BH-FDR | q=0.10，一族 9 个检验 | 3 个因子 × 3 个 horizon 里挑最好的报 = 数据窥探 |
| 主指标是类别中性 IC | `neutralize_cs(zscore_cs(winsorize_cs(...)))` | 「哪个类别涨得好」会被当成「类别内选股能力」 |

### 2.2 为什么必须类别中性

这个池子里，第一层差异（宽基 vs 行业 vs 黄金 vs 债券）远大于第二层差异（同类别里哪只 ETF 好）。原始 IC 里唯一 p<0.05 的检验是 `volatility_20 h=1`（低波赢，p=0.032）；减去当日类别均值后它**变号**（+0.024 → -0.011，t=-1.07）。也就是说，那点「低波赢」来自样本期债券/商品表现好，不是低波选股。

学习点：**一个因子可以「有效」但完全不可交易**——它有效是因为它其实在选类别。中性化是最便宜的照妖镜。

### 2.3 有效广度：比 IC 更重要的上限

```text
n_eff = N / (1 + (N − 1) × ρ)
IR ≈ IC_N × sqrt(n_eff × 252 / h)
```

当前 50 只 ETF 的日收益平均相关 ρ=0.3655：

- `n_eff = 2.64`，即**名义 50 个截面样本，统计上只有 2.6 个独立押注**
- 中性 IC 最好的 momentum_20 h=1，折算 IR 上限 **0.34**（零成本、每日全截面下注）
- 实际 `top_10` 换手 25.5x/年、成本 4.01%/年——上限还没摸到，成本先把收益吃光

学习点：横截面因子研究里，「标的数量」是幻觉，「独立押注数」才是样本量。加 20 只同涨同跌的 ETF 不会让 IC 更可信，只会让 t 值更假。要提升因子，先提升广度（更多不相关资产、更长历史），或者把截面选股挪到时序/配置层。

### 2.4 分年 IC：不稳定是结论，不是噪音

| 因子 | horizon | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| momentum_20 | 20 | +0.002 | -0.004 | +0.074 | +0.037 |
| reversal_5 | 20 | -0.032 | +0.018 | **-0.070** | -0.027 |
| volatility_20 | 20 | **+0.170** | +0.093 | **-0.157** | +0.062 |

- `volatility_20` h=20 从 +0.17 翻到 -0.16；这不是「参数没调好」，是样本内就不稳。
- `reversal_5` 的 `direction=-1`，但 IC 在 5–20 日尺度上为正——说明那段时间它是动量而非反转。**命名和现实不符**，必须在报告里写明，否则解读会错。

学习点：按单年 IC 挑因子 = 拟合噪音。要看的是「同一符号能维持几年」，而不是「哪一年最高」。

---

## 3. Phase 3：把研究变成可执行的约束

### 3.1 组合：不用优化器是刻意的

结构是四层，每层都能一句话解释：

1. **类别预算**固定：宽基 35 / 行业 25 / 跨境 15 / 主题 10 / 债券 10 / 商品 5
2. **类内逆波动**分配（`inverse_vol_weights`）
3. **因子倾斜**只给 `[0.5, 1.5]` 的乘数（`tilt_multipliers`）
4. **硬约束**：单标的 ≤12%，类别上限取 `universe.py` 的护栏值

协方差用 Ledoit-Wolf 收缩（`portfolio/covariance.py`），但**不用它做均值-方差优化**。原因：

- 只有 2.64 个独立押注，均值-方差会把估计误差放大成极端权重
- 优化器输出的权重无法用一句话解释，也没法审计
- 先验预算如果被「算出来的」权重污染，回测里的配置优势就说不清来自设计还是数据

数字：2026-11-05 目标权重 49 只持仓、权重和 1.000001、最大 7.91%、类别暴露与预算最大偏差 0.0016、组合波动 14.78% vs 加权 20.79%（分散化 1.41x）。

学习点：**约束不是优化的敌人，是小样本下的正则化。** 预算、上限、倾斜区间都是先验；先验越简单，越容易在样本外活下来。

### 3.2 信号：置信度不是概率

- `composite = mean(z_cs × direction)`——z 分数的均值，量纲是标准差
- `confidence = |加权和| / 加权绝对值和`——**同向度**，不是上涨概率
- 每个类别最多 3 条信号，避免整张表被同一个风险桶占满
- 每条信号必须带**可机器校验的失效条件**：得分翻向、主因子翻向、持有到期（`InvalidationRule`）
- 全部 `validated=false`

为什么失效条件比得分重要：没有它，信号无法结算、无法统计命中率、也无法在事后判断「错在哪」。**先定义怎么算错，才谈得上算对。**

### 3.3 账本：结算口径决定学到什么

- 只追加不改写；重复 append 不重复写（有测试）
- 结算基准是**等权全池**，不是绝对收益——普涨行情里的多头不算本事
- 15 条预测、0 条结算；首条结算约 2026-12-04（20 个交易日）
- 要让命中率 95% 区间收窄到 ±5%，约需 **385 条独立结算**（±10% 需 97 条）；20 日重叠收益会高估有效样本数，实际日历时间更长

学习点：账本是「让模型接受审判」的机制。它的价值不在前 20 条，而在于**你愿不愿意在事前写下可证伪的预测**。

---

## 4. Phase 4：回测的第一价值是证伪

### 4.1 引擎按股数记账

`backtest/engine.py` 不按权重算术推进，而是按**股数**：

- T 日收盘出信号，**T+1 成交**（默认收盘价，`--exec-price open` 可切开盘）
- 停牌（价格缺失或成交量为 0）不成交；涨停不买、跌停不卖
- 未成交的权重留在原地，等下次再平衡
- 先卖后买；现金不足以支付买入及成本时按比例缩量
- 单边成本 = 佣金 2bp + 滑点 5bp（ETF 免印花税），`--cost-bps` 可覆盖
- 换手率记单边：`成交额 / 2 / 前一日净值`

失败模式对照：

| 常见写法 | 后果 |
|---|---|
| 按目标权重直接算收益 | 成交不了的单子也「生效」了，回测凭空变好 |
| 用 T 日收盘价成交 | 前视（信号和成交用同一个价） |
| 忽略涨跌停 / 停牌 | 小盘、行业 ETF 的回测会系统性偏乐观 |
| 成本只算佣金 | ETF 的真实成本大头是点差与冲击（5–20bp） |

### 4.2 过拟合诊断：三个工具各回答一个问题

| 工具 | 问题 | 本项目的数 |
|---|---|---|
| PBO（CSCV） | 样本内最优的策略，样本外还成立吗？ | **86.0%**（12 块 × 77 日，924 组） |
| DSR | 在试过 N 个方案后，这个夏普有多大概率是真的？ | 0.485–0.546（n_trials=4，乐观） |
| CPCV | 最差的路径有多痛？ | 5% 分位夏普 -0.42 ~ -0.82，正收益折 75% |

- PBO 在纯噪音下本项目口径约 50–70%，86% 意味着四个变体之间**没有真优劣**。
- 窗口缩到 2025-11-05，PBO 降到 59.5%——**诊断本身对窗口敏感**，不要拿单次 PBO 当真值。

### 4.3 净成本增量：评价策略的主指标

「策略赚了多少」不如「同一成本档下比池内什么都不做多赚多少」：

| 策略 | 0bp | 7bp | 20bp |
|---|---|---|---|
| `policy_no_tilt` | +0.55 | +0.47 | +0.33 |
| `policy_tilt` | +0.51 | +0.34 | +0.03 |
| `top_10` | **+2.25** | **-1.52** | **-8.15** |

`top_10` 的符号在 0bp 与 7bp 之间翻转。盈亏平衡成本 **3.2bp/边**，而 ETF 真实单边成本通常 5–20bp——**结构上不可达**。

学习点：

- **任何只报 0 成本结果的回测，都会把负价值路径说成 alpha。**
- 净成本增量把「策略好坏」翻译成「相对基线多赚多少」，这才是可决策的数字。
- 政策组合的优势在 20bp 下仍有 +0.33pp——它靠配置和低换手，对成本不敏感，这才是它能用的原因。

### 4.4 回测真正证伪了什么

- 纯因子 Top-10：负价值（成本吃光超额）
- 因子倾斜：对结果影响 ±0.5pp 内，成本 +0.10%/年——**可以留作解释层，不能当 alpha**
- 「策略有效」这个说法本身：PBO 86% + DSR 0.42 + 中性 IC 0/9，三个独立角度指向同一结论

学习点：一个诚实的回测，最常见的产出是「这条路不行」。它的价值在于**帮你省下继续投入的时间**，而不是给你一个漂亮的净值曲线。

---

## 5. 贯穿四个阶段的东西

### 5.1 PIT 是一条链，不是一处检查

- 采集：宏观按 `available_at`，不用统计期
- 因子：只用 `as_of` 之前的行，`assert_pit`；2026-08-06 截断重算，144,406 个共享值最大差 0
- 回测：只读 `as_of` 之前的数据；截到 2025-11-05 重跑，687 个共享日 NAV 逐位一致
- 产物：以 `as_of` 命名；非交易日回退并在 stderr 说明；缓存里没有当天数据就 exit 1，不用昨天的数据生成标着今天的文件

### 5.2 确定性：同输入必须同输出

- 因子面板重算 153,256 行，与落盘文件逐位一致（最大差值 0）
- 评测 JSON 云端与本地逐字段一致（只有路径、快照 id、生成时间不同）
- 数字由代码算、叙事由人写；评测报告里的每个数都能在 JSON 里找到

### 5.3 先测量，再扩展

- Phase 2 的结论是否定的，但它**先于**任何「加因子」的动作——否则后面加的每一个因子都建立在错误的测量上
- 资金流因子（Phase 5）沿用了同一条规则：60 个快照 + 中性 IC 通过之前不进 composite
- 新因子的默认状态是「观察」，不是「启用」

### 5.4 文档与代码漂移是 bug

本次评测修掉的四项里有两项是文档/注释问题：

- `slice_as_of` docstring 说未来行会 raise，实际静默丢弃
- README/runbook 说云端「不含回测」，实际已部署

另外两项是真实 bug：`collect` 质量报告写在快照之前导致 `snapshot_id` 恒为 `null`；`diversification` 检查把 `n_eff` 当波动比打印。

学习点：**真实数据验收的第一个产出往往不是新功能，而是「文档说的和代码做的不一样」。** 这类问题合成数据测试发现不了。

### 5.5 每个结论都要带偏差声明

存续偏差、样本内预算、基准公平性、窗口只覆盖一轮行情（2023-01 至 2026-11：A 股弱、黄金强、海外强）——这些不是免责声明，是结论的一部分。没有它们，8.53% 会被读成「策略有效」。

---

## 6. 代码地图

| 文件 | 职责 | 关键函数 |
|---|---|---|
| `finagent/data/cache.py` | Parquet 缓存与 manifest | `ParquetCache`、`CacheManifest`、`checksum` |
| `finagent/data/provider.py`、`akshare_provider.py` | 数据源与 fallback | Provider 接口、路径降级 |
| `finagent/data/collect.py` | 采集编排 | `collect`、`CollectResult` |
| `finagent/data/quality.py` | 质量报告 | `check_frame`、`check_freshness`、`merge_reports` |
| `finagent/data/lineage.py` | 快照血缘 | `SnapshotStore`、`Snapshot` |
| `finagent/data/panel.py` | 宽表 / PIT 工具 | `slice_as_of`、`long_to_wide`、`forward_returns` |
| `finagent/data/health.py` | 每日健康检查 | `check_health` |
| `finagent/factors/price.py` | 三个原始因子 | `momentum`、`reversal`、`volatility` |
| `finagent/factors/transforms.py` | 截面变换 | `winsorize_cs`、`zscore_cs`、`neutralize_cs` |
| `finagent/factors/build.py` | 因子面板 | `build_factor_panel`、`assert_pit` |
| `finagent/research/ic.py` | IC 估计 | `cross_sectional_ic`、`ic_summary` |
| `finagent/research/stats.py` | 统计工具 | `newey_west_tstat`、`bh_fdr`、`deflated_sharpe` |
| `finagent/research/report.py` | 因子报告 | `evaluate`、`run_factor_report` |
| `finagent/portfolio/policy.py` | 预算与护栏 | `PortfolioPolicy`、`load_policy` |
| `finagent/portfolio/covariance.py` | 协方差 | `ledoit_wolf`、`portfolio_vol` |
| `finagent/portfolio/construct.py` | 目标权重 | `inverse_vol_weights`、`tilt_multipliers`、`target_weights` |
| `finagent/signals/score.py` | 合成得分 | `composite_scores`、`score_row` |
| `finagent/signals/build.py` | 结构化信号 | `build_signals`、`_invalidation` |
| `finagent/signals/models.py` | 信号模型 | `QuantSignal`、`Evidence`、`InvalidationRule` |
| `finagent/signals/pipeline.py` | 信号流水线 | `run_signal_pipeline`（Phase 5 在此接入新闻叠加） |
| `finagent/predictions/ledger.py` | 预测账本 | `PredictionLedger`、`record_settlement` |
| `finagent/backtest/engine.py` | 回测引擎 | `run_backtest`、`BacktestConfig`、`Strategy` |
| `finagent/backtest/costs.py` | 成本模型 | `CostModel`、`cost_from_bps` |
| `finagent/backtest/strategies.py` | 对照策略 | `PolicyStrategy`、`EqualWeightStrategy`、`TopNStrategy` |
| `finagent/backtest/overfitting.py` | 过拟合诊断 | `cpcv_splits`、`probability_of_backtest_overfitting`、`dsr_table` |
| `finagent/evaluation/checks.py` | 真实数据验收 | `check_data_layer` … `check_pit_rerun` |
| `finagent/evaluation/benchmarks.py` | 基准 | `run_benchmarks`、`pick_bond_etf` |
| `finagent/evaluation/value.py` | 价值翻译 | `net_increment_by_cost`、`effective_breadth`、`expected_ir` |
| `scripts/phase_eval.py` | 评测入口 | 只读缓存，写 `data/quality/` |

**建议阅读顺序**（按依赖关系，不按阶段）：

1. `data/cache.py` 的 `ParquetCache.read/write` —— 先看数据怎么落地
2. `data/panel.py` 的 `slice_as_of` / `forward_returns` —— PIT 与前向收益的口径
3. `factors/transforms.py` 的 `neutralize_cs` —— 三行代码，整套测量的核心
4. `research/ic.py` + `research/stats.py` —— IC、BH-FDR、Newey-West、DSR
5. `portfolio/construct.py` 的 `target_weights` —— 约束怎么落地
6. `signals/build.py` 的 `_invalidation` —— 信号如何可结算
7. `backtest/engine.py` 的 `run_backtest` —— 股数记账与撮合
8. `backtest/overfitting.py` 的 `probability_of_backtest_overfitting` —— 诊断
9. `evaluation/value.py` 的 `net_increment_by_cost` —— 最后看怎么评价

---

## 7. 常见错误清单（跨阶段）

- 用「数据看起来完整」代替「数据可验证」；用前值填补缺失
- 用统计期当可得日（宏观、财报、估值都是高发区）
- 名义样本数当有效样本数；50 只 ETF 当成 50 个独立样本
- 先看原始 IC，再决定要不要中性化（顺序反了会自我说服）
- 按单年 IC 或单次 PBO 调参数
- 用均值-方差优化器处理 2.64 个独立押注
- 把「置信度」写成概率
- 信号没有可校验的失效条件
- 回测按权重算术成交、用当日收盘成交、忽略停牌与涨跌停
- 只报 0 成本结果，不做成本敏感性；用绝对收益而不是净成本增量评价
- 结论不带偏差声明（存续偏差、样本内、窗口）

---

## 8. 可以自己动手的练习

1. **数据层**：删掉一只 ETF 的 `manifest.json`，跑 `data-check`，看错误从哪一层报出来；再跑 `snapshot --id`，看校验和是否覆盖到这个缺口。
2. **PIT**：把 `factor-report` 的 `--date` 改到 2025-06-30，比较该日面板与 2026-11-05 面板中同一天的值，应该逐位一致。思考：如果实现里有一处用了全样本均值，会在哪里露馅？
3. **中性化**：用原始 IC 与中性 IC 各跑一次报告，找出符号翻转的检验（提示：`volatility_20 h=1`），解释为什么。
4. **有效广度**：构造 50 条两两相关 0.3655 的模拟收益，用 `effective_breadth` 验证 n_eff≈2.64；再把相关降到 0.1，看 IR 上限怎么变。
5. **成本**：把 `top_10` 的成本从 7bp 改到 20bp，用 `net_increment_by_cost` 看符号翻转；再找一个「0 成本为正、7bp 为负」的策略解释它为什么不值得做。
6. **前视**：把回测改成 T 日收盘成交，比较 CAGR 变化，并说明为什么这个更高的数字不能用。
7. **可解释性**：给 `target_weights` 加一条「换手上限 5%/日」的约束，重跑回测，看政策组合的成本与净值如何变化。
