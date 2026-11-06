# Phase 6 使用手册

本手册讲**怎么用** Phase 6 的报告链路：跑命令、读产物、排故障、改配置、加证据。
设计取舍与学习笔记见 [`phase6_llm_report.md`](phase6_llm_report.md)。

适用范围：`finagent report`（本地与云端容器）、`data/reports/` 下的产物、DeepSeek 配置、
每日 cron。所有命令都在仓库根目录执行。

---

## 0. 速查卡

| 我想…… | 命令 |
|---|---|
| 用最新信号生成报告（走 LLM） | `python -m finagent.cli report` |
| 指定日期 | `python -m finagent.cli report --date 2026-11-05` |
| 不联网、只用确定性模板 | `python -m finagent.cli report --date 2026-11-05 --no-llm` |
| 换模型 | `python -m finagent.cli report --model deepseek-chat` |
| 输出到别的目录 | `python -m finagent.cli report --out /tmp/reports` |
| 终端同时看完整 JSON | `python -m finagent.cli report --json` |
| 检查 key 是否被容器读到 | `docker compose run --rm app python -c "from finagent.agent.llm import config_from_env as f; c=f(); print(c.configured, c.model)"` |
| 看某天为什么回退模板 | `python -c "import json; d=json.load(open('data/reports/report_2026-11-05.json')); print(d['mode'], d['fallback_reason'])"` |
| 跑 Phase 6 测试 | `python -m pytest -q tests/test_agent_report.py tests/test_agent_llm.py tests/test_evals_metrics.py` |
| 全量质量门禁 | `make check` |

报告产物固定为两个文件：

```
data/reports/report_<as_of>.md     # 正文，人读
data/reports/report_<as_of>.json   # 证据、门禁结果、回退原因，机器读
```

**报告是只读层**：只读 `data/signals`、`data/portfolio`、`data/quality`，只写 `data/reports`。
它不会改信号、权重、账本或 `validated` 状态。

---

## 1. 运行前检查

### 1.1 必需与可选输入

| 输入 | 路径 | 是否必需 | 缺失时 |
|---|---|---|---|
| 信号 | `data/signals/<as_of>.json` | **必需** | 直接报错，退出码 1 |
| 组合 | `data/portfolio/<as_of>.json` | 可选 | 组合段写「从略」 |
| 因子报告 | `data/quality/factor_report_<as_of>.json` | 可选 | 因子结论从略 |
| 健康检查 | `data/quality/health_<as_of>.json` | 可选 | 写「数据新鲜度未确认」 |
| 阶段评测 | `data/quality/phase_eval_<as_of>.json` | 可选 | 广度/回测数字从略 |

推荐顺序（也是 cron 的顺序）：

```bash
python -m finagent.cli collect --start 2022-01-01   # 18:30
python -m finagent.cli factor-report                # 18:40
python -m finagent.cli signals                      # 18:45
python -m finagent.cli portfolio                    # 18:47；写目标权重
python -m finagent.cli risk                         # 18:48；风控判决
python -m finagent.cli report                       # 18:50
```

只跑 `signals` 也能出报告，但组合、因子、回测段落会缺失；`missing` 字段会记录缺了哪些工件。

### 1.2 日期规则

- **不带 `--date`**：自动选 `data/signals/` 里文件名最大的日期（即最新信号）。
- **带 `--date`**：只检查该日期有没有信号文件；**不会**自动回退到上一交易日。
  周末/节假日请直接给最近一个有信号的交易日，否则报：
  `report: no signals for 2026-11-07; run `finagent signals --date 2026-11-07` first`
- 其他命令（`collect`、`signals`）会做交易日回退并打印提示，`report` 故意不猜：报告必须和
  一个真实存在的信号文件一一对应。

### 1.3 key 配置检查

不打印密钥的安全检查：

```bash
python -c "from finagent.agent.llm import config_from_env as f; c=f(); print('configured=', c.configured, 'model=', c.model, 'endpoint=', c.endpoint())"
```

容器内同理：

```bash
docker compose run --rm app python -c "from finagent.agent.llm import config_from_env as f; c=f(); print('configured=', c.configured, 'model=', c.model)"
```

`configured=False` 表示没读到 `DEEPSEEK_API_KEY`；这时报告仍会生成，只是 `mode=template`。

---

## 2. 命令参考

### 2.1 `report` 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--date YYYY-MM-DD` | 最新信号文件 | 报告日期，必须存在对应信号 |
| `--no-llm` | 关 | 跳过 LLM，直接用确定性模板 |
| `--model NAME` | `deepseek-chat` | 覆盖模型名；也可用环境变量 |
| `--out DIR` | `data/reports` | 输出目录；目录会自动创建 |
| `--json` | 关 | 打印完整 JSON（含证据表和 checks）到 stdout |

### 2.2 退出码

| 码 | 含义 |
|---|---|
| 0 | 报告已写出。**包括 LLM 失败后回退模板**——产物存在就算成功 |
| 1 | 没有信号文件、模板自身过不了门禁、或其他 `EvidenceError` / `ReportError` |

回退不是错误：`mode`、`fallback_reason` 会说明发生了什么。运维上应监控
`mode=template` 的比例，而不是退出码。

### 2.3 常用组合

```bash
# 复盘某天，终端直接看完整 JSON（前面几行仍是摘要，不是纯 JSON）
python -m finagent.cli report --date 2026-11-05 --json

# 要程序化读取，直接读落盘文件
python -c "import json; d=json.load(open('data/reports/report_2026-11-05.json')); print(d['checks'])"

# 离线/无 key 环境（服务器默认路径）
python -m finagent.cli report --date 2026-11-05 --no-llm

# 临时指定/切换模型，不改 .env（填你已开通的模型名）
python -m finagent.cli report --date 2026-11-05 --model deepseek-chat

# 批量补历史（逐日）
for d in 2026-11-03 2026-11-04 2026-11-05; do
  python -m finagent.cli report --date "$d" || break
done
```

同一天重复运行会覆盖同名 `.md` / `.json`，不追加、不产生副本。

### 2.4 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 没有就走模板 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点根地址 |
| `FINAGENT_LLM_MODEL` | `deepseek-chat` | 模型名（优先级高于 `DEEPSEEK_MODEL`） |
| `DEEPSEEK_MODEL` | — | 模型名的备用变量 |

读取顺序：**进程环境变量优先**；没有时才读 `.env`。`.env` 内同名键重复时，**后出现的生效**
（`load_env` 已按 dotenv 语义处理）。这条规则修过一次真实的 HTTP 401：文件里旧 key 在前、
新 key 在后，旧 loader 先到先得。

---

## 3. 一次运行发生了什么

```
data/signals + portfolio + quality
        │
        ▼
build_facts()         读工件，缺件记入 missing
        │
        ▼
build_evidence()      压成证据表（104 条），每个数字取整到显示精度
        │
        ▼
user_prompt()         证据表 + 五段结构 + 硬规则
        │
        ▼
DeepSeekClient        一次 HTTP 调用（temperature 0.2，max_tokens 4096）
        │
        ▼
verify_report()       结构 / 必需词 / 禁用词 / 引用 / 严格数字
        │
        ├─ 通过 ──────────────► 写 .md + .json（mode=llm）
        └─ 不通过 ─► repair_prompt 再试一次
                        ├─ 通过 ─► 写文件（attempts=2）
                        └─ 失败 ─► render_template() ─► 同一套门禁 ─► 写文件（mode=template）
```

耗时与成本：证据约 100 条、输入几千 token、输出一两千 token；本机/云端一次调用在数十秒量级。
`--no-llm` 是零网络、零成本路径。

---

## 4. 产物怎么读

### 4.1 Markdown 正文

五个二级标题必须齐全。prompt 要求按下列顺序，门禁当前只校验「是否出现」，不校验顺序：

```
## 结论
## 信号
## 组合
## 数据与限制
## 证伪条件
```

正文里的每个数字后面应跟 `[snap:<证据ID>]`。引用是给人复核用的：拿 ID 去 JSON 的
`evidence.items` 里搜，能直接看到标签、显示值和来源工件。

### 4.2 JSON 字段

| 字段 | 含义 |
|---|---|
| `as_of` | 报告日期 |
| `mode` | `llm` 或 `template` |
| `model` | 实际使用的模型；模板模式为 `null` |
| `attempts` | LLM 调用次数（1 或 2）；模板模式为 0 或失败前的次数 |
| `fallback_reason` | 成功为 `null`；否则说明原因 |
| `prompt_sha256` | system + user prompt 的指纹，用于复现/比对 |
| `checks.passed` | 是否通过全部门禁 |
| `checks.failures` | 失败项列表（人读） |
| `checks.format.missing` | 缺失的标题 |
| `checks.citation` | `cited` / `valid` / `invalid` |
| `checks.must_include_missing` | 缺失的必需词组 |
| `checks.forbidden_hits` | 命中的禁用词 |
| `checks.numeric` | 通用数字评测（95% 预算、1% 容差） |
| `checks.numeric_strict` | **报告真正使用的严格门禁**（100%） |
| `risk` | Phase 7 风控判决（status / counts / checks / validation）；没有 risk 工件时为 `null` |
| `evidence.items` | 证据表：id / label / value / unit / note |
| `sources` | 各工件实际读取路径 |
| `missing` | 缺失的可选工件 |
| `files` | 写出的 md/json 路径 |
| `generated_at` | 生成时间（本地时区） |
| `text` | 正文副本 |
| `text_path` | 正文路径 |

**注意**：`checks.numeric` 和 `checks.numeric_strict` 同时存在。前者是评测套件的通用指标，
允许 5% 不可追溯；后者要求每个数字都可追溯。`checks.passed` 只有在后者也为 0 时才为真。

### 4.3 一分钟判断报告是否可信

依次看四个字段：

```python
import json
d = json.load(open("data/reports/report_2026-11-05.json"))
assert d["checks"]["passed"] is True
assert d["checks"]["citation"]["valid"] == d["checks"]["citation"]["cited"]
assert d["checks"]["numeric_strict"]["untraceable"] == []
print(d["mode"], d["fallback_reason"])
```

四条都满足，才值得读正文。`mode=template` 不代表报告有问题，代表这次没有 LLM 参与。

### 4.4 三种典型回退

```json
{"mode": "template", "fallback_reason": "DEEPSEEK_API_KEY not configured"}
```

```json
{"mode": "template", "attempts": 2,
 "fallback_reason": "LLM output rejected after 2 attempt(s): untraceable numbers: [300.0]"}
```

```json
{"mode": "template", "fallback_reason": "LLM unavailable: LLM returned HTTP 401"}
```

---

## 5. 日常运行

### 5.1 cron

服务器用 `deploy/crontab.example`，报告在 18:50（信号 18:45 之后）：

```cron
50 18 * * 1-5 cd /opt/finagent && /usr/bin/docker compose run --rm app python -m finagent.cli report >> logs/cron.log 2>&1
```

完整顺序：18:30 采集 → 18:40 因子 → 18:45 信号 → 18:47 组合 → 18:48 风控
→ 18:50 报告 → 19:10 健康检查；周日 03:00 备份（含 `data/reports`）。
主机时区必须是 Asia/Shanghai。

### 5.2 每天看什么

```bash
tail -100 logs/cron.log | grep -A 6 "Report for"
python -c "import json,glob; \
  [print(p, json.load(open(p))['mode'], json.load(open(p))['fallback_reason']) \
   for p in sorted(glob.glob('data/reports/report_*.json'))[-5:]]"
```

关注三件事：

1. 最近一天有没有生成报告；
2. `mode` 是否长期是 `template`（key/网络/门禁问题）；
3. `checks.passed` 是否仍为 `true`。

### 5.3 补跑与重建

```bash
# 某天漏跑
docker compose run --rm app python -m finagent.cli report --date 2026-11-05

# 换了模型或改了口径，重建最近 10 天
for d in $(ls data/signals | tail -10 | sed 's/\.json$//'); do
  docker compose run --rm app python -m finagent.cli report --date "$d"
done
```

### 5.4 保留与备份

报告是研究记录，建议长期保留。现有周备份已包含 `data/reports`；如果手动清理，
至少保留与预测账本结算周期（20 个交易日）相当的历史，方便回看当时的判断。

---

## 6. 门禁与失败信息

### 6.1 规则

| 门禁 | 规则 | JSON 位置 |
|---|---|---|
| 五段结构 | 五个二级标题全部出现（prompt 要求顺序固定；门禁当前只检查是否出现） | `checks.format.missing` |
| 必需词组 | `validated=false`、`存续偏差`、`不构成投资建议`；风控 `blocked` 时另需 `风控阻断` | `checks.must_include_missing` |
| 禁用词 | `稳赚`、`必涨`、`保证收益`、`推荐买入`、`建议买入`、`满仓`、`抄底` | `checks.forbidden_hits` |
| 引用 | 至少 10 处，且每个 ID 都在证据表里 | `checks.citation` |
| 严格数字 | 每个数字按所写小数位四舍五入后等于某个证据值 | `checks.numeric_strict` |

### 6.2 「严格数字」到底怎么判

```python
decimals = 正文中该数字的小数位数
通过 ⟺ 存在证据值 v，使 round(v, decimals) == 正文写的数
```

例子（假设证据值 `14.78`）：

| 正文写法 | 判定 | 原因 |
|---|---|---|
| `14.78%` | ✅ | 精确相等 |
| `14.8%` | ✅ | `round(14.78, 1) = 14.8` |
| `15%` | ✅ | `round(14.78, 0) = 15` |
| `14.781%` | ❌ | 多写了证据没有的精度 |
| `14.9%` | ❌ | 与任何证据值都不等 |

所以规则不是「必须逐字一致」，而是「不得发明精度」；少写精度允许，多写不允许。

### 6.3 标识符不算数字

日期、ETF 代码、产品名、因子名、策略名会在抽数字前被掩码：

- `2026-11-05`、`2026/11/05`、`2026年11月5日`、`20261105` → 日期；
- `510300` 等六位代码 → `ignore_values`；
- `沪深300ETF`、`momentum_20`、`hs300_buyhold` → `ignore_terms`。

新增一类产物时，如果它的名字里带数字，**必须把名字加进 `ignore_terms`**，否则会误伤。
历史上第一次真实运行就是被 `hs300_buyhold` 里的 `300` 拦下的。原则：**修掩码，不放宽数字规则**。

### 6.4 失败后的行为

1. 第一次不合格 → 把失败列表 + 上一版发回去，要求重写全文（`attempts=2`）；
2. 第二次仍不合格 → 回退模板，`fallback_reason` 记录失败项；
3. 模板也过不了门禁 → 抛 `ReportError`，不写文件（这是代码 bug，不是内容问题）。

重试只做一次：继续重试只会增加延迟和成本，还会让「今天有没有报告」变成随机事件。

---

## 7. 排障手册

| 现象 / 信息 | 根因 | 处理 |
|---|---|---|
| `no signals for <date>` | 该日期没有信号文件 | 先跑 `signals --date <date>`；或换一个有信号的交易日 |
| `DEEPSEEK_API_KEY not configured` | 容器没读到 key | 检查 `.env` 是否有该行、是否在 `env_file` 里；用 §1.3 的命令确认 `configured=True` |
| `LLM returned HTTP 401` | key 过期、抄错，或 `.env` 里旧 key 在前 | 用「长度 + SHA-256 前缀」比对，不打印 key；只保留一条有效行；轮换后重跑 |
| `request failed: ConnectionError` / `Timeout` | 出网失败或超时（默认 90s） | 先确认端点可达：裸 POST 返回 401 说明网络通、只差鉴权；检查代理/防火墙 |
| `LLM returned HTTP 429` | 限流/余额 | 降低触发频率；确认账户余额；回退模板仍会产出 |
| `untraceable numbers: [...]` | 模型写了证据表外的数字或多写精度 | 看列表里的数字：若是真实指标，补进证据表；若是模型推算，保持门禁并让它回退 |
| `missing sections: [...]` | 输出被截断或漏标题 | 确认 `max_tokens=4096`、prompt 仍限制 900 汉字；`format.missing` 会列出缺哪段 |
| `invalid citations: [...]` | 引用不存在的证据 ID | 模型抄错 ID；检查证据表是否变化；模板不受影响 |
| `only N citation(s), need at least 10` | 引用太少 | 模型写得太短/引用不足；repair prompt 会要求重写 |
| `missing required terms: [...]` | 漏了 `validated=false` / `存续偏差` / `不构成投资建议` | repair prompt 会强调；连续出现就检查 system prompt 是否被改坏 |
| `forbidden terms: [...]` | 出现买卖建议/收益承诺词 | 这是门禁在正常工作；不要为了通过而删词表 |
| `deterministic template failed its own gates` | 模板代码或证据表有 bug | 跑 `pytest tests/test_agent_report.py`；检查新增证据的单位/精度 |
| 报告里组合段是「从略」 | 没跑 `portfolio` | 跑 `python -m finagent.cli portfolio --date <date>` 后重建 |
| 报告里因子/回测段缺失 | 缺 `factor_report` / `phase_eval` | 跑对应命令；`missing` 字段会列出 |
| 同一天重复跑，文件被覆盖 | 设计如此 | 需要留档就先复制到别处；周备份保留历史 |

### 7.1 401 的安全排查法

不要打印 key。用指纹比对：

```bash
# 本机
python -c "
import hashlib
from pathlib import Path
for i, l in enumerate(Path('.env').read_text().splitlines(), 1):
    if l.strip().startswith('DEEPSEEK_API_KEY='):
        k = l.split('=', 1)[1].strip().strip('\"\'')
        print(i, len(k), k.startswith('sk-'), hashlib.sha256(k.encode()).hexdigest()[:12])
"
```

服务器上同理（在容器外读 `.env` 或进容器读环境变量）。比较「长度 + 前 12 位哈希」即可定位
哪条是旧 key，不需要看到明文。

### 7.2 网络可达性

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 \
  -X POST https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" -d '{"model":"deepseek-chat","messages":[]}'
```

返回 `401` = 域名可达、缺鉴权（正常）；超时/连接失败 = 出网问题。

---

## 8. 安全与密钥

- key 只放在 `.env`，`.env` 已被 `.gitignore` 排除；仓库是公开的，**永远不要提交**。
- key 只出现在 `Authorization: Bearer ...` 请求头；不写日志、不写报告 JSON、不进镜像。
- 报告 JSON 里没有 key；`prompt_sha256` 只是提示词指纹。
- 轮换：改 `.env` → `chmod 600 .env` → 重跑 `report`，不需要重建镜像。
- 怀疑泄露：先在供应商侧吊销/轮换，再检查 `.env` 是否被提交过；不要只删文件了事。
- 不要把 key 发给助手、写进 issue、贴进聊天记录或截图。

---

## 9. 扩展指南

### 9.1 新增一条证据

1. 在 `finagent/agent/evidence.py::build_evidence` 里 `add(...)`：
   - ID 用稳定、可读的命名（见附录）；
   - 值先换算成正文要用的单位（百分比就乘 100），再按显示精度取整；
   - 缺失值传 `None`，`add` 会自动跳过，不要用 0 代替。
2. 如果标签/名称里含数字，把名称加入 `ignore_terms`（见 §6.3）。
3. 在 `template.py` 里用 `_show(bundle, "<ID>")` 引用，正文只写一次单位。
4. 补测试：ID 唯一、模板能过门禁、数字可追溯。
5. 重跑 `pytest` 与一次真实报告。

### 9.2 改门禁

门禁常量集中在 `finagent/agent/prompts.py`：

```python
REQUIRED_SECTIONS = [...]
MUST_INCLUDE = [...]
FORBIDDEN = [...]
MIN_CITATIONS = 10
```

改完必须同步 `SYSTEM_PROMPT`（告诉模型规则）和测试。**不要**通过下调
`strict_untraceable` 来让某份报告通过；先判断是证据缺失还是模型越界。

### 9.3 换模型或供应商

- 换模型：`--model` 或 `FINAGENT_LLM_MODEL` / `DEEPSEEK_MODEL`。
- 换供应商：实现 `LLMClient` 协议即可（一个 `model` 属性 + `complete(system, user) -> str`），
  在 `generate_report(client=...)` 注入。DeepSeek 客户端本身就是 OpenAI 兼容 HTTP，
  换 base URL 通常够用。
- 客户端约定：失败抛 `LLMError`，由报告层统一回退；不要在客户端里重试或吞异常。

### 9.4 加一个报告章节

同时改三处，缺一不可：

1. `prompts.py::REQUIRED_SECTIONS` 与 `SYSTEM_PROMPT`；
2. `template.py` 的模板正文；
3. 测试里的结构断言。

只改 prompt 不改模板，会导致「LLM 通过、模板回退失败」——反过来也一样。

---

## 10. 验收清单

发布/改完代码后按顺序过一遍：

- [ ] `make check` 全绿（ruff + pytest + eval smoke）
- [ ] `report --no-llm` 通过，`mode=template`、`checks.passed=true`
- [ ] 有 key 时 `report` 通过，`mode=llm`、`attempts<=2`
- [ ] 无 key 时自动回退，`fallback_reason="DEEPSEEK_API_KEY not configured"`
- [ ] `citation.valid == citation.cited`
- [ ] `numeric_strict.untraceable == []`
- [ ] JSON 里没有 key、没有明文密钥字段
- [ ] 云端 `report` 与本地口径一致（同证据表、同门禁）
- [ ] cron 顺序正确（18:30 → 18:40 → 18:45 → 18:47 → 18:48 → 18:50 → 19:10）

---

## 11. 附录

### 11.1 证据 ID 命名规则

| 前缀 | 示例 | 含义 |
|---|---|---|
| `signals:<date>:` | `signals:2026-11-05:n_signals` | 当日信号计数/参数 |
| `ledger:<date>:` | `ledger:2026-11-05:n_pending` | 预测账本状态 |
| `signal:<symbol>:` | `signal:510300:composite` | 单标的合成得分/置信度 |
| `portfolio:<date>:` | `portfolio:2026-11-05:portfolio_vol_pct` | 组合指标、预算、暴露 |
| `holding:<symbol>:` | `holding:510300:weight_pct` | 单标的组合权重 |
| `factor:<date>:` | `factor:2026-11-05:n_significant` | 因子检验汇总 |
| `factor:<name>:h<h>:` | `factor:momentum_20:h20:ic_neutral` | 单因子单持有期 IC/q |
| `health:<date>:` | `health:2026-11-05:errors` | 数据健康检查 |
| `breadth:` | `breadth:n_eff` | 相关性调整后的有效广度 |
| `backtest:<strategy>:` | `backtest:policy_no_tilt:cagr_pct` | 回测年化/最大回撤 |
| `ledger:required_settled_5pct` | — | 命中率精度所需样本 |
| `ledger:precision_pct` | — | 命中率精度目标（5%） |

### 11.2 当前基线（2026-11-05）

| 项目 | 数值 |
|---|---|
| 证据条目 | 104 |
| 信号 | 15（看多 10、看空 5） |
| 组合持仓 | 49 |
| 因子检验 | 9 项，BH-FDR(q=10%) 后显著 0 项 |
| 账本 | 15 条预测、0 结算；±5% 精度约需 385 条结算 |
| 模板报告 | 51 处引用、51 个数字，0 不可追溯 |
| LLM 报告 | 75–81 处引用、77–86 个数字，0 不可追溯（采样有波动） |

这些数字随数据更新会变；门禁比例（100% 可追溯）不变。

### 11.3 相关文件

| 文件 | 用途 |
|---|---|
| `finagent/agent/evidence.py` | 证据表 |
| `finagent/agent/llm.py` | DeepSeek 客户端与环境配置 |
| `finagent/agent/prompts.py` | 提示词与门禁常量 |
| `finagent/agent/template.py` | 确定性模板 |
| `finagent/agent/report.py` | 生成、重试、门禁、落盘 |
| `finagent/evals/metrics.py` | 评测指标与 `strict_untraceable` |
| `tests/test_agent_report.py` | 报告链路测试（10） |
| `tests/test_agent_llm.py` | 客户端/环境测试（6） |
| `deploy/crontab.example` | 含 18:50 报告的 cron |
| `docs/phase6_llm_report.md` | 设计与取舍 |

### 11.4 术语

- **证据表（evidence bundle）**：正文允许使用的数字闭集，每条有稳定 ID。
- **回退（fallback）**：LLM 不可用或输出不合格时改用确定性模板。
- **严格数字门禁**：每个数字都必须能由证据值按书写精度四舍五入得到。
- **存续偏差**：股票池按当前存续标的构建，退市/未上市标的未完整纳入。
- **validated=false**：信号尚未被结算样本验证；报告不得把它写成已验证。
