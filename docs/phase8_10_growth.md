# Phase 8–10 成长闭环：设计、实测与学习报告

> 本文是 Phase 8–10 的学习报告：先讲清楚为什么需要成长体系、三层各自怎么算，再贴本机与云端的真实输出，最后列出局限和验收清单。
> 所有数字都可以用文中的命令复现；本机的 `as_of=2026-11-05`。

## 0. 一页结论

| 问题 | 回答 |
|---|---|
| 做了什么 | 每日成长状态（Phase 8）、人工决策日志与到期价格复盘（Phase 9）、确定性周期成长报告（Phase 10），并接入每日/每周 cron |
| 为什么做 | 前七个 phase 保证「研究算得对」；8–10 回答「人有没有持续做、有没有记录理由、有没有回头看」 |
| 核心边界 | 成长分只衡量过程，不衡量收益；系统**从不生成决策**；任何自动任务都**不会修改 `validated=false`** |
| 本机实测 | `L2 证据积累期 62/100`：流程 100（7/7 工件）、证据 0（0/385 结算）、风控 70（`warn`）、数据 100 |
| 周期报告 | `data/growth/review_2026-11-05.md|json`，六条验证门槛中 2 条通过（回撤、风控不阻断），4 条未通过 |
| 新增测试 | 16 条，全量 254 passed；`ruff` 干净 |
| 云端 | 已部署 `4c63425`：容器内 254 passed、growth L2 62/100、risk `warn`、report Gate PASS |

一句话：**成长体系不回答「明天买什么」，它回答「这周你有没有把该做的做完、把做过的记下来、把记下的回头看」。**

---

## 1. 为什么需要成长体系

### 1.1 前七个 phase 留下的空白

Phase 1–7 把「算」这一层做扎实了：

- 数据有缓存、血缘、质量检查（Phase 1）；
- 因子有 IC、ICIR、多重检验（Phase 2）；
- 信号、权重、预测账本可复现（Phase 3–4）；
- 报告数字可追溯、引用可校验（Phase 6）；
- 风控独立复算、`validated=false` 有六条升级门槛（Phase 7）。

但这些能力有一个共同前提：**每天都有人把它们跑完，并且把人的判断写下来**。如果只有 cron 在跑、人只看一眼报告标题，那么：

1. 缺少工件时，报告和风控只能看到「部分事实」，而没有人知道缺了什么；
2. 决策留在脑子里，失败后无法区分「判断错了」还是「运气不好」；
3. 没有周期回看，同一个软约束会连续 warn 三个月，没人处理；
4. 最容易发生的自欺：用某几天的收益证明「体系有效」，却对样本量、回撤、阻断视而不见。

### 1.2 三个反模式

| 反模式 | 表现 | 成长体系的应对 |
|---|---|---|
| 只跑不记 | cron 每天跑，人从不看、从不写 | 流程分 + 行动清单，缺件是**高优先级**行动 |
| 只记结果不记理由 | 「我买了」，但不知道为什么、当时看到了什么 | 决策日志强制 `rationale`，且 `signal_ids` 可回链 |
| 用结果评价过程 | 赚了就是对的，亏了就是错的 | 成长分不含收益；决策复盘把「结果」与「过程」分开陈述 |

### 1.3 三条硬边界

- 不产生任何交易指令；
- 不修改信号、组合权重、风控结论；
- 不修改 `validated`，升级必须由人决定并留下理由。

---

## 2. 三层结构

```
                   ┌──────────────────────────────┐
   每日工件          │ Phase 8  每日成长状态          │
   collect / factor │ 流程 30 + 证据 30 +          │──► data/growth/growth_<date>.json
   signals/portfolio│ 风控 25 + 数据 15            │
   risk / report    └──────────────┬───────────────┘
   health                          │
                                   ▼
                   ┌──────────────────────────────┐
                   │ Phase 10 周期成长报告          │──► data/growth/review_<date>.md|json
                   │ 结论/过程/证据/决策/风险/行动/ │
                   │ 学习卡（确定性，不经 LLM）      │
                   └──────────────▲───────────────┘
                                  │
   人写 ──► data/journal/entries.jsonl ──► Phase 9 到期复盘 ──► reviews.jsonl
             （append-only，理由必填）        （只做价格对照）
```

三层是**单向**的：人写日志 → 系统做价格对照 → 成长状态汇总 → 周期报告解释。没有任何一层会反向改动上游事实。

---

## 3. Phase 8：每日成长状态

命令：

```bash
python -m finagent.cli growth --date 2026-11-05          # 终端摘要 + 写 JSON
python -m finagent.cli growth --date 2026-11-05 --json   # 附带完整 JSON
```

默认日期取最新一份 `data/signals/<date>.json` 的日期；不指定 `--out` 时写到 `data/growth/growth_<date>.json`。

### 3.1 四个维度

| 维度 | 权重 | 输入 | 算法 | 为什么这样设计 |
|---|---|---|---|---|
| 流程 process | 30% | 当日 7 个工件是否存在 | `round(100 × 存在数 / 7)` | 先保证「每天都跑完」，这是所有证据的前提 |
| 证据 evidence | 30% | 预测账本已结算条数 / 门槛 | `round(min(settled / required, 1) × 100)` | 用结算样本衡量「证据在积累」，而不是「今天猜对了」 |
| 风控 risk | 25% | `risk_<date>.json` 的 `status` | `pass=100 / warn=70 / blocked=0`；未运行=50 | 守住边界比多赚一点重要；`warn` 不该和 `pass` 同分 |
| 数据 data | 15% | 健康检查 errors / warnings | `max(0, 100 − 50×errors − 10×warnings)`；无文件=50 | 数据错了，下游全错；没有文件时给中性分，不奖励也不惩罚 |

`required` 从风控策略里读，默认 385（Phase 7 的 `min_settled_samples`）。这样成长体系和风控门槛**同源**，不会出现「成长说到 300 条就够了、风控说 385」的分裂。

总分：

```
total = round(0.30 × process + 0.30 × evidence + 0.25 × risk + 0.15 × data)
```

以本机 2026-11-05 为例：

```
process  = 100 × 7/7                = 100
evidence = min(0/385, 1) × 100      =   0
risk     = warn                     =  70
data     = 100 − 0 − 0              = 100
total    = 0.30×100 + 0.30×0 + 0.25×70 + 0.15×100
         = 30 + 0 + 17.5 + 15 = 62.5 → 62
```

> 细节：Python 的 `round(62.5)` 按「银行家舍入」得到 **62**（取偶），不是 63。这是真实实现的输出，不是笔误。分数只用于分档，1 分的差异没有意义。

### 3.2 七个工件

| id | 文件 | 缺失时的含义 |
|---|---|---|
| `collect` | `quality/collect_<date>.json` | 当天没有采集/质量记录 |
| `factor_report` | `quality/factor_report_<date>.json` | 没有因子 IC 报告 |
| `signals` | `signals/<date>.json` | 没有结构化信号与账本摘要 |
| `portfolio` | `portfolio/<date>.json` | 没有目标权重 |
| `risk` | `quality/risk_<date>.json` | 没有风控判决 |
| `report` | `reports/report_<date>.json` | 没有研究报告（含门禁结果） |
| `health` | `quality/health_<date>.json` | 没有健康检查 |

缺失不会让命令崩溃——这是刻意设计：**成长状态本身要能在「不完整的一天」运行**，否则它就没法告诉你缺了什么。

### 3.3 等级

| 分数 | 等级 | 名称 | 含义 |
|---|---|---|---|
| <40 | L0 | 流程搭建期 | 连每天跑完都还不稳定 |
| 40–59 | L1 | 习惯养成期 | 流程基本稳定，但证据或风控有缺口 |
| 60–74 | L2 | 证据积累期 | 流程完整，主要缺结算样本 |
| 75–89 | L3 | 复盘进阶期 | 有足够样本和记录，开始做周期复盘 |
| ≥90 | L4 | 稳定闭环期 | 流程、证据、风控、数据都在高位 |

等级只用于提示下一步，**不是绩效评级**，也不能跨人比较。L2 的本机状态说明「流程已经搭好，接下来只能靠时间积累结算样本」——这不是缺陷，是当前真相。

### 3.4 活动窗口与连续天数

- 窗口默认 30 个交易日，日期来自 `data/cache/trade_calendar/all.parquet`，只取 `<= as_of` 的日期，**不会包含未来**；
- 没有日历缓存时，退回到「实际产出过工件的日期」，再退回到工作日近似（注释里写明了这是最后手段）；
- **完整日**：`signals / portfolio / risk / report` 四个核心工件同时存在；
- `streak_days`：从 `as_of` 往前数，连续完整的天数，遇到第一个不完整就停。

本机 `Activity last 30 sessions: complete 1 streak 1` 说明：这套流程是 2026-11-05 才第一次完整跑通的，没有历史可吹。

### 3.5 行动清单

行动不是「建议买卖」，而是「下一个该补的工件/该看的文件」。优先级排序后最多 6 条：

| id | 优先级 | 触发条件 |
|---|---|---|
| `pipeline.missing` | high | 当日有缺失工件 |
| `risk.blocked` | high | 风控 `blocked` |
| `data.errors` | high | 健康检查有 errors |
| `risk.warn` | medium | 风控 `warn` |
| `risk.not_run` | medium | 没有风控文件 |
| `evidence.samples` | medium | 结算样本 < 门槛 |
| `data.warnings` | medium | 健康检查有 warnings |
| `report.template` | low | 报告走了确定性模板 |
| `journal.first` | low | 决策日志为空 |
| `keep.rhythm` | low | 没有任何缺口（兜底） |

排序键是 `(优先级, id)`，所以同一优先级内输出稳定，便于 diff 和测试。

### 3.6 里程碑

九个里程碑，只记录**第一次/达到阈值**，用来给长期使用一点正反馈：

`first_signal`、`first_report`、`first_risk`、`first_journal`、`first_review`、`first_settled`、`samples_100`、`samples_required`、`process_20d`。

本机 3/9：有第一条信号、第一份报告、第一次风控；还没有结算、没有决策记录。

### 3.7 本机实测输出

```text
$ python -m finagent.cli growth --date 2026-11-05
Growth for 2026-11-05  level=L2 证据积累期  score=62/100
Process 100  Evidence   0  Risk  70  Data 100
Artifacts 7/7  Risk warn  Settled 0/385  Journal 0 entries / 0 reviewed
Activity last 30 sessions: complete 1  streak 1
Next: L3 复盘进阶期 in 13 points

Actions:
  - [medium] 继续积累结算样本：0/385
    why: 在样本达到门槛前，命中率与超额都没有统计意义；不要提前修改 validated。
    cmd: python -m finagent.cli ledger --date 2026-11-05
  - [medium] 复盘软约束：concentration.n_eff
    why: 软约束不阻断，但它解释了「通过得勉强」在哪里。
    cmd: python -m finagent.cli risk --date 2026-11-05 --json
  - [low] 记录第一条决策或观察
    why: 没有记录就没有可复盘的对象；决策日志是成长体系里唯一由人填写的一层。
    cmd: python -m finagent.cli journal --date 2026-11-05 --add --action watch --rationale "今天的观察"

Milestones 3/9
```

**怎么读**：

- 流程 100 不代表「做得对」，只代表「今天该跑的 7 个东西都在」；
- 证据 0 不是 bug，是账本还没有到期预测。要诚实保留这个 0；
- 风控 70 是因为 `concentration.n_eff` 这一条软约束失败（50 只 ETF 只有 2.64 个独立押注），不是 hard 越线；
- L3 只差 13 分，但在结算样本为 0 时**无法靠流程分补上**——这正是设计想要的效果。

---

## 4. Phase 9：决策日志与到期复盘

两个 append-only 的 JSONL：

| 文件 | 内容 | 谁写 |
|---|---|---|
| `data/journal/entries.jsonl` | 一条人工决策一行，永不改写 | 人（CLI） |
| `data/journal/reviews.jsonl` | 一条到期复盘一行，写一次 | 系统（价格对照） |

### 4.1 记录一条决策

```bash
python -m finagent.cli journal --date 2026-11-05 --add \
  --symbol 510300 --action watch \
  --rationale "等回撤到 20 日线再评估" --confidence 0.6 \
  --review-days 20 --tags "观察,宽基" --signal-ids "sig-20261105-510300"
```

字段（`DECISION_FIELDS`）：

| 字段 | 说明 |
|---|---|
| `decision_id` | 默认 `dec-<date>-<symbol|portfolio>-<action>`，重复时加 `-2`、`-3`；也可用 `--id` 指定 |
| `as_of` | 决策日 |
| `scope` | 有 `--symbol` 为 `symbol`，否则 `portfolio` |
| `symbol` | ETF 代码，可为空 |
| `action` | `add / hold / trim / exit / watch / no_trade` |
| `rationale` | **必填**，去掉空白后为空直接报错 |
| `confidence` | `[0, 1]` 的判断分，不是概率 |
| `review_days` | 多少个交易日后复盘，默认 20 |
| `tags` / `signal_ids` | 自由标签、可回链到当天的信号 |
| `mode` | 默认 `research` |
| `created_at` | 写入时间（本地时区） |

**为什么强制理由**：没有理由的记录无法复盘。事后只能看到「买了/卖了」，却不知道当时依据什么，就无法判断「依据是否成立」，只能看结果——这恰好是成长体系要避免的。

**为什么 `confidence` 不是概率**：它不参与任何期望收益计算，只用于事后对照「高置信度是否真的更容易命中」。别把它读成「70% 会涨」。

### 4.2 动作的方向

```python
ACTION_DIRECTION = {"add": 1, "hold": 1, "trim": -1, "exit": -1, "watch": 0, "no_trade": 0}
```

方向只用于复盘打分：

- `add/hold` 是看多（相对基准要跑赢才算 hit）；
- `trim/exit` 是看空（相对基准跑输才算 hit）；
- `watch/no_trade` 是**观察项**，方向为 0，记为 `observed`，**不计入命中率**，也不会被算成 miss。

把「不操作」算成预测是常见的统计污染：它没有方向，凭什么算对错？

### 4.3 到期复盘

```bash
python -m finagent.cli journal --date 2026-11-05 --review
```

逻辑（`DecisionJournal.review`）：

1. 读 `entries.jsonl`，跳过 `reviews.jsonl` 里已有 `decision_id` 的（幂等，不会重复写）；
2. 只处理 `scope == "symbol"` 的记录；`portfolio` 级记录暂不自动复盘（见 §9 局限）；
3. 决策日必须是价格面板里的一个真实交易日，否则跳过；
4. `exit_pos = entry_pos + review_days`；若越界或 `exit_date > as_of`，保持 pending——**绝不偷看未来**；
5. 价格用后复权收盘（`etf_daily_hfq`），从 `data/cache/` 读取，已经把面板截断到 `as_of`；
6. 计算：

```
ret      = exit_price / entry_price − 1
excess   = ret − mean(基准内所有 ETF 同期收益)          # 等权全池
dir_excess = direction × excess
outcome  = "observed"  if direction == 0
           "unscored"  if 缺少可比基准
           "hit"       if dir_excess > 0
           "miss"      otherwise
```

**为什么基准是等权全池**：绝对收益里混着 beta。普涨时随便买都赚，不能说明判断能力。等权全池和预测账本、回测的对照口径一致，避免「换个基准就换个结论」。

**为什么只做价格对照**：复盘不做仓位、不做成本、不做择时评价，只回答「到期那天，这个方向相对全池是对的还是错的」。这是最小可证伪事实，解释权仍然在人。

### 4.4 汇总

`summary(as_of)` 输出：

| 字段 | 含义 |
|---|---|
| `n_entries` | 记录总数 |
| `n_reviewed` | 已复盘条数 |
| `n_pending` | 未到期/未复盘 |
| `n_directional_reviewed` | 有方向的已复盘条数 |
| `hit_rate_excess` | 方向性命中率（仅 directional） |
| `mean_directional_excess` | 平均方向性超额 |
| `by_action` | 按动作分组的条数、命中率、平均超额 |
| `note` | 「好的过程可能遇到坏结果」的固定提醒 |

### 4.5 本机实测

生产目录保持为空——**不造假数据**。下面的示例在临时目录里跑，验证的是机制：

```text
$ FINAGENT_DATA_DIR=/tmp/finagent-growth-cli python -m finagent.cli journal \
    --date 2024-06-03 --add --symbol 510300 --action watch --rationale "等回撤"
Recorded dec-2024-06-03-510300-watch
  date=2024-06-03  scope=symbol  action=watch
  confidence=0.5  review_days=20
  rationale=等回撤
  file=/tmp/finagent-growth-cli/journal/entries.jsonl

$ ... journal --date 2024-06-03
Decision journal  as_of=2024-06-03  entries=1  reviewed=0  pending=1
directional reviewed 0  excess hit rate n/a  mean directional excess n/a
```

生产环境：

```text
$ python -m finagent.cli journal --date 2026-11-05
Decision journal  as_of=2026-11-05  entries=0  reviewed=0  pending=0
no decisions recorded yet — use `finagent journal --add ...`
```

**怎么读**：空日志不是失败，是「还没有可复盘的对象」。成长体系里唯一需要人动手的一层就是这里；系统不会替你编一条。

---

## 5. Phase 10：周期成长报告

```bash
python -m finagent.cli growth --date 2026-11-05 --review           # 默认 30 个交易日窗口
python -m finagent.cli growth --date 2026-11-05 --review --window 60
```

产出：

- `data/growth/review_<date>.md`：人读的 Markdown；
- `data/growth/review_<date>.json`：同样内容的机器可读版（去掉 `markdown` 字段）。

### 5.1 为什么不用 LLM 写

这是刻意的：周期报告要**准确陈述缺口**。LLM 会把「0/385」写成「正在稳步积累」，把 `blocked` 写成「需关注的风险点」。Phase 6 的 LLM 报告有数字门禁与证据约束，是因为它要写叙事；Phase 10 只需要把事实摆出来，确定性渲染更可靠、可 diff、可测试。

### 5.2 六个部分

| 部分 | 内容 |
|---|---|
| 一页结论 | 等级、流程、证据、风控、决策、窗口内完整天数 |
| 过程 | 四个核心工件当日是否齐全 + 窗口内出现天数 + 连续天数 |
| 证据 | 风控 JSON 里的六条验证门槛逐条对照（实际 / 要求 / ✅❌） |
| 决策 | 记录数、已复盘、待复盘、方向性命中率、平均超额、按动作分组 |
| 风险 | `status`、策略指纹、hard/soft 失败数与失败项 |
| 下一周的行动 | 复用 Phase 8 的行动清单，带可复制命令 |
| 学习卡 | 最多 5 条确定性「教训」 |

### 5.3 学习卡的生成规则

| id | 触发 |
|---|---|
| `evidence.pending` | 结算 0 条 |
| `evidence.remaining` | 有结算但 `eligible=false`，列出还差的条件 |
| `process.gap` | 有缺失工件 |
| `risk.blocked` / `risk.warn` | 风控状态 |
| `journal.empty` / `journal.pending` | 无记录 / 有待复盘 |
| `report.template` | 报告走模板 |
| `data.errors` / `data.warnings` | 健康检查 |
| `keep.loop` | 无缺口（兜底） |

最多 5 条，避免报告变成一张没有重点的清单。

### 5.4 本机实测

```text
$ python -m finagent.cli growth --date 2026-11-05 --review
Growth review 2026-11-05  window=30 sessions
Level       : L2 证据积累期 (62/100)
Process     : 7/7 artifacts
Evidence    : 0/385 settled
Risk        : warn
Journal     : 0 entries / 0 reviewed
Complete    : 1/30 sessions  streak=1

Next actions:
  - [medium] 继续积累结算样本：0/385
  - [medium] 复盘软约束：concentration.n_eff
  - [low] 记录第一条决策或观察
```

报告正文的关键段落：

| 条件 | 实际 | 要求 | 结果 |
|---|---|---|---|
| `settled_samples` | 0 | 385 | ❌ |
| `hit_rate_excess` | None | 0.55 | ❌ |
| `mean_directional_excess` | None | > 0 | ❌ |
| `factor_significant` | 0 | 1 | ❌ |
| `drawdown_budget` | -0.180695 | -20% | ✅ |
| `risk_not_blocked` | warn | not blocked | ✅ |

`eligible=false`，`validated=false`；剩余：结算样本、命中率、平均方向超额、显著因子。

风险段：`warn`，策略指纹 `0a8b6aaace1c`，hard 失败 0，soft 失败 1，失败项 `concentration.n_eff`。

**怎么读**：

- 六条门槛里通过的两条（回撤、风控不阻断）是「没出事」，不是「有效」；
- 四条未通过里，只有「结算样本」能靠时间解决，其余三条依赖样本之后的统计结果；
- 报告不会给出「建议加仓」之类的结论——它只告诉你，离可以讨论升级还差什么。

---

## 6. 运行方式

### 6.1 命令

```bash
python -m finagent.cli growth --date 2026-11-05                 # 每日成长状态
python -m finagent.cli growth --date 2026-11-05 --review        # 周期成长报告
python -m finagent.cli journal --date 2026-11-05                # 查看决策日志摘要
python -m finagent.cli journal --date 2026-11-05 --add ...      # 记录一条决策
python -m finagent.cli journal --date 2026-11-05 --review       # 到期决策价格复盘
```

### 6.2 cron（共 11 条）

| 时间 | 任务 | 产物 |
|---|---|---|
| 周一~五 18:30 | `collect_daily.py` | 缓存 + 质量 + 快照 |
| 周一~五 18:38 | `health_check.py --alert feishu` | 健康检查 + 告警 |
| 周一~五 18:40 | `factor-report` | 因子面板 + IC 报告 |
| 周一~五 18:45 | `signals` | 信号 + 预测账本 |
| 周一~五 18:47 | `portfolio` | 目标权重 |
| 周一~五 18:48 | `risk` | 风控判决 |
| 周一~五 18:50 | `report` | LLM/模板报告 |
| 周一~五 18:55 | `growth` | `data/growth/growth_<date>.json` |
| 周一~五 19:05 | `journal --review` | `data/journal/review_<date>.json` |
| 周日 03:00 | `tar` 备份 | `backups/finagent-<date>.tgz` |
| 周日 03:30 | `growth --review --window 30` | `data/growth/review_<date>.md|json` |

顺序不是随意的：健康检查必须排在 `risk` 和 `growth` 之前（两者都读 `health_<date>.json`；文件缺失时风控只会记一条 info，当天的数据错误不会阻断），`growth` 在 `report` 之后（否则当天报告工件还不存在），`journal --review` 在 `growth` 之后（这样当天复盘结果能进下一次成长状态），备份包含 `data/growth` 与 `data/journal`（后者**不可重建**）。

### 6.3 文件清单

```text
finagent/growth/
  __init__.py     # 导出 DecisionJournal、build_*、run_*、format_*
  state.py        # Phase 8：工件、评分、等级、活动窗口、行动、里程碑
  journal.py      # Phase 9：append-only 日志、到期复盘、汇总
  review.py       # Phase 10：确定性 Markdown/JSON 报告与学习卡
  pipeline.py     # run_growth / run_growth_review / run_journal_review
tests/test_growth.py   # 16 条离线测试
```

---

## 7. 云端部署与验证

代码部署到腾讯云 Lighthouse 的 Docker 容器（`/opt/finagent`，compose 服务 `app`）。镜像在构建时把代码复制进去，所以每次发版都要重建镜像，而不是只 `git pull`。

| 步骤 | 结果 |
|---|---|
| 部署提交 | `4c63425 feat: Phase 8-10 成长闭环` |
| 镜像 | 重新构建成功，打标签 `finagent:4c63425`（与 `finagent:0.1.0` 同一个 image id） |
| 容器内测试 | **254 passed in 63.97s** |
| 每日成长状态 | `L2 62/100`、`7/7`、`0/385`、`warn`，与本地逐字一致 |
| 周期成长报告 | 写出 `growth_2026-11-05.json`、`review_2026-11-05.json`、`review_2026-11-05.md` |
| 决策日志 | `entries=0 reviewed=0 pending=0`；`journal --review` 正常处理空日志并写 `review_2026-11-05.json` |
| 风控复验 | `status=warn`，`risk-v1 (0a8b6aaace1c)`，hard 15/15、soft 10/11，`n_eff=2.64` |
| 报告复验 | `Mode llm (deepseek-chat, 1 attempt)`、`Gate PASS`、引用 95/95、数字 91 项 0 不可追溯 |
| crontab | 11 条任务（8 条 `finagent.cli` + 采集 + 健康检查 + 备份），含 18:55 growth、19:05 journal --review、周日 03:30 growth --review |

云端 `review_<date>.md` 的六条门槛与本地完全相同：`drawdown_budget` ✅、`risk_not_blocked` ✅，其余四条 ❌，`eligible=false`、`validated=false`。

**从这次部署学到的事**：

- 容器里的代码是镜像的一部分，`git pull` 不会改变正在运行的镜像；部署必须「更新仓库 → 重建镜像 → 用新镜像跑测试」；
- 空决策日志的复盘路径也要验证：它不能报错，也不能写出一条假记录；
- 云端和本地输出逐字一致，前提是两边读同一套 committed 口径与同一份 `as_of` 数据；任何一边手工改过 JSON，diff 立刻会暴露。

---

## 8. 学习笔记：几个设计选择背后的理由

### 8.1 为什么成长分不是收益分

收益分无法指导行动：今天赚了，是该继续还是该收手？它也不可归因：收益里混着 beta、运气、仓位。过程分可以直接转化为动作：缺工件就补，样本不够就等，软约束失败就看。**成长体系的目标是让一个普通人持续做对的事，而不是预测市场。**

### 8.2 为什么证据占 30%，和流程一样重

流程分很容易满（7 个工件都在就是 100），如果权重过高，成长分会在流程跑通的第二天就冲到 L3，制造虚假的进步感。把证据放在同等权重，意味着**在结算样本为 0 时，总分上限也只有 70 左右**，必须等时间给答案。这正是本机 62 分的来源。

### 8.3 385 是怎么来的

要把「命中率」估到 ±5% 精度（95% 置信、最坏情况 p=0.5）：

```
n = ceil(z² × p(1−p) / e²) = ceil(1.96² × 0.25 / 0.05²) = ceil(384.16) = 385
```

这个数字直接来自 Phase 7 的 `policy.min_settled_samples`，成长体系只读不算，避免两套门槛。注意：预测账本里的重叠收益会高估有效样本数，385 是**名义**门槛，不是统计上的充分条件。

### 8.4 为什么 `watch` 不计命中率

命中率的分母必须是有方向的判断。把观察项算进去会让命中率「看起来更稳」——观察项永远不会错，因为它没有立场。成长体系宁可样本少，也不要被稀释的准确率。

### 8.5 为什么决策日志只由人写

如果系统自动生成决策，复盘就变成「系统评价系统」，人会被排除在闭环之外。Phase 9 的唯一自动动作是**价格对照**，它不评价决策质量，只提供事实。判断「当时理由是否成立」永远是人做的事。

### 8.6 为什么成长报告不经 LLM

确定性渲染可以保证：`0/385` 就是 `0/385`，`blocked` 就是 `blocked`，不会被措辞柔化。需要叙事的地方（Phase 6 研究报告）已经有 LLM + 证据门禁；成长报告需要的是**不美化**。

### 8.7 数据缺失为什么给 50 分而不是 0 分

没有健康检查文件，不等于数据坏了，只等于「不知道」。给 0 会把「没跑健康检查」和「数据有 error」混为一谈；给 50 是中性的「未知」，同时行动清单里会有 `pipeline.missing` 提示补跑。

---

## 9. 局限与下一步

| 局限 | 影响 | 下一步 |
|---|---|---|
| 组合级决策（无 `symbol`）不自动复盘 | `portfolio` scope 的 `hold/no_trade` 永远 pending | 用组合净值或等权全池做基准，单独实现 |
| 复盘只看到期日价格，不计成本 | 结果偏乐观，尤其是高换手动作 | 扣除单边成本，或在 note 里标注 |
| 成长分不可跨人/跨账户比较 | 只适合单人长期自用 | 保持现状，不做排行榜 |
| 流程 100 只说明 cron 跑通 | 不能说明报告被读过 | 增加「已读/已记录」标记（人工） |
| `n_eff=2.64` 等软约束需要人判断 | 系统只提醒，不解决 | 在组合层调整类别预算或增加低相关标的 |
| 证据门槛依赖账本，账本依赖信号 | 信号质量本身仍是否定结果 | 不因成长分上升而改 `validated` |

---

## 10. 验收清单

- [x] `ruff check finagent scripts tests` 通过；
- [x] `pytest` 全量 **254 passed**（新增 16 条成长测试）；
- [x] 真实数据 `growth --date 2026-11-05` 输出 L2 / 62 / 7/7 / 0/385 / warn；
- [x] 真实数据 `growth --review` 写出 md + json，含六条门槛、行动、学习卡；
- [x] 生产 `journal` 摘要为空（不造假数据），临时目录验证 `--add` 与列表；
- [x] 测试覆盖：缺工件、`blocked`、385 结算、活动窗口/连续天数、里程碑、理由必填、非法动作/置信度、ID 唯一与重复拒绝、看多 hit、看空在上涨市场 miss、观察项不计分、`as_of` 不前视、报告段落、两个 runner 写文件；
- [x] 云端部署 + 容器内 254 passed + growth/review/journal/risk/report 实测（见 §7）。

---

## 11. 命令速查

```bash
# 每日成长状态
python -m finagent.cli growth --date 2026-11-05
python -m finagent.cli growth --date 2026-11-05 --json

# 周期成长报告
python -m finagent.cli growth --date 2026-11-05 --review
python -m finagent.cli growth --date 2026-11-05 --review --window 60

# 决策日志
python -m finagent.cli journal --date 2026-11-05
python -m finagent.cli journal --date 2026-11-05 --add --symbol 510300 \
  --action watch --rationale "等回撤再评估" --confidence 0.6
python -m finagent.cli journal --date 2026-11-05 --review
```

相关文档：

- Phase 7 风控与验证门槛：[`phase7_risk_compliance.md`](phase7_risk_compliance.md)、[`phase7_manual.md`](phase7_manual.md)
- Phase 6 报告：[`phase6_llm_report.md`](phase6_llm_report.md)、[`phase6_manual.md`](phase6_manual.md)
- 前 1–4 评测：[`phase1_4_eval.md`](phase1_4_eval.md)
