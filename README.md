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
| Phase 4 真实回测（T+1 / 成本 / CPCV / DSR / PBO） | 计划中 |
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

# 目标权重：类别预算 + 逆波动 + 有界因子倾斜
python -m finagent.cli portfolio --date 2026-11-05

# 预测账本：结算到期预测并输出命中率 / 校准
python -m finagent.cli ledger --date 2026-11-05 --settle

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

完整步骤（购买、防火墙、SSH 加固、时区、Docker、首次回补、cron、备份、回滚）见 [`deploy/tencent-lighthouse.md`](deploy/tencent-lighthouse.md)。云上已部署 Phase 1~3（采集、健康检查、因子报告、信号与预测账本），不含回测与 LLM。cron 五条：18:30 采集、18:40 因子、18:45 信号、19:10 健康检查、周日 03:00 备份。

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
5. `snapshot_id` 贯穿 data → factors → portfolio → backtest → signals → report，回测只读快照。
6. 因子口径：因子值保持原始方向（`direction` 只做解读），IC 是每日截面 Spearman 秩相关；信号 T 日收盘生成、T+1 执行，所以前向收益是 `P(t+1+h)/P(t+1)-1`；重叠收益用 Newey-West（滞后 `max(h-1, 4*(n/100)^(2/9))`）；9 个检验统一做 BH-FDR（q=0.10），不按单因子宣称显著。
7. 信号与账本口径：合成得分 = 各因子 `z_cs × direction` 的等权均值，**置信度是同向度（|加权和| / 加权绝对值和），不是概率**；每个类别最多 3 条信号，避免整张表被同一风险桶占满；每条信号必须带可机器校验的失效条件（得分翻向、主因子翻向、持有到期）。账本只追加不改写，**结算收益相对等权全池**而不是绝对收益——普涨行情里的多头不算本事。全部信号 `validated=false`，直到 Phase 4 回测给出证据。
8. 组合口径：类别预算固定（宽基 35 / 行业 25 / 跨境 15 / 主题 10 / 债券 10 / 商品 5），类别内按逆波动分配，因子得分只做 `[0.5, 1.5]` 的有界倾斜；单标的 12% 上限，类别上限取 `data/universe.py` 的护栏值。不使用优化器，每个权重都能一句话解释。

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
  signals/    # 结构化 QuantSignal、新闻映射（Phase 3/5）
  agent/      # LangGraph、报告、偏差自检（Phase 6）
  evals/      # golden set、引用/数字可追溯/格式指标
configs/      # universe / catalog / 后续 factors、ips、holdings
tests/        # 全部离线，不联网
scripts/      # 每日采集、健康检查、源探测
```

## 评测

`evals/golden_set.jsonl` 固定 10 条问题/报告样本，覆盖 CFA 概念、研究报告、数值可追溯三类。

- `python -m finagent.evals.run_evals --smoke`：离线校验 golden set 与指标本身，CI 门禁。
- `python -m finagent.evals.run_evals --answers answers.jsonl`：给真实回答打分；引用准确率 < 90% 或数字可追溯率 < 95% 直接失败。

## 免责声明

本项目仅用于个人研究与学习，输出为研究分析而非投资建议。历史回测不代表未来收益。
