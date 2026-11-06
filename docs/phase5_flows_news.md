# Phase 5：资金流与新闻叠加

实现日期 2026-11-06；数据截止 `as_of=2026-11-05`。

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
| 缺少任一数据源时链路降级并标注 | `tests/test_flows.py::test_one_snapshot_is_not_a_flow_trend`、`test_flows_report_names_every_missing_source`；`tests/test_news_overlay.py::test_missing_news_file_degrades_with_a_reason`、`test_pipeline_reports_a_missing_overlay_instead_of_guessing` |
| 新闻叠加对分数的影响可解释 | `test_overlay_is_bounded_changes_only_the_latest_day_and_reports_its_size`、`test_overlay_cap_applies_before_the_score_moves`、`test_pipeline_applies_news_to_the_reported_score`（composite 变化 = contribution） |
| PIT | `test_future_headlines_are_not_usable`；资金流快照 > as_of 被丢弃（`test_flow_scores_use_accumulated_snapshots_and_respect_as_of`） |
| 板块 → ETF 映射 | `test_sectors_and_themes_reach_etfs` |

全量测试 206 passed。

## 4. 复现

```bash
python -m finagent.cli flows --date 2026-11-05
python -m finagent.cli flows --date 2026-11-05 --json
python -m finagent.cli signals --date 2026-11-05 --news data/news/2026-11-05.json --news-weight 0.2
```

## 5. 下一步（按价值排序）

1. **让采集继续累积**：cron 的 18:30 采集已经在写 `sector_flow_rank`，不额外加任务。攒到 ≥5 个快照后 `flows` 自动给出 `sector_flow` 截面；攒到 ≥60 个再做 IC/ICIR 与类别中性检验，通过之前不进 composite。
2. **接入 week3 新闻导出**：把 `week3` 的 `FinancialSignal` 输出转成上面的 JSON（`title / published_at / sectors / sentiment`），放到 `data/news/<date>.json`。新闻提取的模型准确率不在本仓库的验收范围，本仓库只保证 PIT、映射和有界。
3. **修数据源**：`etf_nav` 的东财接口在本机不通（0 文件），`etf_scale_sse` 只覆盖 SSE 且当晚常缺。折溢价/份额因子在这两个源稳定之前只能保持 unavailable。
4. **不要**因为「Phase 5 有资金流」就宣称能预测：当前 0 个资金流因子有足够历史，Phase 4 的结论（类别中性 IC 0/9 显著）仍然适用于整个信号层。
