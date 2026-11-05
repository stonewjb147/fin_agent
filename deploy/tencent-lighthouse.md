# 腾讯云 Lighthouse 部署 Runbook

目标：每天收盘后自动采集数据、检查新鲜度，失败时飞书告警。只部署 Phase 1（采集 + 健康检查），不含因子、回测、LLM。

预期耗时：首次 1.5~2 小时，其中镜像构建 2~4 分钟。

---

## 0. 本地准备：提交并推送代码

服务器通过 git 拉取代码，当前工作区里的 `finagent/`、`configs/`、`scripts/` 还是未跟踪文件，必须先提交：

```bash
cd /Users/stonewjb/fin_agent_projects
git add finagent configs scripts tests evals pyproject.toml Makefile README.md \
        Dockerfile .dockerignore .env.example docker-compose.yml deploy .gitignore
git commit -m "feat: 部署每日采集管道到腾讯云"
git push origin main
```

确认 `.env`、`data/`、`faiss_index/` 没有进入提交（`.gitignore` 已覆盖）。

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
```

`.env` 已在 `.gitignore` 和 `.dockerignore` 中，不会入库、不会进镜像。

---

## 5. 构建与离线自检

```bash
cd /opt/finagent
docker compose build                      # 4C8G 约 2~4 分钟
docker compose run --rm app date          # 必须是 CST +0800
docker compose run --rm app python -m pytest -q          # 52 passed
docker compose run --rm app python -m finagent.evals.run_evals --smoke
```

构建失败先看内存：`free -h`；4C8G 一般不会 OOM，若曾降配到 2C2G 再补 swap。

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
# 预期：Datasets written: 68，Failures: 2（index_valuation/399006、etf_scale_sse）
# 记下输出的 Snapshot: snap-YYYYMMDD-xxxxxxxx

docker compose run --rm app python -m finagent.cli data-check
# 预期：OK=True errors=0 warnings=0

docker compose run --rm app python -m finagent.cli snapshot --id <上一步的 snapshot id>
# 预期：checksum verification: OK
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
crontab -l                            # 确认三条任务
```

- 18:30 周一~五：`collect_daily.py`
- 19:10 周一~五：`health_check.py --alert feishu`
- 周日 03:00：备份 snapshots/quality/configs，保留 8 周

**先手动演练一次**（不用等到明天）：

```bash
cd /opt/finagent
docker compose run --rm app python scripts/collect_daily.py >> logs/cron.log 2>&1; echo "exit=$?"
docker compose run --rm app python scripts/health_check.py --alert feishu; echo "exit=$?"
tail -50 logs/cron.log
```

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
docker compose run --rm app python -m pytest -q     # 通过再等下一次 cron
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
| 飞书没收到 | `.env` 的 app id/secret/chat id；先跑第 7 节的 `send_text` 测试 |
| 数据源全部超时 | `source_probe.json`；确认没有遗留 `HTTP_PROXY` 环境变量；必要时换地域 |
| 构建 OOM | 4C8G 基本不会；`free -h` 确认，若降配过就补 swap |
| 磁盘满 | `docker system prune -f`、清理旧 `backups/`、检查 `logs/cron.log` |

---

## 13. 备份与恢复

备份已在 cron 里：每周日 03:00 打包 `data/snapshots data/quality configs` 到 `backups/`，保留 56 天。

- **必须备份**：`data/snapshots`（血缘）、`data/quality`（质量/健康报告）、`configs`、`.env`（单独保管）。
- **不必备份**：`data/cache` 可由源重建；`faiss_index` 不在本次部署。
- 需要异地容灾时，把 `backups/` 同步到腾讯云 COS（`coscmd upload -r backups/ /finagent-backups/`）。

灾难恢复：新 Lighthouse → 第 2~5 节 → 解压备份 → `collect --start 2022-01-01` 重建缓存 → 装 cron。约 15 分钟。
