# Phase 7 学习手册

本手册讲**怎么理解、运行、审计和修改** Phase 7 的风控与验证门槛。
设计动机与取舍见 [`phase7_risk_compliance.md`](phase7_risk_compliance.md)；报告链路见
[`phase6_manual.md`](phase6_manual.md)。所有命令都在仓库根目录、已激活 `fin_agent` 环境后执行。

学完你应该能回答四个问题：

1. 一条风险检查由什么组成，为什么分 hard / soft / info？
2. `status=warn` 和 `status=blocked` 分别会让报告发生什么？
3. `validated=false` 还差哪几条证据，每条数字从哪里来？
4. 改一条限制后，怎样证明历史判决没有被悄悄改写？

---

## 0. 速查卡

| 我想…… | 命令 |
|---|---|
| 对最新信号日跑风控 | `python -m finagent.cli risk` |
| 指定日期 | `python -m finagent.cli risk --date 2026-11-05` |
| 终端同时看完整 JSON | `python -m finagent.cli risk --date 2026-11-05 --json` |
| 输出到别的目录 | `python -m finagent.cli risk --date 2026-11-05 --out /tmp/risk` |
| 看状态和剩余门槛 | `python -c "import json; d=json.load(open('data/quality/risk_2026-11-05.json')); print(d['status'], d['validation']['remaining'])"` |
| 看失败项 | `python -c "import json; d=json.load(open('data/quality/risk_2026-11-05.json')); [print(c['id'], c['message']) for c in d['checks'] if not c['passed']]"` |
| 跑 Phase 7 测试 | `python -m pytest tests/test_risk.py` |
| 全量质量门禁 | `make check` |

产物只有一个文件：

```
data/quality/risk_<as_of>.json     # 检查项、限制、状态、验证门槛
```

风控是**只读判决层**：读组合、健康检查、阶段评测、因子报告、账本和价格缓存，
只写 `data/quality/risk_<as_of>.json`。它不改权重、不改账本、不改 `validated`。

---

## 1. 先建立心智模型

### 1.1 四个对象

```
RiskPolicy        规则：每条线画在哪里
    │
    ▼
RiskCheck × N     检查：id / level / passed / value / limit / message / source
    │
    ▼
status            判决：blocked / warn / pass
    │
    ├──────────────► risk_<date>.json
    └──────────────► Phase 6 报告（证据 + 必需词 + JSON.risk）
```

- **Policy** 是配置，不是代码里的散落常数。所有阈值集中在 `RiskPolicy` 与
  `configs/risk.yaml`，每次运行把整份 policy 和指纹写进 JSON。
- **Check** 是原子事实：某条规则、某个值、某个限制、过或不过。它不负责解释全局。
- **Status** 是推导出来的，没有手工设置入口。
- **Validation** 是另一条线：它不判断「今天组合是否越线」，而判断「这个策略是否已经
  攒够证据，值得人来复核 `validated=false`」。

### 1.2 风控不是什么

- 不是收益预测。它只回答「有没有越过自己定的线」。
- 不是交易指令。`pass` 不代表可以买，`blocked` 也不产生卖单。
- 不是回测。回撤和波动来自已有产物，风控不重新跑策略。
- 不是「自动化审批」。即使六条验证门槛全过，代码也只输出 `eligible=true`，
  `validated` 仍保持 `false`，由人决定并记录理由。

### 1.3 与 Phase 3 的分工

Phase 3 的组合构造函数**已经**保证单标的 12%、类别预算等约束。那为什么还要 Phase 7？

| 层次 | 回答的问题 | 信任假设 |
|---|---|---|
| Phase 3 构造 | 我按规则搭出来的组合长什么样 | 相信构造函数 |
| Phase 7 风控 | 这份持仓**实际上**有没有越线 | 不信任声明，尽量复算 |

组合文件是「结果」，风控是「判决」。如果构造函数有 bug，结果会错；风控的价值在于
换一条路径重新算，让同一个 bug 有机会暴露。

> 当前实现的边界要看清：权重和、单标的、top5 是从 `holdings` 复算的；类别暴露在
> `category_exposure` 存在时直接采用声明值，只有缺失时才按持仓汇总；波动率和回撤
> 直接读产物。§11 有一个练习就是把类别暴露也改成始终复算。

---

## 2. 三层检查：hard / soft / info

### 2.1 语义

| 等级 | 含义 | 失败后 status | 典型例子 |
|---|---|---|---|
| `hard` | 越线即不可接受，报告不得给出正常结论 | `blocked` | 负权重、超单标的上限、流动性不足、数据错误 |
| `soft` | 值得注意，但不阻断 | `warn` | 集中度高、有效广度不足、类别偏离预算 |
| `info` | 只记录，不表达通过/失败 | 不改变 | 结算样本进度、缺可选工件 |

### 2.2 状态真值表

| 有 hard 失败 | 有 soft 失败 | status | CLI 退出码 | 报告额外要求 |
|---|---|---|---|---|
| 是 | 任意 | `blocked` | 1 | 必须出现「风控阻断」 |
| 否 | 是 | `warn` | 0 | 只需陈述风控状态 |
| 否 | 否 | `pass` | 0 | 只需陈述风控状态 |

推导只有一行：

```python
status = "blocked" if hard_failed else ("warn" if soft_failed else "pass")
```

`info` 永远不参与这一行。这样设计是为了避免「没跑 `phase_eval` 就被判风控失败」的
假阳性：缺数据应当说「未检查」，而不是说「不合格」。

### 2.3 为什么 hard 要少

如果所有值得注意的指标都是 hard，系统每天都会 `blocked`，人很快会开始忽略它——这叫
告警疲劳。hard 只保留「越线即不可接受」的规则；程度问题放 soft，让输出是 `warn`。
`warn` 仍然有信息量，而且不会让报告失去可读性。

---

## 3. 运行

### 3.1 输入

| 输入 | 路径 | 必需 | 缺失时 |
|---|---|---|---|
| 组合 | `data/portfolio/<as_of>.json` | **是** | 直接报错，退出码 1 |
| 健康检查 | `data/quality/health_<as_of>.json` | 否 | 错误检查降为 `info`，警告检查不出现 |
| 阶段评测 | `data/quality/phase_eval_<as_of>.json` | 否 | 广度/回撤降为 `info` |
| 因子报告 | `data/quality/factor_report_<as_of>.json` | 否 | 显著因子条件判失败 |
| 预测账本 | `data/predictions/` | 否 | 结算样本按 0 计 |
| 价格缓存 | `data/cache/` | 否 | 流动性降为 `info` |

组合是唯一硬前置。原因很直接：没有持仓，就没有「组合有没有越线」这个问题。
只跑 `portfolio` 而不跑 `phase_eval` 也能得到判决，只是有几项会明确写「未检查」。

推荐顺序（也是 cron 的顺序）：

```bash
python -m finagent.cli signals        # 18:45
python -m finagent.cli portfolio      # 18:47
python -m finagent.cli risk           # 18:48
python -m finagent.cli report         # 18:50
```

### 3.2 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--date YYYY-MM-DD` | 最新信号文件的日期 | 风控日期；不会自动回退到上一交易日 |
| `--out DIR` | `data/quality` | 输出目录；会自动创建 |
| `--json` | 关 | 摘要之后再把完整 JSON 打到 stdout |

日期规则与 `report` 一致：给了 `--date` 就只认这一天。周末/节假日请给最近一个有
组合文件的交易日，否则会得到：

```
risk: no portfolio for 2026-11-07; run `finagent portfolio --date 2026-11-07` first
```

`--out` 只改**写到哪里**，不会改报告读取的位置。报告固定读
`data/quality/risk_<date>.json`；如果为了归档写到 `/tmp`，报告不会自动看到它。

### 3.3 退出码

| 码 | 含义 |
|---|---|
| 0 | `pass` 或 `warn`，产物已写出 |
| 1 | `blocked`（产物仍然写出）；或缺少组合 / 策略配置错误等 `RiskError` |

注意：`blocked` 时**仍然写 JSON**。退出码是给 cron/监控看的，JSON 是给人的审计记录。
cron 的每一行是独立命令，`risk` 退出 1 不会阻止 18:50 的 `report` 运行；报告会读到
`blocked` 并写入「风控阻断」。

### 3.4 一次运行做了什么

```
portfolio ─────────────────────────────┐
quality/health ────────────────────────┤
quality/phase_eval ────────────────────┼─► evaluate_risk()
quality/factor_report ─────────────────┤       │
predictions/ledger.summary(as_of) ─────┤       ├─ checks + counts
cache：持仓的 60 日价格 ────────────────┘       ├─ status
                                                └─ evaluate_validation()
                                                       │
                                                       ▼
                                          risk_<as_of>.json
```

价格面板按 `as_of` 截断，不会用未来数据计算历史日期的流动性。这是 point-in-time
原则在风控层的体现。

---

## 4. 逐条读懂检查

### 4.1 当前组合的 27 项由什么组成

2026-11-05 的 49 只持仓分布在 6 个类别，因此：

| 组 | 数量 | 检查 |
|---|---|---|
| 持仓与权重 | 4 hard | `portfolio.present`、`weights.non_negative`、`weights.sum_to_one`、`weights.asset_cap` |
| 集中度 | 1 soft | `concentration.top5` |
| 类别上限 | 6 hard | `exposure.cap.<category>` |
| 类别偏离 | 6 soft | `exposure.drift.<category>` |
| 组合风险预算 | 2 hard | `portfolio.vol_budget`、`portfolio.drawdown_budget` |
| 流动性 | 2 hard | `liquidity.coverage`、`liquidity.min_adv` |
| 数据质量 | 1 hard + 2 soft | `data.health_errors`、`data.health_warnings`、`data.staleness` |
| 广度 | 2 soft | `concentration.n_eff`、`concentration.avg_corr` |
| 验证进度 | 1 info | `validation.samples` |

合计 **15 hard + 11 soft + 1 info = 27**。

总数不是固定的：类别数、缺失工件都会改变它。不要写死「27 项」做断言，读 `counts`。

### 4.2 每条检查怎么算

| 检查 | 计算 | 默认线 | 数据来源 | 备注 |
|---|---|---|---|---|
| `portfolio.present` | 文件是否存在、持仓数 | — | portfolio | 缺文件直接 hard fail |
| `weights.non_negative` | 是否所有 `weight >= 0` | `>= 0` | `holdings` | 容差 `-1e-9` |
| `weights.sum_to_one` | `sum(weight)` | `1.0 ± 0.01` | `holdings` | 复算，不信声明 |
| `weights.asset_cap` | `max(weight)` | `<= 12%` | `holdings` | 容差 `1e-6` |
| `concentration.top5` | 最大 5 个权重之和 | `<= 40%` | `holdings` | soft |
| `exposure.cap.<cat>` | 类别暴露 | 见 §4.3 | `category_exposure`，缺失时按持仓汇总 | hard |
| `exposure.drift.<cat>` | `abs(actual - budget)` | `<= 3pp` | 同上 + `policy.category_budget` | soft |
| `portfolio.vol_budget` | `portfolio_vol` | `<= 18%` | portfolio | 读产物，不重算 |
| `portfolio.drawdown_budget` | `abs(max_drawdown)` | `<= 20%` | phase_eval 的 `policy_tilt` / `policy_no_tilt` | 先 tilt，后 no_tilt |
| `liquidity.coverage` | 持仓是否都有价格 | 无缺失 | cache | 只有拿到价格时才检查 |
| `liquidity.min_adv` | 每只持仓最近 60 个交易日的 `amount` 均值 | `>= 5000 万` | cache | 用成交额，不是成交量 |
| `data.health_errors` | `errors` | `= 0` | health | hard |
| `data.health_warnings` | `warnings` | `= 0` | health | soft；当前 0 |
| `data.staleness` | `as_of - 最新价格日期`（自然日） | `<= 0` | cache | 只有拿到价格时才检查 |
| `concentration.n_eff` | 相关性调整后有效标的数 | `>= 3.0` | phase_eval.breadth | soft |
| `concentration.avg_corr` | 平均相关系数 | `<= 60%` | phase_eval.breadth | soft |
| `validation.samples` | 账本已结算条数 | `>= 385` | ledger | info；不影响 status |

几个容易误解的点：

- **`liquidity.min_adv` 用的是成交额**（`amount` 列的 60 日均值），不是成交量。
  单位是元，阈值 5000 万元。
- **`data.staleness` 用自然日**，不是交易日。周五的数据在周一运行时已经「落后 3 天」，
  但只要当天缓存更新过，就是 0。
- **回撤取绝对值后和 20% 比**。JSON 里 `value` 写的是负数（如 `-0.180695`），
  `limit` 也是负数（`-0.2`），这样读起来就是「-18.07% 没有跌破 -20%」。
- **类别上限对未知类别默认 1.0**。新增类别时如果忘了配 `category_caps`，它不会被
  这条规则限制；应该同步配置。
- **`category_exposure` 优先于持仓汇总**。这是当前实现的一个已知边界：如果组合文件里
  的类别暴露是过期或错误的，风控会跟着错。§11 练习 2 会让你修掉它。

### 4.3 类别上限

| 类别 | 上限 | 含义 |
|---|---|---|
| `broad` | 100% | 宽基可以是全部 |
| `sector` | 40% | 行业 ETF 不超过四成 |
| `thematic` | 30% | 主题不超过三成 |
| `bond` | 60% | 债券不超过六成 |
| `cross_border` | 30% | 跨境不超过三成 |
| `commodity` | 20% | 商品不超过两成 |

上限来自 `configs/risk.yaml` 的 `category_caps`，不是硬编码在检查函数里。

---

## 5. 判决怎么读

### 5.1 终端输出

2026-11-05 的真实输出：

```
Risk for 2026-11-05  status=warn  policy=risk-v1 (0a8b6aaace1c)
Hard: 15/15 passed   Soft: 10/11 passed   Info: 1
Failed checks:
  - [soft] concentration.n_eff: 相关性调整后有效标的 2.64 (value=2.64, limit=3.0)
Note: validation.samples: 已结算样本 0/385 (value=0, limit=385)
Validation: eligible=false  remaining=settled_samples, hit_rate_excess,
mean_directional_excess, factor_significant  validated=false
```

逐行解释：

1. 第一行：日期、状态、策略名、**策略指纹**。指纹是整份 policy 的 SHA-256 前 12 位；
   改任何一条限制都会变。
2. 第二行：hard 通过数、soft 通过数、info 数量（info 不分通过/失败）。
3. `Failed checks:` 只列 hard/soft 失败；`Note:` 只列 info 的「未达成」，不叫失败。
4. `Validation:` 是六条升级门槛的汇总，和今天的组合判决是两件事。
5. `validated=false` 是硬编码的：风控命令从不修改旗标。

### 5.2 JSON 顶层字段

| 字段 | 含义 |
|---|---|
| `as_of` | 判决日期 |
| `policy` | 完整生效策略（所有阈值 + 类别上限） |
| `policy_fingerprint` | 策略指纹，用于追溯 |
| `status` | `pass` / `warn` / `blocked` |
| `counts` | `total / hard / soft / info / hard_failed / soft_failed` |
| `checks` | 每项：`id / level / passed / message / value / limit / source` |
| `failed` | hard 失败 + soft 失败的 id 列表（不含 info） |
| `validation` | `validated / eligible / criteria / remaining / note` |
| `generated_at` | 生成时间（本地时区） |
| `inputs` | 实际读取的工件路径；缺失的为 `null` |
| `risk_file` | 写出的 JSON 路径 |

`value` 和 `limit` 是**原始单位**：权重是 0–1 的小数，不是百分数；成交额是元。
终端里的 `%` 和「亿元」只是显示格式。

### 5.3 一分钟审计

```python
import json

d = json.load(open("data/quality/risk_2026-11-05.json"))
assert d["status"] in {"pass", "warn", "blocked"}
assert d["counts"]["hard_failed"] == 0 or d["status"] == "blocked"
assert d["counts"]["soft_failed"] == 0 or d["status"] in {"warn", "blocked"}
assert d["validation"]["validated"] is False
assert d["counts"]["total"] == len(d["checks"])
print(d["policy"]["name"], d["policy"]["max_asset_weight"])
```

更实用的做法是把「策略指纹 + status + 失败项」写进监控；指纹变化意味着规则变了，
不是市场变了。

---

## 6. 验证门槛：`validated=false` 到底差什么

### 6.1 六条

`finagent/risk/validation.py` 输出六条机器可读条件：

| ID | 条件 | 默认要求 | 2026-11-05 实际 | 结果 |
|---|---|---|---|---|
| `settled_samples` | 已结算预测数 | `>= 385` | 0 | ❌ |
| `hit_rate_excess` | 相对等权全池的命中率 | `>= 55%` | 无结算 | ❌ |
| `mean_directional_excess` | 平均方向性超额 | `> 0` | 无结算 | ❌ |
| `factor_significant` | BH-FDR 后显著的中性检验数 | `>= 1` | 0 | ❌ |
| `drawdown_budget` | 回测最大回撤 | `<= 20%` | 18.07% | ✅ |
| `risk_not_blocked` | 风控无 hard 失败 | `!= blocked` | `warn` | ✅ |

每条都写成 `actual / required / passed`。`remaining` 就是没过的 ID 列表，可以直接
当待办清单用。

### 6.2 385 是怎么来的

不是拍的。命中率的 ±5% 置信区间，在 `p=0.5`（最坏情况）、`z=1.96`（95% 置信）下：

```
n = ceil(z² · p(1-p) / margin²)
  = ceil(1.96² × 0.25 / 0.05²)
  = ceil(384.16)
  = 385
```

实现见 `finagent/evaluation/value.py::required_settled`。这个数字假设样本**独立**；
账本里 20 日持有期的预测会重叠，有效样本数小于名义条数，所以 385 是下限，不是充分条件。

### 6.3 `eligible` 不是 `approved`

```python
"validated": False,
"eligible": not remaining,
```

六条全过时 `eligible=true`，但 `validated` 仍是 `false`。这是故意的责任边界：

- 代码可以判断「证据是否足够」；
- 人才能判断「是否相信这个策略」；
- 改旗标必须留下理由，不能由一次自动运行完成。

### 6.4 为什么「显著因子」也在门槛里

如果账本的命中率好看，但因子在多重检验后仍不显著，更可能是样本运气，而不是可重复的
能力。账本证据和因子证据要同时成立，才值得进入人工复核。

### 6.5 缺数据时各条怎么算

- `settled_samples`：缺账本按 0 计，判失败。
- `hit_rate_excess` / `mean_directional_excess`：`None` 判失败，不会当成 0 通过。
- `factor_significant`：缺因子报告按 0 计。
- `drawdown_budget`：缺 `phase_eval` 时 `actual=None`，判失败。
  **注意**：这和 §4 的 `portfolio.drawdown_budget` 不同——后者缺数据是 `info`，不影响
  status；验证门槛问的是「有没有证据满足要求」，没证据就是没满足。
- `risk_not_blocked`：未运行风控时 `actual="not run"`，视为未阻断。

同一个缺失工件，在「今天的组合是否越线」和「策略是否已积累足够证据」两个问题下，
语义不同。这是本阶段最容易混淆的地方之一。

---

## 7. 与 Phase 6 报告怎么接

### 7.1 只放三个数字

`quality/risk_<date>.json` 存在时，证据表新增三条：

| 证据 ID | 标签 |
|---|---|
| `risk:<date>:n_checks` | 风控检查项数 |
| `risk:<date>:n_hard_failed` | 风控硬约束失败项数 |
| `risk:<date>:n_soft_failed` | 风控软约束失败项数 |

具体是哪条检查失败、`n_eff` 是多少，**不进入报告正文**。原因：

- 报告是研究叙事，不是检查清单；
- 数字越少，严格数字门禁越容易审计；
- 完整细节在 `risk_<date>.json` 里，报告 JSON 的 `risk` 字段也带了一份快照。

### 7.2 `blocked` 时发生什么

三处同时生效：

1. `prompts.py`：user prompt 写「风控状态：blocked；结论必须明确写『风控阻断』」。
2. `compliance.required_terms("blocked")`：必需词追加「风控阻断」。
3. `template.py`：在「结论」里写「风控硬约束失败 N 项，本报告触发风控阻断，
   不给出组合层面的正常结论」。

LLM 漏写「风控阻断」→ 门禁失败 → 重试一次 → 仍失败就回退模板。模板自己过同一套门禁，
所以阻断语义不会依赖模型自觉。

`warn` 不会追加必需词，只要求报告陈述风控状态；报告在「数据与限制」里写：

```
- 风控检查 27 项 [...]: 硬约束失败 0 项 [...], 软约束失败 1 项 [...]; 状态 warn。
```

### 7.3 报告 JSON

`report_<date>.json` 顶层新增 `risk`，保存完整的风控结果与验证门槛。这样一份报告自带
「当时的数字、当时的门禁、当时的风险判决」，不必再跨文件对照。

没有 `risk` 工件时：

- `report.risk` 为 `null`；
- `missing` 里出现 `risk`；
- 报告照常生成，不会因为没有风控而失败。

### 7.4 先跑 risk 再跑 report

报告读取的是**落盘**的 `risk_<date>.json`，不是内存里的结果。改了限制、重跑了 risk，
要再跑一次 report，报告里的风控快照才会更新。

---

## 8. 改限制：一次可审计的变更

### 8.1 改哪里

只改 `configs/risk.yaml`，不要改 JSON，也不要在调用处临时改常量。

```yaml
max_top5_weight: 0.30
min_n_eff: 3.5
```

`comment` 键会被忽略，可以放说明。未知键会直接报错，避免拼写错误被静默忽略：

```
ValueError: unknown risk policy keys: ['max_top_five']
```

### 8.2 加载与校验

- 找不到 `configs/risk.yaml` 时使用 `RiskPolicy()` 默认值。
- YAML 覆盖默认值；`__post_init__` 校验部分字段：比例类必须在 `(0, 1]`，
  `min_avg_amount_60d >= 0`，`min_hit_rate_excess ∈ [0, 1]`，`min_settled_samples >= 1`。
- `min_n_eff`、`max_health_errors`、`max_health_warnings`、`category_caps` 目前没有
  范围校验；改它们时要自己保证语义合理。

### 8.3 指纹

```python
blob = json.dumps(policy.as_dict(), sort_keys=True, ensure_ascii=False)
fingerprint = hashlib.sha256(blob.encode()).hexdigest()[:12]
```

因此：

- 只改注释 → 指纹**不变**；
- 改任何阈值、策略名、类别上限 → 指纹变化；
- 指纹相同可以认为两次判决用了同一套规则。

每次改完限制，至少做三件事：

```bash
python -m finagent.cli risk --date 2026-11-05 --json > /tmp/risk-new.txt
python -m finagent.cli report --date 2026-11-05 --no-llm
python -m pytest tests/test_risk.py
```

对比新旧 JSON 的 `policy_fingerprint`、`status`、`failed`，确认变化符合预期。

### 8.4 不要把「通过」当成目标

如果一条检查总是失败，先问：

1. 是组合真的越线，还是阈值不适合这个策略？
2. 是数据缺失造成的假失败，还是规则本身写错？
3. 如果放宽，历史判决会不会变得不可比？

可以改规则，但必须留下指纹变化和理由。**不要为了让某天的报告好看而临时改阈值。**

---

## 9. 排障手册

| 现象 / 信息 | 根因 | 处理 |
|---|---|---|
| `no portfolio for <date>; run finagent portfolio ...` | 没有该日组合文件 | 先跑 `portfolio --date <date>`；或改用有组合的交易日 |
| `unknown risk policy keys: [...]` | YAML 拼写错误或写了未支持字段 | 对照 `RiskPolicy` 字段名修正 |
| `must be in (0, 1]` / `must be positive` | 阈值超出允许范围 | 比例写小数（12% 写 `0.12`），样本数写正整数 |
| `status=blocked` 但不知道哪条 | 终端只显示失败项；先看 `Failed checks` | `failed` 数组 + 每项的 `message` 足够定位 |
| `status=warn` 且只有 `n_eff` 失败 | 持仓多但相关性高，分散化不足 | 这是真实信息，不一定要改；看 `avg_corr` 和类别暴露 |
| `info` 里 `validation.samples` 显示 `Note` | 结算样本未达 385 | 正常；这是进度，不是失败 |
| 流动性显示「未检查」 | 价格缓存缺失或读取失败 | 先跑采集；确认 `data/cache/etf_daily_hfq` 有对应代码 |
| `data.staleness` 失败 | 缓存最新日期落后 `as_of` | 补跑当天采集；检查 `as_of` 是否给错 |
| `portfolio.drawdown_budget` 是 info | 缺 `phase_eval` | 跑 `python scripts/phase_eval.py`；或接受「未检查」 |
| 验证门槛里 `drawdown_budget` 失败但风险检查是 info | 两个问题语义不同（§6.5） | 补 `phase_eval`，不要改风控等级来「修」它 |
| cron 日志里 risk exit 1 | 当天 hard 约束越线 | 看 `data/quality/risk_<date>.json`；报告仍会生成并写「风控阻断」 |
| 报告里没有风控段 | risk 没跑，或 `--out` 写到了别处 | 用默认输出目录重跑 risk，再重跑 report |
| 改了 YAML 但指纹没变 | 只改了注释，或改的不是生效文件 | 确认读的是 `configs/risk.yaml`；打印 `policy` 看实际值 |
| 容器里路径是 `/app/...` | 容器工作目录是 `/app` | 属正常；宿主机对应 `data/...` |

### 9.1 定位一条失败检查

```bash
python - <<'PY'
import json
d = json.load(open("data/quality/risk_2026-11-05.json"))
for c in d["checks"]:
    if not c["passed"]:
        print(c["level"], c["id"])
        print("  message:", c["message"])
        print("  value:", c["value"], "limit:", c["limit"])
        print("  source:", c["source"])
PY
```

`source` 告诉你该去看哪个工件：`portfolio` / `phase_eval` / `cache` / `health` / `ledger`。

### 9.2 复现一次判决

```bash
# 同一份输入、同一份 policy，结果应当逐字段一致（generated_at 除外）
python -m finagent.cli risk --date 2026-11-05 --out /tmp/risk-a
python -m finagent.cli risk --date 2026-11-05 --out /tmp/risk-b
python - <<'PY'
import json
a = json.load(open("/tmp/risk-a/risk_2026-11-05.json"))
b = json.load(open("/tmp/risk-b/risk_2026-11-05.json"))
a.pop("generated_at"); b.pop("generated_at")
print("identical:", a == b)
PY
```

如果两次不一致，先查输入是否在两次运行之间被改写（采集、portfolio、ledger），
再查是否有未固定的时间/随机因素。风控本身不使用随机数。

---

## 10. 学习路径

建议按这个顺序读代码，每步都跑一次命令：

1. `finagent/risk/policy.py`：先看「规则长什么样」，跑一次 risk 看 JSON 里的 `policy`。
2. `finagent/risk/checks.py`：看 `evaluate_risk` 如何把持仓变成 checks；对照 §4 的表。
3. `finagent/risk/validation.py`：看六条门槛的 `actual` 从哪里来。
4. `finagent/risk/pipeline.py`：看工件如何被读取、价格如何按 `as_of` 截断。
5. `finagent/risk/compliance.py` + `agent/report.py`：看阻断词如何进入门禁。
6. `finagent/agent/template.py`：看模板如何用三个证据 ID 写风控段。
7. `tests/test_risk.py`：13 个测试就是 13 个可执行的行为规格。

阅读时始终问三个问题：

- 这个数字是**复算**的，还是**读声明**的？
- 缺数据时它是 `info`、失败，还是根本不出现？
- 它会不会改变 status / 报告门禁 / `validated`？

---

## 11. 练习

先自己判断，再运行验证。

1. **改 soft 阈值**：把 `max_top5_weight` 从 40% 调到 25%，重跑 risk。
   当前 top5 是 28.78%，状态会变成什么？为什么不是 `blocked`？
2. **让类别暴露真正复算**：修改 `checks.py::_exposures`，让它始终从 `holdings` 汇总，
   忽略 `category_exposure`。补一个测试：声明暴露与持仓不一致时，以持仓为准。
   再想一下：这会改变哪条检查的结果？
3. **构造越线组合**：把某只持仓权重改成 15%，重跑 risk。确认
   `weights.asset_cap` 失败、`status=blocked`、CLI 退出码 1，并且报告必须写「风控阻断」。
4. **权重和不为 1**：构造 `sum=0.90` 的组合。终端信息是否足以定位问题？
   `value` 和 `limit` 分别是什么？
5. **缺工件语义**：把 `phase_eval` 临时移走，重跑 risk。哪些检查从 hard/soft 变成
   `info`？验证门槛里的 `drawdown_budget` 是 `info` 还是失败？解释两者为什么不矛盾。
6. **指纹实验**：只改 YAML 注释，记录指纹；再改一个阈值，记录指纹。
   两次都重跑 risk，比较 `policy_fingerprint`。
7. **结算样本**：把 `min_settled_samples` 改成 10，观察 `remaining` 是否变化。
   当前账本有 0 条结算，所以结果如何？这个改动合理吗？
8. **阻断词门禁**：用 `tests/test_risk.py::test_blocked_risk_requires_the_block_term_in_reports`
   的思路，手工把模板里的「风控阻断」替换成「风控提示」，确认 `verify_report` 失败。
9. **流动性**：把价格缓存里某只持仓的 `amount` 改成 1000 万，重跑 risk。
   哪条检查失败？`value` 的单位是什么？
10. **只读性**：在 risk 运行前后计算 `data/portfolio/<date>.json` 与
    `data/predictions/` 的哈希，确认风控没有改写它们。

### 参考答案要点

1. `warn`。top5 是 soft；只有 hard 失败才会 `blocked`。
2. 类别暴露、类别上限、类别偏离三组检查都会受影响；当前组合的声明值与持仓汇总很接近，
   所以状态可能不变，但检查的**可信度**提高了。
3. 15% > 12% → `weights.asset_cap` hard fail → `blocked`；退出码 1；报告必需词多一条。
4. `weights.sum_to_one` 失败，`value=0.9`、`limit="1.0 ± 0.01"`；`message` 里有权重合计。
5. 广度两条与回撤一条变 `info`；验证门槛里的 `drawdown_budget` 仍然**失败**。
   前者问「今天是否越线」，后者问「是否有足够证据」。
6. 注释不参与 `as_dict`，指纹不变；阈值变化 → 指纹变化。
7. 仍剩 `settled_samples`（0 < 10），其余三条也仍失败。把门槛降到 10 不会让 0 条结算
   变成有证据，只会降低要求；不合理。
8. 门禁返回 `passed=False`，`must_include_missing` 含「风控阻断」。
9. `liquidity.min_adv` 失败；`value` 是最低 60 日均成交额，单位元。
10. 哈希不变。风控只写 `data/quality/risk_<date>.json`。

---

## 12. 验收清单

发布或改完风控代码后按顺序过一遍：

- [ ] `python -m pytest tests/test_risk.py` 全绿
- [ ] `make check` 全绿（ruff + 全量 pytest + eval smoke）
- [ ] `risk --date <date>` 能产出 JSON，`status` 与 `counts` 自洽
- [ ] `validation.validated` 恒为 `false`
- [ ] 改一条限制后 `policy_fingerprint` 变化，且 JSON 里保存了完整 `policy`
- [ ] 缺 `phase_eval` / `health` / 价格时，相应检查降为 `info`，不误判 blocked
- [ ] `blocked` 时 CLI 退出码为 1，报告仍生成且含「风控阻断」
- [ ] `warn` 时退出码 0，报告「数据与限制」含风控计数
- [ ] 报告 JSON 的 `risk` 与 `data/quality/risk_<date>.json` 一致
- [ ] 风控运行前后，组合文件与预测账本未被改写
- [ ] cron 顺序正确：18:45 signals → 18:47 portfolio → 18:48 risk → 18:50 report

---

## 13. 附录

### 13.1 检查 ID 命名

| 前缀 / ID | 含义 |
|---|---|
| `portfolio.*` | 组合文件与组合级预算 |
| `weights.*` | 权重非负、合计、单标的上限 |
| `concentration.*` | top5、有效广度、平均相关 |
| `exposure.cap.<category>` | 类别暴露上限 |
| `exposure.drift.<category>` | 类别暴露偏离预算 |
| `liquidity.*` | 价格覆盖、60 日日均成交额 |
| `data.*` | 健康检查错误/警告、缓存新鲜度 |
| `validation.samples` | 结算样本进度（info） |

验证门槛 ID：`settled_samples`、`hit_rate_excess`、`mean_directional_excess`、
`factor_significant`、`drawdown_budget`、`risk_not_blocked`。

### 13.2 当前基线（2026-11-05）

| 项目 | 数值 |
|---|---|
| 策略 | `risk-v1`，指纹 `0a8b6aaace1c` |
| 检查 | 27 项：15 hard / 11 soft / 1 info |
| 状态 | `warn`；hard 15/15，soft 10/11 |
| 唯一软失败 | `concentration.n_eff = 2.64 < 3.0` |
| 其他关键值 | 组合波动 14.78%、回测回撤 -18.07%、top5 28.78%、avg_corr 36.55%、最低 ADV 1.57 亿 |
| 验证门槛 | `eligible=false`，剩 4 条：结算样本、命中率、平均超额、显著因子 |
| 模板报告 | 54/54 引用、54 个数字，0 不可追溯 |
| LLM 报告 | 引用与数字数量随采样波动，门禁比例恒为 100% |

这些数字会随数据更新变化。稳定不变的是：`validated=false`、100% 数字可追溯、
以及「状态由 hard/soft 推导」这三条规则。

### 13.3 相关文件

| 文件 | 用途 |
|---|---|
| `configs/risk.yaml` | 限制配置（可改，改后指纹变化） |
| `finagent/risk/policy.py` | `RiskPolicy`、YAML 加载、指纹 |
| `finagent/risk/checks.py` | 检查计算与状态推导 |
| `finagent/risk/validation.py` | `validated=false` 的六条升级条件 |
| `finagent/risk/compliance.py` | 禁用词、必需词、阻断词（单一来源） |
| `finagent/risk/pipeline.py` | 读工件、跑检查、写 JSON、终端格式 |
| `finagent/cli.py` | `risk` 子命令 |
| `finagent/agent/evidence.py` | 三条风控证据 + `risk_status` |
| `finagent/agent/prompts.py` | 阻断时的必需词提示 |
| `finagent/agent/template.py` | 风控计数行与阻断结论 |
| `finagent/agent/report.py` | 阻断词门禁、报告 JSON 的 `risk` |
| `tests/test_risk.py` | 13 个离线测试 |
| `docs/phase7_risk_compliance.md` | 设计与取舍 |
| `deploy/crontab.example` | 18:47 portfolio、18:48 risk |

### 13.4 术语

- **Policy（策略）**：一组阈值和类别上限，带名字和指纹。
- **Check（检查）**：一条规则在某个日期、某份持仓上的原子判定。
- **hard / soft / info**：阻断 / 警告 / 仅记录。
- **Status（判决）**：由 hard/soft 失败推导，不可手工设置。
- **Fingerprint（指纹）**：policy 的 SHA-256 前 12 位，用于追溯历史判决。
- **Validation（验证门槛）**：判断证据是否足够让人复核 `validated=false` 的六条条件。
- **eligible**：证据足够，可以进入人工复核；不等于 approved，也不自动改旗标。
