# Phase 5：资金流与新闻叠加

实现日期 2026-11-06；数据截止 `as_of=2026-11-05`。

> 阅读指引：§0 结论、§2 实现、§5 学习笔记是主线；§3 验收与 §4 复现供复核；§6 是后续动作。

## 0. 结论先行

| 项 | 状态 | 说明 |
|---|---|---|
| 行业资金流因子 | ✅ 实现，⏳ 数据不足 | `sector_flow_rank` 目前只有 **1 天快照**；至少 5 天才定义 5 日累计流向，今天明确返回 unavailable |
| ETF 份额变化 | ✅ 实现，⛔ 无数据 | `etf_scale_sse` 缓存 **0 个文件**（仅 SSE、发布有滞后） |
| 折溢价 | ✅ 实现，⛔ 无数据 | `etf_nav` 缓存 **0 个文件**，没有 T-1 单位净值就无法算 |
| 市场资金流 | ✅ 可用（仅背景） | 121 个交易日；全市场一个数，不能给 ETF 排序 |
| 新闻 → 板块 → ETF | ✅ 实现，⏳ 未接入数据源 | 读取 `data/news/<date>.json`；缺文件时跳过并标注。week3 提取器不在本仓库 |
| 缺源降级 | ✅ | 每个源返回 `SourceStatus`，`flows` 命令与 `signals` JSON 都写明缺失原因 |
| 新闻影响可解释 | ✅ | 每个受影响的标的输出 `news_score / n_items / titles / contribution / composite_before / after` |

**一句话**：Phase 5 的管道和验收已经完成，但今天**没有任何资金流因子可以计算**——这不是代码问题，是数据只积累了 1 天。按本项目原则，缺数据就标注、不拿一天截面冒充趋势。

## 1. 今天的实际输出

```text
$ python -m finagent.cli flows --date 2026-11-05

Phase 5 flows & news  2026-11-05

SOURCES
MISSING sector_flow_rank   need 5 daily snapshots, have 1 (2026-11-05..2026-11-05); collection accumulates one per trading day
MISSING etf_scale_sse      no etf_scale_sse snapshot on or before 2026-11-05
MISSING etf_nav            no cached unit NAV on or before 2026-11-05
OK      market_flow        latest 2026-11-05
MISSING news               no news file at data/news/2026-11-05.json

MARKET FLOW  2026-11-05  main net inflow 0.4% (5d mean -0.44%)

SECTOR FLOW (z, mapped ETFs): no scores (source unavailable)
SHARE CHANGE (z, mapped ETFs): no scores (source unavailable)
PREMIUM / DISCOUNT (z, mapped ETFs): no scores (source unavailable)
```

云端（服务器缓存里已有 2026-11-05 的采集结果）同一天输出只有 **MISSING 的原因**不同：`etf_scale_sse` 有 1 个快照（「need at least two snapshots to measure a change」）、`etf_nav` 有 1 只标的（「only 1 symbols have a same-day close and NAV」）。四项资金流判定仍是 1 个可用、3 个 unavailable，可见降级逻辑与实际缓存内容对齐，而不是写死的一句话。

`signals` 在缺新闻文件时的行为：

```text
$ python -m finagent.cli signals --date 2026-11-05
...
news overlay: skipped — no news file at data/news/2026-11-05.json
```

信号本身与 Phase 5 之前完全一致：叠加不可用时**不改分数**，也不回退到昨天的新闻。

## 2. 实现

### 2.1 资金流因子（`finagent/flows/`）

| 因子 | 定义 | 方向 | 数据要求 |
|---|---|---|---|
| `sector_flow` | 每个交易日先对行业净流入做截面 z，再对最近 `window` 个快照求和；ETF 取其 `flow_sectors` 的均值 | +（净流入为正） | ≥ `window`(默认 5) 个 `sector_flow_rank` 快照 |
| `share_change` | 最新份额 / 基准日份额 − 1，截面 z；同时报告 `span_days` | +（份额增加） | ≥ 2 个 `etf_scale_sse` 快照 |
| `premium_discount` | 同一交易日收盘价 / 单位净值 − 1，截面 z；报告 `nav_date` | +（溢价） | `etf_nav` 历史 + 同日收盘 |

三个 loader 都返回 `(frame, SourceStatus)`。空 DataFrame 不能区分「没有信号」和「没有数据」，所以调用方必须看 status。份额变化只是**代理**：份额上升可能是申购，也可能是拆分/分红，报告里不会把它写成「资金流入」。

**为什么不直接进合成得分**：Phase 2 的教训是「先测准，再决定投不投人」。资金流因子需要至少 60 个快照才谈得上 IC 评估；在此之前把它塞进 composite，只会让今天的信号被一天的行业资金流左右。因此资金流因子目前是**研究报告**，不进 `composite`；新闻叠加是唯一会改变分数的 Phase 5 组件（有界、可解释）。

### 2.2 新闻叠加（`finagent/news/`）

流程：`data/news/<as_of>.json` → PIT 过滤 → 映射到 ETF → 有界调整。

输入 schema：

```json
{
  "as_of": "2026-11-05",
  "source": "week3",
  "items": [
    {
      "title": "央行宣布降准 0.5 个百分点",
      "published_at": "2026-11-05T09:30:00+08:00",
      "sectors": ["银行", "证券"],
      "themes": ["降准"],
      "symbols": ["511010"],
      "sentiment": 0.6,
      "source": "财联社"
    }
  ]
}
```

- `sentiment` 必须有限，读入时裁剪到 `[-1, 1]`；缺失/非数字的条目被丢弃并计数。
- `published_at` 晚于 `as_of` 收盘日的条目被丢弃并计数（**PIT**）。
- 映射通道：`symbols` 直接命中；`sectors` 命中 ETF 的 `flow_sectors` / `sector` / `eastmoney_sector`；`themes` 通过 `configs/news_map.yaml` 展开成板块/标的/类别。
- 一条新闻匹配不到任何 ETF 时计数为 unmatched，不进入任何类别均值。
- 每个 ETF 的 `news_score` = 匹配新闻 `sentiment` 的均值（再裁剪到 `[-1,1]`）。

调整公式（`apply_news_overlay`）：

```text
contribution = clip(weight × news_score, ±max_abs)      # 默认 weight=0.20, max_abs=0.30
composite_after = composite_before + contribution
```

只调整**最新一天**的分数；历史分数保持可由因子复现。输出里每个变动都有 `composite_before / contribution / composite_after / n_items / titles`。

### 2.3 降级与标注

`signals` JSON 新增：

```json
"overlays": {
  "news": {
    "name": "news", "available": false, "applied": false,
    "reason": "no news file at data/news/2026-11-05.json",
    "weight": 0.2, "max_abs": 0.3, "contributions": []
  }
}
```

`flows` JSON（`--json`）包含五个源的 `SourceStatus` 与各因子的截面值。任何报告引用 Phase 5 数字时，都必须同时说明该源是否可用。

## 3. 验收对照

| 验收项 | 证据 |
|---|---|
| 缺少任一数据源时链路降级并标注 | `tests/test_flows.py::test_one_snapshot_is_not_a_flow_trend`、`test_flows_report_names_every_missing_source`；`tests/test_news_overlay.py::test_missing_news_file_degrades_with_a_reason`、`test_file_with_no_usable_items_explains_what_was_dropped`、`test_pipeline_reports_a_missing_overlay_instead_of_guessing` |
| 新闻叠加对分数的影响可解释 | `test_overlay_is_bounded_changes_only_the_latest_day_and_reports_its_size`、`test_overlay_cap_applies_before_the_score_moves`、`test_pipeline_applies_news_to_the_reported_score`（composite 变化 = contribution） |
| PIT | `test_future_headlines_are_not_usable`；资金流快照 > as_of 被丢弃（`test_flow_scores_use_accumulated_snapshots_and_respect_as_of`） |
| 板块 → ETF 映射 | `test_sectors_and_themes_reach_etfs` |

Phase 5 完成时全量测试 207 passed；Phase 6 之后为 225。

## 4. 复现

```bash
python -m finagent.cli flows --date 2026-11-05
python -m finagent.cli flows --date 2026-11-05 --json
python -m finagent.cli signals --date 2026-11-05 --news data/news/2026-11-05.json --news-weight 0.2
```

### 4.1 真实缓存上的叠加演示（`write=False`，不写盘）

`signals --news` 会写信号文件并追加账本；只想验证叠加本身时，用 API 跑一份临时新闻：

```python
import json, pathlib, tempfile
from finagent import config
from finagent.data.panel import as_date
from finagent.data.universe import load_universe
from finagent.factors import DEFAULT_FACTORS, load_close_panel
from finagent.news import apply_news_overlay, load_news, load_news_map, news_scores
from finagent.research.report import MIN_SYMBOLS, factor_snapshot
from finagent.signals.pipeline import run_signal_pipeline
from finagent.signals.score import composite_scores

day = as_date("2026-11-05")
universe = load_universe(config.CONFIG_DIR / "universe.yaml")
close = load_close_panel(config.CACHE_DIR, universe.symbols(day), day)
factors = factor_snapshot(close, list(DEFAULT_FACTORS), min_obs=MIN_SYMBOLS)
scores = composite_scores(factors)

news = {"items": [
    {"title": "半导体设备订单超预期", "published_at": "2026-11-05T09:00:00+08:00",
     "sectors": ["半导体"], "sentiment": 0.8},
    {"title": "人工智能政策落地", "published_at": "2026-11-05T10:30:00+08:00",
     "themes": ["人工智能"], "sentiment": 0.5},
    {"title": "券商两融收紧", "published_at": "2026-11-05T11:00:00+08:00",
     "sectors": ["证券"], "sentiment": -0.6},
    {"title": "明天的消息", "published_at": "2026-11-06T09:00:00+08:00",
     "symbols": ["510300"], "sentiment": 1.0},          # 应被 PIT 丢弃
]}
path = pathlib.Path(tempfile.mkdtemp()) / "news.json"
path.write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")

loaded = load_news(path, day)                          # dropped_future == 1
frame, diag = news_scores(loaded, universe, day, mapping=load_news_map())
adjusted, contrib = apply_news_overlay(scores, frame, weight=0.20, max_abs=0.30)
result = run_signal_pipeline(universe, as_of=day, cache_dir=config.CACHE_DIR,
                             news_path=path, write=False)
```

实测（2026-11-05，50 只有分数）：

| symbol | news_score | contribution | composite before → after | 命中方式 |
|---|---|---|---|---|
| 159516 | +0.8 | +0.16 | -1.98 → -1.82 | `sectors: 半导体` |
| 512480 | +0.8 | +0.16 | -1.04 → -0.88 | `sectors: 半导体` |
| 588170 | +0.8 | +0.16 | -2.28 → -2.12 | `sectors: 半导体` |
| 512880 | -0.6 | -0.12 | +0.27 → +0.15 | `sectors: 证券` |

- 4 条新闻：1 条日期在未来被丢弃，2 条命中 ETF，1 条（人工智能主题）在池内没有对应 `flow_sectors` 的标的，计为 unmatched，不进入任何均值
- 其余 **46 只标的变化严格为 0**；只有 `as_of` 当天被改
- `|after − before − contribution| = 1.11e-16`（浮点误差），限幅 0.30 未触发
- 叠加前后都是 **15 条信号**，没有标的跨越 `min_composite=0.25`——±0.16 的调整不足以改变结论，这正是「有界」的意义

## 5. 学习笔记（这一阶段值得记住的东西）

这一节不是给「验收」看的，是以后回来看代码时先读的东西：为什么这样做、坑在哪、下次接新数据源时哪些决定可以照抄。

### 5.1 这一阶段解决的不是「加因子」，而是「加不上时怎么办」

Phase 5 的任务定义里有两个词决定了实现：**缺源降级**、**有界可解释**。免费源上的资金流数据本来就是残缺的（只有当日截面、份额有滞后、净值接口不稳定），所以真正的工程问题是：数据不全时，系统怎么保持诚实。只有三种选择：

| 做法 | 后果 |
|---|---|
| 静默丢掉这个因子 | 报告看起来完整，实际少了一半信息，读的人不知道 |
| 缺数据时回退到最近一天 | 报表好看，但 PIT 失守，回测会骗自己 |
| 返回状态、在报告里写明原因、分数不动 | 本项目采用 |

这就是 `SourceStatus` 的由来：`frozen dataclass(name, available, reason, n_records, first_date, last_date)`，每个 loader 返回 `(frame, status)`。**空 DataFrame 不能区分「没有信号」和「没有数据」**，所以调用方必须看 status，而不是看 `.empty`。

### 5.2 快照 → 趋势：累积型数据源的成本

`sector_flow_rank` 只有「今天」的行业资金流，没有历史接口。项目没有去买数据，也没有拿当日截面冒充 5 日累计，而是**让每天的采集多写一个 parquet**（`data/cache/sector_flow_rank/<date>.parquet`），再由 `load_sector_flow_history` 把 ≤ `as_of` 的文件拼起来。

代价是时间：因子第一次可用要等 5 个交易日，IC 评估要等 60 个快照。

学习点：

- 数据的历史深度可以「从现在开始积累」，但**只能向前积累**。任何依赖历史的因子，上线日期 = 数据源接入日期 + 所需窗口。
- 所以接入新源的第一天，最大的产出不是因子，是「开始记录」。
- 这也是 `flows` 不进 cron 的原因：它只是读缓存，没有新信息；真正需要每天跑的是采集。

### 5.3 状态有三层：没文件 / 文件不够 / 够用

以 `sector_flow_rank` 为例：

1. 目录里没有 ≤ `as_of` 的文件 → `no snapshot on or before ...`
2. 有文件，但按日去重后不足 `window` 天 → `need 5 daily snapshots, have 1 (dates); collection accumulates one per trading day`
3. ≥ `window` 天 → `OK` + `first_date..last_date`

份额需要 ≥2 个快照，折溢价还多一个条件：同一天既有收盘又有净值。云端和本地同一天跑出的 MISSING 原因不同（缓存里的文件数不同），恰好证明这些句子是**算出来的**，不是写死的。这是「标注」和「敷衍」的分界线：原因必须来自数据本身。

### 5.4 PIT 不是一个函数，是一串决定

新闻的 PIT 具体化为四件事：

- 文件名就是 `as_of`，但条目可能跨日 → **逐条**看 `published_at`，不信任文件名
- 带时区的时间先转成本地时间再比日期；解析失败算 `dropped_invalid`，不猜
- 晚于 `as_of` 的条目丢弃并**计数**（`dropped_future`），报告里能看到丢了几条
- 没有 `published_at` 的条目当前按「可用」处理（很多源只有日期）。这是有意的宽松，但必须写进文档，否则以后会变成隐性前视

学习点：PIT 的正确性靠「丢弃 + 计数」，不靠「相信来源」。

### 5.5 映射比模型更容易出错

新闻 → ETF 有三条通道，硬度依次递减：

| 通道 | 写法 | 说明 |
|---|---|---|
| `symbols` | ETF 代码 | 最硬，新闻直接点名标的 |
| `sectors` | 同花顺行业名 | 与 `universe.yaml` 的 `flow_sectors` 同一套词表 |
| `themes` | `configs/news_map.yaml` | 人工词表，展开成 sectors / symbols / categories |

两个容易忽略的细节：

- 一条新闻匹配不到任何 ETF → 记为 unmatched，**不进入任何均值**（否则会把「无关」稀释成 0）
- 一个 theme 映射到很宽的类别 → 所有标的同向加分，**类别中性化之后等于没加**

学习点：NLP 的上限由词表决定。先把「板块名 ↔ ETF」对齐，再谈模型；映射表要保持短，它本质是人工先验，越长越像过拟合。

### 5.6 有界叠加：为什么是 clip 而不是乘

```text
contribution = clip(weight × news_score, ±max_abs)     # 默认 0.20 / 0.30
```

四个决定各自对应一个失败模式：

| 决定 | 如果反过来会怎样 |
|---|---|
| 用加法，不用乘法 | composite 是 z 分数的均值，量纲就是「标准差」；乘法会让 0 分附近的标的永远不动 |
| 用 `clip` 限幅，不整体缩放 | 单条极端新闻（sentiment=1）最多改 0.30，不会把一个 SHORT 直接翻成 LONG |
| 只调整最新一天 | 改历史分数就无法用因子复现，也无法归因 |
| 每个变动输出 before / contribution / after / 前 3 条标题 | 可解释 = 能逐项对上账；测试断言的就是 `after − before == contribution` |

学习点：任何「让分数变好看」的调整，都要能回答三个问题——改了多少、为什么改、能不能撤销。

### 5.7 为什么资金流因子不进 composite

不是因为没写完，而是顺序：**先测准，再决定投不投人**（Phase 2 的教训）。门槛写死在文档里：≥60 个快照 + 类别中性 IC 检验通过。在此之前把一天的行业流向塞进得分，等于用一个分布未知的变量去扰动一个已经测过（虽然是否定的）的分数。

学习点：新因子的默认状态是「观察」，不是「启用」。

### 5.8 代码地图

| 文件 | 职责 | 关键函数 |
|---|---|---|
| `finagent/data/sources.py` | 统一状态对象 | `SourceStatus.missing / ok / to_dict` |
| `finagent/flows/sector.py` | 行业资金流累积与截面 | `load_sector_flow_history`、`sector_flow_scores`、`flow_factor_scores`、`market_flow_context` |
| `finagent/flows/etf.py` | 份额变化 / 折溢价 | `load_share_snapshots`、`share_change_scores`、`load_nav_history`、`premium_discount_scores` |
| `finagent/flows/report.py` | 汇总与终端表格 | `build_flows_report`、`format_flows` |
| `finagent/news/overlay.py` | PIT、映射、有界叠加 | `load_news`、`news_scores`、`apply_news_overlay` |
| `configs/news_map.yaml` | 主题词表 | `themes: {sectors, symbols, categories}` |
| `finagent/signals/pipeline.py` | 叠加接入信号 | `run_signal_pipeline(..., news_path=...)` |
| `finagent/cli.py` | 入口 | `flows`、`signals --news` |
| `tests/test_flows.py`、`tests/test_news_overlay.py` | 降级与可解释性 | 14 条测试 |

建议阅读顺序：`data/sources.py` → `flows/sector.py` 的 `load_sector_flow_history`（看三层状态）→ `news/overlay.py` 的 `load_news`（看 PIT）→ `apply_news_overlay`（看有界叠加）→ `signals/pipeline.py` 的叠加段（看怎么接入而不破坏原有分数）。

### 5.9 常见错误清单

- 用空 DataFrame 表示「没有数据」，调用方无法区分「有数据但没信号」
- 缺数据时回退到最近一天：报表完整，回测有前视
- 用当日资金流截面当「近 5 日趋势」
- 新闻只按文件日期过滤，不看 `published_at`
- 叠加用乘法（量纲错），或只对总和做 clip（单条仍可爆）
- 改历史分数：无法复现、无法归因
- 把「份额增加」直接写成「资金流入」（还可能是拆分/分红）
- 因为「有资金流数据」就把一天的流向写进 composite

### 5.10 可以自己动手的练习

1. 造 6 天假快照跑 `sector_flow_scores(window=5)`，看第一天为什么没有值（滚动求和的起点在哪里）
2. 把 `news_map.yaml` 的「人工智能」改成映射 `categories: [thematic]`，观察类别中性化后它是否还有区分度
3. 给 `apply_news_overlay` 加一个 `sector_neutral=True` 选项（叠加后再按类别减均值），测试 `after − before` 是否还等于 `contribution`，想清楚可解释性该怎么重新定义
4. 把 `SourceStatus` 换成抛异常，重跑 `flows`，体会为什么「状态优先」比异常更容易写出完整报告

## 6. 下一步（按价值排序）

1. **让采集继续累积**：cron 的 18:30 采集已经在写 `sector_flow_rank`，不额外加任务。攒到 ≥5 个快照后 `flows` 自动给出 `sector_flow` 截面；攒到 ≥60 个再做 IC/ICIR 与类别中性检验，通过之前不进 composite。
2. **接入 week3 新闻导出**：把 `week3` 的 `FinancialSignal` 输出转成上面的 JSON（`title / published_at / sectors / sentiment`），放到 `data/news/<date>.json`。新闻提取的模型准确率不在本仓库的验收范围，本仓库只保证 PIT、映射和有界。
3. **修数据源**：`etf_nav` 的东财接口在本机不通（0 文件），`etf_scale_sse` 只覆盖 SSE 且当晚常缺。折溢价/份额因子在这两个源稳定之前只能保持 unavailable。
4. **不要**因为「Phase 5 有资金流」就宣称能预测：当前 0 个资金流因子有足够历史，Phase 4 的结论（类别中性 IC 0/9 显著）仍然适用于整个信号层。
