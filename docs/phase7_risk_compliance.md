# Phase 7：风控、合规与验证门槛

Phase 7 把「这份组合能不能这样持有」从一句主观判断，变成一组**可计算、可审计、可阻断**的检查；
同时把 `validated=false` 的升级条件写成机器可读的清单。它仍然不做交易、不给建议，
只在研究报告和产物层面加一道硬边界。

> Phase 6 的报告链路见 [`phase6_llm_report.md`](phase6_llm_report.md) 与
> [`phase6_manual.md`](phase6_manual.md)。

## 0. 一页结论

| 项目 | 结果 |
|---|---|
| 命令 | `python -m finagent.cli risk --date 2026-11-05` |
| 产物 | `data/quality/risk_<date>.json`（检查项、限制、验证门槛） |
| 检查层级 | hard（阻断）/ soft（警告）/ info（仅记录） |
| 2026-11-05 实测 | **hard 15/15 通过**，soft 10/11 通过，状态 `warn` |
| 唯一软失败 | 相关性调整后有效标的 **2.64 < 3.0**（分散化不足） |
| 报告接线 | 风控数字进入证据表；`blocked` 时报告必须出现「风控阻断」，否则门禁不通过 |
| 合规词表 | `finagent/risk/compliance.py` 单一来源，Phase 6 提示词直接引用 |
| 验证门槛 | 6 条全部通过才 `eligible=true`；当前差 4 条（结算样本、命中率、平均超额、显著因子） |
| 测试 | 新增 13 个离线测试；全量 `238 passed` |

关键立场：**风控不是收益预测**。它只能回答「有没有越过自己定的线」，不能回答「这样能不能赚钱」。
`eligible=true` 也不自动翻转 `validated`，只是把决定权交回给人。

---

## 1. 为什么要把风控写成检查

Phase 3 的组合构建已经保证了一些约束（单标的 12%、类别预算），但它们分散在构造函数里：
权重文件是结果，不是判决。Phase 7 的改动是把「事后看结果」变成「独立复算 + 明确等级」：

```
portfolio/<date>.json ─┐
quality/health ────────┤
quality/phase_eval ────┼─► evaluate_risk() ─► hard/soft/info ─► status
quality/factor_report ─┤                                      ├─► risk_<date>.json
predictions/ledger ────┘                                      └─► report evidence + gate
cache/etf_daily_hfq ───┘
```

三条设计原则：

1. **独立复算**：不信任组合文件里「已经满足约束」的声明，重新从持仓权重算上限、集中度、流动性。
2. **等级明确**：硬约束只放「越线就必须停」的规则；把「值得注意」放软约束，避免每天都 blocked。
3. **缺数据不猜**：可选工件缺失记 `info`，不伪装成通过，也不误判为失败。

---

## 2. 三层检查

### 2.1 hard：越线即阻断

| 检查 | 规则 | 默认限制 |
|---|---|---|
| `portfolio.present` | 组合文件存在 | — |
| `weights.non_negative` | 无负权重 | `>= 0` |
| `weights.sum_to_one` | 权重合计为 1 | `1.0 ± 0.01` |
| `weights.asset_cap` | 单标的上限 | `<= 12%` |
| `exposure.cap.<category>` | 类别暴露不超过上层上限 | broad 100%、sector 40%、thematic 30%、bond 60%、cross_border 30%、commodity 20% |
| `portfolio.vol_budget` | 组合年化波动率 | `<= 18%` |
| `portfolio.drawdown_budget` | 策略回测最大回撤 | `<= 20%` |
| `liquidity.coverage` | 每个持仓都有价格缓存 | 无缺失 |
| `liquidity.min_adv` | 60 日日均成交额 | `>= 5000 万元` |
| `data.health_errors` | 数据健康检查错误 | `= 0` |

### 2.2 soft：警告，不阻断

| 检查 | 规则 | 默认限制 |
|---|---|---|
| `concentration.top5` | 前五大权重合计 | `<= 40%` |
| `concentration.n_eff` | 相关性调整后有效标的数 | `>= 3.0` |
| `concentration.avg_corr` | 标的平均相关系数 | `<= 60%` |
| `exposure.drift.<category>` | 类别暴露偏离预算 | `<= 3pp` |
| `data.health_warnings` | 健康检查警告 | `= 0` |
| `data.staleness` | 价格缓存落后报告日 | `<= 0 天` |

### 2.3 info：只记录

- `validation.samples`：已结算样本 / 385；
- 可选工件缺失时的占位（流动性、回撤、健康检查未检查）。

`info` 永远不影响 `status`。这是为了避免「没跑 phase_eval 就被判风控失败」的假阳性。

### 2.4 状态推导

```python
status = "blocked" if hard_failed else ("warn" if soft_failed else "pass")
```

没有人工改状态的入口；JSON 里记录 `policy_fingerprint`，改了限制就能追溯是哪一版规则给出的判决。

---

## 3. 与 Phase 6 报告的接线

### 3.1 证据

`quality/risk_<date>.json` 存在时，证据表新增：

| 证据 ID | 含义 |
|---|---|
| `risk:<date>:n_checks` | 检查项总数 |
| `risk:<date>:n_hard_failed` | 硬约束失败数 |
| `risk:<date>:n_soft_failed` | 软约束失败数 |

正文只能用这三个数；具体失败项和数值在 `risk_<date>.json` 里，避免报告变成检查表。

### 3.2 阻断语义

- `status=blocked`：模板在「结论」写「风控阻断，不给出组合层面的正常结论」；
  `verify_report` 的必需词组额外要求 **风控阻断**。LLM 不写就重试，再不写就回退模板。
- `status=warn`：只要求报告陈述风控状态，不阻断。
- 没有 risk 文件：报告在「缺失的工件」里列出 `risk`，其余照常。

### 3.3 报告 JSON

`report_<date>.json` 新增顶层 `risk` 字段，保存完整的检查结果与验证门槛。这样一份报告
自带「当时的数字、当时的门禁、当时的风险判决」，不需要再去翻别的文件。

---

## 4. 合规词表只有一个来源

Phase 6 曾在 `prompts.py` 里直接定义禁用词。Phase 7 把它移到
`finagent/risk/compliance.py`：

```python
FORBIDDEN_TERMS = ("稳赚", "必涨", "保证收益", "推荐买入", "建议买入", "满仓", "抄底")
REQUIRED_TERMS = ("validated=false", "存续偏差", "不构成投资建议")
BLOCKED_TERM = "风控阻断"

def required_terms(risk_status=None):
    ...
```

`agent/prompts.py` 只是重命名导入：

```python
from finagent.risk.compliance import FORBIDDEN_TERMS, REQUIRED_TERMS
MUST_INCLUDE = list(REQUIRED_TERMS)
FORBIDDEN = list(FORBIDDEN_TERMS)
```

测试 `test_compliance_terms_have_one_source` 保证两边不会再各自漂移。合规是规则，
不是某版 prompt 的巧合。

---

## 5. `validated=false` 的升级条件

`finagent/risk/validation.py` 输出机器可读的六条：

| ID | 条件 | 2026-11-05 实际 | 结果 |
|---|---|---|---|
| `settled_samples` | 结算样本 ≥ 385 | 0 | ❌ |
| `hit_rate_excess` | 相对等权命中率 ≥ 55% | 无结算 | ❌ |
| `mean_directional_excess` | 平均方向性超额 > 0 | 无结算 | ❌ |
| `factor_significant` | BH-FDR 后显著中性检验 ≥ 1 | 0 | ❌ |
| `drawdown_budget` | 策略回测最大回撤 ≤ 20% | 18.60% | ✅ |
| `risk_not_blocked` | 风控无硬失败 | `warn` | ✅ |

当前 `eligible=false`，`remaining` 正好是前四条。`eligible=true` 也只表示「证据足够让人复核」，
不会自动改 `validated`；改旗标仍然需要人做决定并记录理由。

为什么把「显著因子」也放进来：如果账本命中率好看，但因子在多重检验后仍不显著，更可能是
样本运气而不是可重复的能力。两条证据链要同时成立。

---

## 6. 实测（2026-11-05）

```bash
python -m finagent.cli risk --date 2026-11-05
```

```
Risk for 2026-11-05  status=warn  policy=risk-v1 (0a8b6aaace1c)
Hard: 15/15 passed   Soft: 10/11 passed   Info: 1
Failed checks:
  - [soft] concentration.n_eff: 相关性调整后有效标的 2.64 (value=2.64, limit=3.0)
Note: validation.samples: 已结算样本 0/385 (value=0, limit=385)
Validation: eligible=false  remaining=settled_samples, hit_rate_excess,
mean_directional_excess, factor_significant  validated=false
```

`status=warn` 是诚实的结果：49 只持仓看起来很多，相关性调整后只相当于 2.64 只独立标的；
平均相关系数 36.55%。组合波动 14.78% 低于 18% 预算，硬约束全部通过，所以不阻断，只警告。

报告侧：

```bash
python -m finagent.cli report --date 2026-11-05 --no-llm
# Mode template / Gate PASS / Citations 54/54 / Numbers 54 checked, 0 untraceable

python -m finagent.cli report --date 2026-11-05
# Mode llm (1 attempt) / Gate PASS / Citations 87/87 / Numbers 82 checked, 0 untraceable
```

模板与 LLM 都在「数据与限制」里写了「风控检查 27 项，硬约束失败 0 项，软约束失败 1 项，状态 warn」；
数字来自证据 ID，不能由模型自行发挥。

---

## 7. 代码地图

| 文件 | 职责 |
|---|---|
| `finagent/risk/policy.py` | `RiskPolicy`、`configs/risk.yaml` 加载、指纹 |
| `finagent/risk/checks.py` | 持仓/集中度/波动/回撤/流动性/数据质量检查与状态推导 |
| `finagent/risk/validation.py` | `validated=false` 的六条升级条件 |
| `finagent/risk/compliance.py` | 禁用词、必需披露、阻断词（单一来源） |
| `finagent/risk/pipeline.py` | 读工件、调用检查、写 `risk_<date>.json`、终端格式 |
| `finagent/cli.py` | `risk --date --out --json` |
| `finagent/agent/evidence.py` | 读 risk 工件，生成三条证据，传播 `risk_status` |
| `finagent/agent/template.py` | 风控行与阻断结论 |
| `finagent/agent/report.py` | 阻断时追加必需词、报告 JSON 带 `risk` |
| `configs/risk.yaml` | 限制默认值（可改，改后指纹变化） |

测试：`tests/test_risk.py`（13）覆盖通过/阻断/软失败/缺件/流动性/健康检查/验证门槛/
策略格式/合规单一来源/阻断词门禁。

---

## 8. 学习笔记

### 8.1 硬约束要少，软约束要诚实

如果所有值得注意的指标都设成 hard，系统每天都会 blocked，人就会开始忽略它。
硬约束只保留「越线即不可接受」的规则（负权重、超上限、流动性不足、数据错误）；
「集中度高」这种程度问题放 soft，让状态是 `warn` 而不是 `blocked`。

### 8.2 不要把「没数据」当成「通过」

早期版本里，缺 phase_eval 会让回撤检查直接 hard fail，结果每次首次运行都 blocked。
正确语义是：缺数据 → `info` + 「未检查」，状态不受影响；但验证门槛里的回撤条件仍然是
`false`，因为「没证据」不能算「满足证据要求」。两者服务于不同问题。

### 8.3 风控层必须独立复算

组合文件是构造函数的输出；风控如果再读它的 `category_exposure` 却不复算权重，
构造函数一旦有 bug，风控也会跟着错。现在的做法是：能从持仓权重复算的都复算
（权重和、单标的上限、top5、类别暴露），只有波动率和回撤这类需要模型的指标才读工件。

### 8.4 阻断要能被机器检查

「报告要说明风控失败」如果只写在 prompt 里，模型可以忘。现在的做法是把
「风控阻断」加进必需词组：`verify_report` 直接判失败，重试一次后回退模板。
模板里的这句话由证据 ID 驱动，不依赖模型自觉。

### 8.5 合规词表是配置，不是提示词

把禁用词留在 `prompts.py` 会让「合规」看起来像 prompt 工程。移到 `risk/compliance.py`
后，报告门禁、模板、测试引用同一组常量；新增一条禁用词只改一个地方，并补一个测试。

### 8.6 验证门槛要可计算，不要可解释

「账本攒够样本」听起来对，但什么叫够？±5% 精度对应 385 条，这是算出来的。
「因子要有效」也要落到 BH-FDR 后的显著计数。每条门槛都写 `actual / required / passed`，
这样 `remaining` 不是一段散文，而是一张待办清单。

### 8.7 eligible 不等于 approved

即使六条全过，代码也只输出 `eligible=true`，`validated` 仍然是 `false`。
自动化可以做「证据是否充分」的判断，但不应该替人做「是否相信这个策略」的判断。
这不是保守，是责任边界。

### 8.8 软失败也有信息量

`n_eff=2.64` 这条 soft 失败比一串 hard 通过更有价值：它解释了为什么 49 只持仓的波动率
只比单只低一点。风控报告不应该只报「通过/不通过」，还要留下「为什么通过得勉强」。

---

## 9. 常见错误

| 错误 | 现象 | 处理 |
|---|---|---|
| 把所有指标设成 hard | 每天 blocked，告警疲劳 | 只把不可接受项设 hard |
| 缺工件就判失败 | 首次运行永远 blocked | 缺件用 info；验证门槛单独处理 |
| 直接信任组合文件的暴露 | 构造函数有 bug 时风控一起错 | 从持仓权重复算 |
| 阻断词只写在 prompt | 模型漏写仍通过 | 加进 `required_terms`，由门禁强制 |
| 改限制不留痕 | 无法解释历史判决 | 每份 JSON 带 `policy_fingerprint` |
| 把 eligible 当成 validated | 自动改旗标 | 保持人工决定，代码只给证据 |
| 风控读取未来数据 | 用最新缓存算历史日期的流动性 | 价格面板按 `as_of` 截断 |

---

## 10. 练习

1. 把 `max_top5_weight` 调到 25%，重跑 risk，观察状态从 `warn` 变成什么；解释为什么不是 blocked。
2. 给 `RiskPolicy` 加一条「单一类别持仓数上限」，写出检查、测试和报告证据 ID。
3. 构造一个 `weights.sum_to_one = 0.9` 的组合，确认 hard fail 的信息足够定位问题。
4. 把 `min_settled_samples` 改成 10，观察 `validation.remaining` 的变化；这样做是否合理？
5. 让 LLM 报告在 blocked 状态下故意不写「风控阻断」，确认重试一次后回退模板。
6. 在 `configs/risk.yaml` 改一个限制，比较两份 risk JSON 的 `policy_fingerprint`。
7. 解释为什么 `liquidity.min_adv` 是 hard，而 `concentration.n_eff` 是 soft。

---

## 11. 下一步

Phase 7 完成后，研究链路具备「数字可追溯 + 结构可检查 + 风险可阻断 + 验证门槛可计算」。
后续可以往三个方向走：

- **Phase 8 成长闭环**：把 risk/validation 的 `remaining` 变成每日待办，按结算进度更新；
- **执行层**：把目标权重翻译成订单草案，但仍在纸面/模拟环境，不接券商；
- **归因**：把组合波动、回撤、超额拆到类别/因子，解释 soft 失败来自哪里。

在账本结算样本达到门槛之前，所有这些都只是研究工具，不是可实盘策略。
