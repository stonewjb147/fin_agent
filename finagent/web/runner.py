"""Run the daily CLI steps from the web app.

The web UI never reimplements the pipeline: it shells out to the same entry
points cron uses, with the same interpreter and data directory, and shows the
combined output. Long steps are explicit about being slow.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finagent import config


@dataclass(frozen=True)
class Step:
    id: str
    label: str
    description: str
    args: tuple[str, ...]
    slow: bool = False
    group: str = "daily"


STEPS: tuple[Step, ...] = (
    Step(
        "collect",
        "采集数据",
        "联网抓取行情、估值与资金流，写入缓存和快照。可能需要几分钟。",
        ("scripts/collect_daily.py", "--end", "{date}"),
        slow=True,
    ),
    Step(
        "health",
        "健康检查",
        "检查新鲜度、空值与覆盖，写 health_<date>.json。放在风控和成长之前，"
        "否则它们只能看到昨天的健康结论。",
        ("scripts/health_check.py", "--date", "{date}"),
    ),
    Step(
        "factor",
        "因子报告",
        "重算因子面板与中性 IC / ICIR，只读缓存，不联网。",
        ("-m", "finagent.cli", "factor-report", "--date", "{date}"),
    ),
    Step(
        "signals",
        "结构化信号",
        "生成当日信号，先把到期预测结算，再追加预测账本。",
        ("-m", "finagent.cli", "signals", "--date", "{date}"),
    ),
    Step(
        "portfolio",
        "目标权重",
        "类别预算 + 逆波动分配 + 有界因子倾斜。",
        ("-m", "finagent.cli", "portfolio", "--date", "{date}"),
    ),
    Step(
        "risk",
        "风控判决",
        "独立复算硬/软约束；硬约束越线时命令返回非零。",
        ("-m", "finagent.cli", "risk", "--date", "{date}"),
    ),
    Step(
        "report",
        "研究报告",
        "证据约束的 LLM 报告；没有 key 或门禁失败时回退确定性模板。",
        ("-m", "finagent.cli", "report", "--date", "{date}"),
        slow=True,
    ),
    Step(
        "growth",
        "成长状态",
        "汇总流程、证据、风控与数据四个维度，写 growth_<date>.json。",
        ("-m", "finagent.cli", "growth", "--date", "{date}"),
    ),
    Step(
        "journal_review",
        "决策复盘",
        "把到期的人工决策按价格与等权全池对照；没有记录时为空操作。",
        ("-m", "finagent.cli", "journal", "--date", "{date}", "--review"),
        group="review",
    ),
    Step(
        "growth_review",
        "周期成长报告",
        "生成 review_<date>.md|json：结论、过程、证据、决策、风险、行动、学习卡。",
        ("-m", "finagent.cli", "growth", "--date", "{date}", "--review"),
        group="review",
    ),
)

STEP_BY_ID = {step.id: step for step in STEPS}

DAILY_ORDER = (
    "collect",
    "health",
    "factor",
    "signals",
    "portfolio",
    "risk",
    "report",
    "growth",
)

TIMEOUTS = {"collect": 1800, "report": 600, "growth_review": 300, "journal_review": 300}
DEFAULT_TIMEOUT = 900


def build_command(
    step_id: str, as_of: str, *, no_llm: bool = False
) -> list[str]:
    """The exact argv, with the current interpreter and project root."""
    step = STEP_BY_ID[step_id]
    args = [part.format(date=as_of) for part in step.args]
    if step_id == "report" and no_llm:
        args.append("--no-llm")
    return [sys.executable, *args]


def display_command(step_id: str, as_of: str, *, no_llm: bool = False) -> str:
    command = build_command(step_id, as_of, no_llm=no_llm)
    return shlex.join(command)


def run_step(
    step_id: str,
    as_of: str,
    *,
    no_llm: bool = False,
    data_dir: str | Path | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Run one step and return its exit code, combined output and duration."""
    command = build_command(step_id, as_of, no_llm=no_llm)
    env = os.environ.copy()
    env["FINAGENT_DATA_DIR"] = str(Path(data_dir or config.DATA_DIR))
    env["PYTHONUNBUFFERED"] = "1"
    limit = timeout or TIMEOUTS.get(step_id, DEFAULT_TIMEOUT)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=config.PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=limit,
            check=False,
        )
        code = completed.returncode
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        output = f"{stdout}{stderr}\n\n[超时] 超过 {limit} 秒仍未结束，已终止。"
    except OSError as exc:
        code = 127
        output = f"无法启动命令：{exc}"
    elapsed = time.monotonic() - started
    return {
        "step": step_id,
        "label": STEP_BY_ID[step_id].label,
        "command": display_command(step_id, as_of, no_llm=no_llm),
        "returncode": code,
        "ok": code == 0,
        "output": output.strip(),
        "elapsed": elapsed,
    }


__all__ = [
    "DAILY_ORDER",
    "STEPS",
    "STEP_BY_ID",
    "Step",
    "build_command",
    "display_command",
    "run_step",
]
