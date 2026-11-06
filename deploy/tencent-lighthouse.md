# 腾讯云 Lighthouse 部署 Runbook

目标：每天收盘后自动采集数据、产出因子报告与结构化信号、检查新鲜度，失败时飞书告警。已部署 Phase 1（采集 + 健康检查）、Phase 2（因子面板 + IC 报告）、Phase 3（结构化信号 + 预测账本 + 目标权重）、Phase 4（回测 + CPCV/PBO/DSR + `scripts/phase_eval.py` 评测）、Phase 5（资金流 / 份额 / 折溢价状态 + 有界新闻叠加）、Phase 6（证据约束的 LLM 报告 + 确定性回退）、Phase 7（风控硬/软约束 + `validated=false` 升级门槛）与 Phase 8–10（成长状态、决策日志、周期成长报告）。**回测、评测与 `flows` 是按需研究命令，不进 cron**——它们没有每日新增信息，还会长时间占满 CPU；行业资金流历史由 18:30 采集顺带累积（每天一个快照）。服务器上暂不放 `data/news/`，新闻叠加自动跳过并在信号 JSON 的 `overlays.news` 里标注原因。

预期耗时：首次 1.5~2 小时，其中镜像构建 2~4 分钟。

---

## 0. 本地准备：提交并推送代码

服务器通过 git 拉取代码，所以本地改动必须先提交并推送到 main：

```bash
cd /Users/stonewjb/fin_agent_projects
git add -A && git commit -m "..." && git push origin main
```

推送前确认 `.env`、`data/` 没有进入提交（`.gitignore` / `.dockerignore` 已覆盖）。**仓库是公开的**，不要提交服务器 IP、密钥或数据文件。

---

## 1. 购买与初始化

| 项目 | 选择 |
|---|---|
| 产品 | 轻量应用服务器 Lighthouse |
| 地域 | 上海 / 广州 / 北京（大陆访问东财、中证、同花顺最稳） |
| 镜像 | Ubuntu 22.04 LTS |
| 规格 | 4C8G，80GB SSD（内存充足，无需 swap；也为后续因子/回测留余量） |
| 时长 | 先买 1 个月验证，稳定后续费 |

**防火墙**（控制台 → 防火墙）：只保留 SSH 22，来源改为自己的出口 IP；删除 80/443 等默认规则。没有 Web 服务，**不需要域名和 ICP 备案**。

登录：

```bash
ssh root@<公网IP>
```

---

## 2. 创建部署用户与 SSH 加固

容器内的 `appuser` 是 uid 1000，最省事的是让部署用户也用 uid 1000。腾讯云 Ubuntu 镜像通常自带 `ubuntu`（uid 1000），可以直接用它；没有的话新建：

```bash
id ubuntu                     # 如果输出 uid=1000，就用 ubuntu，下面命令里的 finagent 全部替换成 ubuntu
# 或者：
adduser --uid 1000 --disabled-password --gecos "" finagent
usermod -aG sudo finagent
```

如果 1000 已被占用且你坚持用别的 uid，把 `.env` 里的 `FINAGENT_UID/FINAGENT_GID` 改成实际值即可，但注意容器内该 uid 没有 home 目录，个别库写 `~/.cache` 时可能报警。

# 把本地公钥装到 finagent 名下；没有的话先在本地 ssh-keygen -t ed25519
mkdir -p /home/finagent/.ssh
cp /root/.ssh/authorized_keys /home/finagent/.ssh/authorized_keys   # 若 root 已有公钥
chown -R finagent:finagent /home/finagent/.ssh
chmod 700 /home/finagent/.ssh
chmod 600 /home/finagent/.ssh/authorized_keys
```

先另开一个终端确认 `ssh finagent@<IP>` 能登录，再关闭密码登录：

```bash
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh
```

记下部署用户的 uid/gid，后面要写进 `.env`：

```bash
id -u finagent   # 例如 1001
id -g finagent
```

---

## 3. 系统：时区、Docker

```bash
timedatectl set-timezone Asia/Shanghai
date   # 应显示 CST +0800

# 4C8G 无需 swap。如果以后降到 2C2G，再补：
# fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile \
#   && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Docker（官方源）
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list

# 大陆拉取慢时，把官方源换成腾讯镜像后重试：
# sed -i 's|https://download.docker.com|https://mirrors.cloud.tencent.com/docker-ce|' \
#   /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker finagent
```

重新登录 `finagent`（或 `newgrp docker`）后验证：

```bash
docker run --rm hello-world
docker compose version
```

---

## 4. 拉代码、建目录、配密钥

```bash
sudo mkdir -p /opt/finagent
sudo chown finagent:finagent /opt/finagent
git clone https://github.com/stonewjb147/fin_agent.git /opt/finagent
cd /opt/finagent

mkdir -p data/cache data/snapshots data/quality logs backups
# 目录属主必须与 compose 里的 user 一致，否则容器内写 Parquet 会 PermissionError
chown -R "$(id -u):$(id -g)" data logs backups

cp .env.example .env
chmod 600 .env
vi .env
```

`.env` 至少填：

```ini
FEISHU_APP_ID=cli_...
FEISHU_APP_SECRET=...
FEISHU_CHAT_ID=oc_...
FINAGENT_UID=<上一步的 id -u>
FINAGENT_GID=<上一步的 id -g>

# 可选：Phase 6 报告。不填也能跑，只是固定回退到确定性模板。
DEEPSEEK_API_KEY=<你的 key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` 已在 `.gitignore` 和 `.dockerignore` 中，不会入库、不会进镜像。

---

## 5. 构建与离线自检

```bash
cd /opt/finagent
docker compose build                      # 4C8G 约 2~4 分钟
docker compose run --rm app date          # 必须是 CST +0800
docker compose run --rm app python -m pytest             # 254 passed
docker compose run --rm app python -m finagent.evals.run_evals --smoke
```

构建失败先看内存：`free -h`；4C8G 一般不会 OOM，若曾降配到 2C2G 再补 swap。

> 不要写成 `pytest -q`：`pyproject.toml` 里已有 `addopts = "-q"`，再加一个 `-q` 会变成 `-qq`，**汇总行（`254 passed`）会被吞掉**，只剩一屏点，看起来像没跑完。用 `pytest` 或 `pytest -q --no-header -rN`。

---

## 6. 源探测（关键，先做）

云上网络与本地不同：本地是被失效代理挡住 `push2*`，云上可能可达，也可能仍不可达。两种都能运行，但要记录：

```bash
docker compose run --rm app python scripts/probe_sources.py \
  --out data/quality/source_probe.json
```

云端实测 2026-11-05：**20/20 OK**（本机被失效代理挡住的 `push2*` 在云上可达）。打开 JSON 检查 `etf_hist_hfq`、`etf_nav`、`index_hist`、`index_value_csindex`、`sector_flow_rank_today`、`macro_*`、`bond_10y` 是否至少各有一条可用路径。失败项会由 provider 的 fallback 覆盖；若某个数据集所有路径都失败，先不要装 cron，把 JSON 留着排查。

---

## 7. 回补三年并验证

```bash
docker compose run --rm app python -m finagent.cli collect \
  --start 2022-01-01 --snapshots on
# 预期：Datasets written: 111，Failures: 3（index_valuation/399006、index_valuation/399330、etf_scale_sse）
# 这三项是已登记的数据缺口，不是 bug
# 记下输出的 Snapshot: snap-YYYYMMDD-xxxxxxxx

docker compose run --rm app python -m finagent.cli data-check
# 预期：OK=True errors=0 warnings=0

docker compose run --rm app python -m finagent.cli snapshot --id <上一步的 snapshot id>
# 预期：checksum verification: OK

docker compose run --rm app python -m finagent.cli factor-report --date 2026-11-05
# 实测：3 个因子 × 3 个持有期的 IC/ICIR/t/q 表格，17 秒跑完（无网络）

docker compose run --rm app python -m finagent.cli signals --date 2026-11-05
# 预期：LONG/SHORT 各若干条（每类最多 3 条），末尾提示 validated=false

docker compose run --rm app python -m finagent.cli portfolio --date 2026-11-05
# 预期：类别暴露等于政策预算（35/25/15/10/10/5），单标的 <= 12%

docker compose run --rm app python -m finagent.cli risk --date 2026-11-05
# 实测：status=warn / hard 15/15 / soft 10/11 / n_eff 2.64 < 3.0
# 产出 data/quality/risk_<date>.json；退出码 0=pass/warn，1=blocked

docker compose run --rm app python -m finagent.cli ledger --date 2026-11-05
# 预期：predictions=N，settled=0（首个结算要等满 20 个交易日）

docker compose run --rm app python -m finagent.cli flows --date 2026-11-05
# 实测（云端）：sector_flow_rank 只有 1 天快照 -> unavailable（从 2026-11-05 起每天累积一个）
# etf_scale_sse 只有 1 个快照（算不了变化）、etf_nav 只有 1 只同日净值 -> unavailable
# market_flow 可用；news 文件缺失 -> unavailable
# 三条资金流判定都是 MISSING，但每行都写明了缺什么——这就是「缺源降级」的验收
docker compose run --rm app python -m finagent.cli signals --date 2026-11-05
# 末尾应出现：news overlay: skipped — no news file at /app/data/news/2026-11-05.json
# 分数与 Phase 5 之前一致（叠加不可用不改分数）

docker compose run --rm app python -m finagent.cli report --date 2026-11-05 --no-llm
# 实测：Mode template / Gate PASS / Citations 51/51 / Numbers 51 checked, 0 untraceable
# 产出 data/reports/report_2026-11-05.md|json；不联网、不需要 key
docker compose run --rm app python -m finagent.cli report --date 2026-11-05
# 实测（云端已配置 key）：Mode llm (deepseek-chat, 1 attempt) / Gate PASS / Citations 75/75 / Numbers 77 checked, 0 untraceable
# 没有 key：Mode template + Fallback: DEEPSEEK_API_KEY not configured；JSON 里 fallback_reason 说明原因
# key 只在请求头，不进镜像/日志/报告；复制到过期 key 会 HTTP 401 并回退模板

docker compose run --rm app python -m finagent.cli growth --date 2026-11-05
# 实测：level=L2 证据积累期 / score=62/100 / Process 100 / Evidence 0 / Risk 70 / Data 100
# 产出 data/growth/growth_2026-11-05.json
docker compose run --rm app python -m finagent.cli growth --date 2026-11-05 --review
# 产出 data/growth/review_2026-11-05.md|json（一页结论、证据门槛、决策、风险、行动、学习卡）
docker compose run --rm app python -m finagent.cli journal --date 2026-11-05
# 没有人工记录时显示 entries=0；journal 只接受人写入，不生成决策

docker compose run --rm app python -m finagent.cli backtest --start 2023-01-01
# 实测：四个对照策略 + PBO/CPCV/DSR，约 30 秒，产出 data/reports/backtest_<date>.json|_daily.csv|_fills.csv
# 回测不进 cron：它是研究工具，数据变了重新跑一次即可

docker compose run --rm app python scripts/phase_eval.py --start 2023-01-01 --end 2026-11-05
# 实测：22/22 硬检查 + 4/4 信息项通过 + 价值表 + 成本敏感性 + 类别中性 IC/有效广度 + 分年 IC + 账本状态；本机约 130 秒（单核为主）
# 产出 data/quality/phase_eval_<date>.json；实测云端与本地除路径/快照 id 外逐字段一致
```

验证飞书（这一步会真的发一条消息）：

```bash
docker compose run --rm app python -c \
"from finagent.integrations.feishu import load_env, send_text; load_env(); print(send_text('[finagent] 云上部署测试'))"
```

---

## 8. 安装定时任务

```bash
cd /opt/finagent
crontab deploy/crontab.example       # 以当前部署用户安装
crontab -l                            # 确认十一条任务（含 18:50 报告、18:55 成长、19:05 决策复盘、周日 03:30 周报）
```

- 18:30 周一~五：`collect_daily.py`
- 18:38 周一~五：`health_check.py --alert feishu`。**必须排在风控和成长之前**：两者都读 `health_<date>.json`，文件缺失时风控只会记 info，当天的数据错误反而不会阻断
- 18:40 周一~五：`factor-report`（只读缓存，不联网）
- 18:45 周一~五：`signals`（先结算到期预测，再写当日信号并入账）
- 18:47 周一~五：`portfolio`（目标权重，只读缓存）
- 18:48 周一~五：`risk`（硬/软约束，写 `data/quality/risk_<date>.json`）
- 18:50 周一~五：`report`（有 `DEEPSEEK_API_KEY` 走 LLM，没有或调用失败写确定性模板，`fallback_reason` 记录原因）
- 18:55 周一~五：`growth`（成长状态；写 `data/growth/growth_<date>.json`）
- 19:05 周一~五：`journal --review`（到期的人工决策按价格复盘；没有记录时只打印空摘要）
- 周日 03:00：备份 snapshots/quality/factors/signals/predictions/portfolio/reports/growth/journal/configs，保留 8 周
- 周日 03:30：`growth --review --window 30`（写 `data/growth/review_<date>.md|json`）

**先手动演练一次**（不用等到明天）：

```bash
cd /opt/finagent
docker compose run --rm app python scripts/collect_daily.py >> logs/cron.log 2>&1; echo "exit=$?"
docker compose run --rm app python -m finagent.cli factor-report >> logs/cron.log 2>&1; echo "exit=$?"
docker compose run --rm app python -m finagent.cli signals >> logs/cron.log 2>&1; echo "exit=$?"
docker compose run --rm app python scripts/health_check.py --alert feishu; echo "exit=$?"
tail -50 logs/cron.log
```

### 网页界面（可选）

镜像里包含 Streamlit（`.[dev,web]`），web 服务复用同一个镜像，只监听服务器回环地址：

```bash
cd /opt/finagent
docker compose build
docker compose --profile web up -d web
docker compose --profile web ps
docker compose --profile web logs --tail=50 web
```

本机开隧道（不要把 8501 加到防火墙放行列表）：

```bash
ssh -L 8501:127.0.0.1:8501 ubuntu@<host>
# 浏览器打开 http://localhost:8501
```

页面只读取 `data/`；「运行流水线」会调用与 cron 相同的命令，运行日期可选。网页里录入的决策写入 `data/journal/entries.jsonl`，与 CLI 完全同一份文件。

更新代码后：`git pull`（或 bundle）→ `docker compose build` → `docker compose --profile web up -d web`。只重启 web 不会加载新代码，因为代码在镜像里。

---

## 9. 告警演练（可选但建议）

制造一次数据缺失，确认飞书能收到：

```bash
cd /opt/finagent
mv data/cache/etf_daily_hfq/510300.manifest.json /tmp/510300.manifest.json.bak
docker compose run --rm app python scripts/health_check.py --alert feishu; echo "exit=$?"
mv /tmp/510300.manifest.json.bak data/cache/etf_daily_hfq/510300.manifest.json
```

预期 exit=1 且飞书收到「数据健康检查失败」。

---

## 10. 重启与持久化验证

```bash
sudo reboot
# 重新登录后
systemctl status docker
crontab -l
cd /opt/finagent && ls data/cache | head && du -sh data
```

卷挂载不依赖容器生命周期；`docker compose down` 不会删 `./data`。

---

## 11. 日常运维

```bash
cd /opt/finagent

# 看最近一次任务输出
tail -100 logs/cron.log

# 手动补跑某一天
docker compose run --rm app python scripts/collect_daily.py --end 2026-11-05

# 强制忽略当日缓存重新取数
docker compose run --rm app python scripts/collect_daily.py --force

# 磁盘与镜像
df -h /; docker system df
```

更新：

```bash
cd /opt/finagent
git pull
docker compose build
docker compose run --rm app python -m pytest        # 通过再等下一次 cron
```

回滚：

```bash
git log --oneline -5
git checkout <上一个可用 commit>
docker compose build
```

每次构建后打一个 sha 标签便于回滚：

```bash
docker tag finagent:0.1.0 finagent:$(git rev-parse --short HEAD)
```

---

## 12. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `env file .env not found` | 第 4 节没做，`cp .env.example .env` 并填值 |
| 容器内写 Parquet `PermissionError` | `data/` 属主与 `.env` 的 `FINAGENT_UID` 不一致，`chown -R` 对齐 |
| `date` 显示 UTC | 主机时区没设，`timedatectl set-timezone Asia/Shanghai`；容器再看 compose 的 `TZ` |
| cron 没有任何输出 | `journalctl -u cron -n 50`；确认 PATH 与 `/usr/bin/docker` 路径 |
| 采集 exit 1 | `logs/cron.log` 里看 `failures`；coverage 缺口不算 error，error 才是问题 |
| `factor-report` / `signals` / `portfolio` exit 1 且提示 `panel ends ...; run collect first` | 18:30 的采集没成功（或还没跑完），当天缓存里没有数据。命令拒绝用前一天的数据生成标着今天的文件，先补跑采集即可 |
| 飞书没收到 | `.env` 的 app id/secret/chat id；先跑第 7 节的 `send_text` 测试 |
| 数据源全部超时 | `source_probe.json`；确认没有遗留 `HTTP_PROXY` 环境变量；必要时换地域 |
| 构建 OOM | 4C8G 基本不会；`free -h` 确认，若降配过就补 swap |
| 磁盘满 | `docker system prune -f`、清理旧 `backups/`、检查 `logs/cron.log` |

---

## 13. 备份与恢复

备份已在 cron 里：每周日 03:00 打包 `data/snapshots data/quality data/factors data/signals data/predictions data/portfolio data/reports data/growth data/journal configs` 到 `backups/`，保留 56 天。

- **必须备份**：`data/snapshots`（血缘）、`data/quality`（质量/健康/因子报告）、`data/factors`（因子面板）、`data/predictions`（预测账本，**不可重建**，丢了就再也没有当时的口径）、`data/signals`、`data/portfolio`、`data/reports`（报告正文与门禁结果）、`data/growth`（成长状态与周报）、`data/journal`（**人工决策记录，不可重建**）、`configs`、`.env`（单独保管）。
- **不必备份**：`data/cache` 可由源重建；`faiss_index` 不在本次部署。
- 需要异地容灾时，把 `backups/` 同步到腾讯云 COS（`coscmd upload -r backups/ /finagent-backups/`）。

灾难恢复：新 Lighthouse → 第 2~5 节 → 解压备份 → `collect --start 2022-01-01` 重建缓存 → 装 cron。约 15 分钟。
