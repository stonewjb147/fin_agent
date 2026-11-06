# finagent — A股 ETF 多因子投研助手

把「市场信息 / 基本面 / 资金流」归集起来，形成可复现的多因子分析、结构化信号和研究报告。**人做最终决策，系统不接实盘。**

核心原则：**数字由代码计算，叙事由 LLM 撰写**。因子、IC、回测、组合权重全部走 pandas/numpy；LLM 只解释、对比、写矛盾与证伪条件。

## 当前进度

| 阶段 | 状态 |
|---|---|
| Phase 0 工程骨架（包结构 / CLI / pytest / eval smoke / CI gate） | 完成 |
| Phase 1 真实数据层（Parquet 缓存 / manifest / 快照血缘 / 质量校验 / 健康检查） | 完成 |
| Phase 2 因子内核（动量 / 反转 / 波动 → IC/ICIR / 多重检验） | 完成 |
| Phase 3 组合构建 + 结构化信号 + 预测账本 | 完成 |
| Phase 4 真实回测（T+1 / 成本 / CPCV / DSR / PBO） | 完成 |
| Phase 1–4 评测与价值记分卡（真实数据验收 + 基准对比 + 成本敏感性） | 完成，见 [`docs/phase1_4_eval.md`](docs/phase1_4_eval.md) |
| Phase 5 资金流 + 新闻叠加（缺源降级、有界可解释） | 完成，数据受限，见 [`docs/phase5_flows_news.md`](docs/phase5_flows_news.md)（§5 学习笔记） |
| Phase 6 LLM 报告与评测、Phase 7 风控合规、Phase 8~10 成长闭环 | 计划中 |

## 安装

```bash
conda activate fin_agent
pip install -e .
pip install ruff            # 开发用
```

数据默认落在 `data/`（可用 `FINAGENT_DATA_DIR` 覆盖）。

## 常用命令

```bash
# 取数：Parquet 缓存 + 质量报告 + 血缘快照
python -m finagent.cli collect --start 2022-01-01 --end 2026-11-05

# 新鲜度 / 空值 / 覆盖检查（写 data/quality/health_*.json）
python -m finagent.cli data-check

# 查看 / 校验快照 checksum
python -m finagent.cli snapshot --id snap-20261105-908f0422

# 因子报告：只读缓存，产出 data/factors/<date>.parquet + data/quality/factor_report_<date>.json
python -m finagent.cli factor-report --date 2026-11-05 --horizons 1,5,20

# 结构化信号：写入 data/signals/<date>.json，并追加到预测账本
python -m finagent.cli signals --date 2026-11-05 --horizon 20
python -m finagent.cli signals --date 2026-11-05 --news data/news/2026-11-05.json   # 可选新闻叠加

# Phase 5：资金流 / 份额 / 折溢价 / 新闻源的状态与截面（缺源会写明原因）
python -m finagent.cli flows --date 2026-11-05
python -m finagent.cli flows --date 2026-11-05 --json

# 目标权重：类别预算 + 逆波动 + 有界因子倾斜
python -m finagent.cli portfolio --date 2026-11-05

# 预测账本：结算到期预测并输出命中率 / 校准
python -m finagent.cli ledger --date 2026-11-05 --settle

# 真实回测：四个对照策略 + 成本 + CPCV / PBO / DSR
python -m finagent.cli backtest --start 2023-01-01 --end 2026-11-05
python -m finagent.cli backtest --start 2023-01-01 --cost-bps 0      # 无摩擦对照
python -m finagent.cli backtest --start 2023-01-01 --exec-price open --rebalance-days 21

# Phase 1-4 评测：真实数据验收 + 基准（510300 / 60-40 / 池内等权）+ 成本敏感性 + 类别中性 IC 与有效广度
python scripts/phase_eval.py --start 2023-01-01 --end 2026-11-05
python scripts/phase_eval.py --start 2023-01-01 --end 2026-11-05 --strict   # 硬检查失败即 exit 1

# 每日任务（cron 入口）与飞书告警
python scripts/collect_daily.py
python scripts/health_check.py --alert feishu

# 离线质量门禁：ruff + pytest + eval smoke
make check
```

## 部署到腾讯云

每日采集可跑在腾讯云 Lighthouse（4C8G / Ubuntu 22.04）上，Docker + compose，主机 cron 在收盘后触发：

```bash
docker compose build
docker compose run --rm app python scripts/collect_daily.py
docker compose run --rm app python scripts/health_check.py --alert feishu
```

完整步骤（购买、防火墙、SSH 加固、时区、Docker、首次回补、cron、备份、回滚）见 [`deploy/tencent-lighthouse.md`](deploy/tencent-lighthouse.md)。云上已部署 Phase 1–5 代码（采集、健康检查、因子报告、信号与预测账本、回测与评测、资金流/新闻叠加），LLM 报告尚未做。cron 五条：18:30 采集、18:40 因子、18:45 信号、19:10 健康检查、周日 03:00 备份；**回测、`phase_eval.py` 与 `flows` 是按需研究命令，不进 cron**（会占满 CPU 且没有每日新增信息；行业资金流历史由 18:30 采集顺带累积）。服务器上目前没有 `data/news/` 文件，新闻叠加会自动跳过并在信号 JSON 里标注。

## 数据源现状（本机实测，2026-11-05）

- 东财 `push2*` 域名在本机不可达（系统代理已失效），因此：
  - 指数日线走 `stock_zh_index_daily_em`（push2his）
  - ETF 快照走 `fund_etf_category_sina`
  - 行业资金流走同花顺 `stock_fund_flow_industry`（只有当日截面，无历史）
  - ETF 份额走 `fund_etf_scale_sse`（仅交易日、发布有滞后）
- 所有请求带超时、重试和降级；失败时回退最近缓存并在质量报告中标注 `stale`。
- 每个数据集在 `configs/catalog.yaml` 登记字段、覆盖、频率和已知缺口（`available: false`）。

**必须记住的口径**

1. 复权用后复权（hfq），且每次全量刷新——新分红会重写历史。
2. 宏观数据按 `available_at` 过滤（PMI +1 天、CPI/PPI +10 天、M2 +15 天、LPR 当日），不能用统计期。
3. 指数估值覆盖不全（部分国证/深证指数无免费数据），缺失记为 `NaN + coverage`，不伪造。
4. ETF 池为当前存续池，存在存续偏差；`configs/universe.yaml` 每月归档一次。
5. 血缘口径：`snapshot_id` 目前由 `collect` 生成、写在 `collect_<date>.json` 与 `data/snapshots/` 下，可用 `finagent.cli snapshot --id ...` 校验 checksum。**它还没有向下游传播**——因子、组合、信号、回测的产物都以 `as_of` 命名并只读 `as_of` 之前的数据，但不记录自己消费的是哪个快照；把 `snapshot_id` 一路传下去是后续项（见 `docs/phase1_4_eval.md` §4）。回测只读 `as_of` 之前的缓存，并有截断重跑校验（`point_in_time`）。
6. 因子口径：因子值保持原始方向（`direction` 只做解读），IC 是每日截面 Spearman 秩相关；**主指标是类别中性 IC**——先对每个交易日减掉所属类别的均值（`neutralize_cs(zscore_cs(winsorize_cs(...)))`），否则「哪个类别涨得好」会冒充选股能力。原始 IC 与中性 IC 并列报告，但显著性、DSR、多空夏普、折算 IR 都以中性口径为准，两者各自做一族 BH-FDR（q=0.10）。信号 T 日收盘生成、T+1 执行，所以前向收益是 `P(t+1+h)/P(t+1)-1`；重叠收益用 Newey-West（滞后 `max(h-1, 4*(n/100)^(2/9))`）。样本的名义广度不等于有效广度：`n_eff = N / (1 + (N-1)ρ)`，当前 50 只 ETF 的日收益平均相关 0.37，只有 2.64 个独立押注；`IR ≈ IC_N × sqrt(n_eff × 252/h)` 是零成本上限，用来判断一个 IC 值不值得继续投入。
7. 信号与账本口径：合成得分 = 各因子 `z_cs × direction` 的等权均值，**置信度是同向度（|加权和| / 加权绝对值和），不是概率**；每个类别最多 3 条信号，避免整张表被同一风险桶占满；每条信号必须带可机器校验的失效条件（得分翻向、主因子翻向、持有到期）。账本只追加不改写，**结算收益相对等权全池**而不是绝对收益——普涨行情里的多头不算本事。全部信号保持 `validated=false`：Phase 4 已经给出证据，而且是**否定的**——9 个类别中性因子检验在 BH-FDR(q=0.10) 下 0 个显著（最小 q 0.642、最高 DSR 0.42），纯因子 Top-10 的盈亏平衡成本只有 3.2bp/边。改成 `true` 需要账本攒够结算样本（±5% 精度约 385 条），不是靠再跑一次回测。详见 `docs/phase1_4_eval.md`。
8. 组合口径：类别预算固定（宽基 35 / 行业 25 / 跨境 15 / 主题 10 / 债券 10 / 商品 5），类别内按逆波动分配，因子得分只做 `[0.5, 1.5]` 的有界倾斜；单标的 12% 上限，类别上限取 `data/universe.py` 的护栏值。不使用优化器，每个权重都能一句话解释。
9. 日期口径：所有产物都以 `as_of` 命名，所以 `--date` 落在非交易日会**回退到前一个交易日**并在 stderr 说明；如果那天缓存里还没有数据（例如当天收盘后采集尚未跑），`factor-report` / `signals` / `portfolio` 直接报错退出（exit 1），**绝不**用昨天的数据生成一个标着今天的文件。
10. 回测口径：引擎按**股数**记账而不是权重算术，所以成交不了的委托不会凭空生效。信号 T 日收盘生成、T+1 成交，默认用收盘价（与预测账本一致），`--exec-price open` 可切到次日开盘；单边成本 = 佣金 2bp + 滑点 5bp（ETF 免印花税），`--cost-bps` 可覆盖。停牌（价格缺失或成交量为 0）不成交；涨停不买、跌停不卖，未成交的权重留在原地等下次再平衡。先卖后买，现金不足以支付买入及其成本时按比例缩量。换手率记为单边（`成交额 / 2 / 前一日净值`），年化后再与成本对照。**读法**：PBO 是「组合内最优策略在样本外落到中位数以下」的频率，纯噪音下按本项目的 ω 口径约为 50%~70%，所以 86% 意味着四个变体之间没有真正的优劣；DSR 用显式 `n_trials`（默认只算本次跑的变体数，是乐观情形，真实试过的方案数应通过 `--trials` 传入）；CPCV 的 5% 分位夏普若显著为负，说明最差路径很痛，不能只看均值。**评价策略的主指标是「净成本增量」**：同一成本档下相对 `equal_weight` 的 CAGR 差（`net_increment_vs_equal_weight`），而不是单一成本下的绝对收益——只看 0 成本会把 `top_10` 的 +2.25pp 当成 alpha，扣 7bp 后它其实是 -1.52pp。
11. 资金流与新闻口径：每个可选数据源返回 `SourceStatus`，缺数据时**降级并写明原因**，不静默丢因子、不回退到昨天。行业资金流需要 ≥5 个 `sector_flow_rank` 快照才定义 5 日累计；份额变化需要 ≥2 个 `etf_scale_sse` 快照；折溢价需要 `etf_nav` 与同日收盘。资金流因子在攒够 60 个快照并通过类别中性 IC 检验之前**不进合成得分**。新闻只从 `data/news/<as_of>.json` 读，`published_at` 晚于当日的条目丢弃；每个 ETF 的 `news_score` 是匹配条目 sentiment 的均值，调整量 `clip(weight × news_score, ±max_abs)`（默认 0.20 / 0.30），只改最新一天，并在 `overlays.news.contributions` 里逐条给出 `composite_before / contribution / composite_after / titles`。

## 目录

```
finagent/
  data/       # 缓存、Provider、universe、panel、质量、catalog、lineage
  factors/    # FactorSpec 注册表、变换、IC 评估（Phase 2）
  research/   # 统计检验、BH / Deflated Sharpe（Phase 2）
  valuation/  # 指数估值、ERP、Gordon 合理 PE（K1）
  macro/      # 增长/通胀/流动性 regime（K1/P1）
  risk/       # 协方差、风险预算（K2/K3）
  portfolio/  # IPS/SAA/TAA/优化/再平衡（K3）
  attribution/# Brinson / 因子归因（K4）
  backtest/   # 回测引擎、成本、CPCV/PBO（Phase 4）
  evaluation/ # 真实数据验收、基准、成本敏感性、类别中性分年 IC、有效广度、评测汇总
  flows/      # 行业资金流、ETF 份额变化、折溢价（Phase 5，状态优先）
  news/       # 新闻 → 板块 → ETF 映射与有界叠加（Phase 5）
  signals/    # 结构化 QuantSignal、合成得分
  agent/      # LangGraph、报告、偏差自检（Phase 6）
  evals/      # golden set、引用/数字可追溯/格式指标
configs/      # universe / catalog / 后续 factors、ips、holdings
docs/         # 评测报告（phase1_4_eval.md、phase5_flows_news.md）
tests/        # 全部离线，不联网
scripts/      # 每日采集、健康检查、源探测、Phase 1-4 评测
```

## 评测

`evals/golden_set.jsonl` 固定 10 条问题/报告样本，覆盖 CFA 概念、研究报告、数值可追溯三类。

- `python -m finagent.evals.run_evals --smoke`：离线校验 golden set 与指标本身，CI 门禁。
- `python -m finagent.evals.run_evals --answers answers.jsonl`：给真实回答打分；引用准确率 < 90% 或数字可追溯率 < 95% 直接失败。

## 免责声明

本项目仅用于个人研究与学习，输出为研究分析而非投资建议。历史回测不代表未来收益。
