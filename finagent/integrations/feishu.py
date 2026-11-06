"""Minimal Feishu bot client for operational alerts.

Credentials are read from the repository `.env` (never logged). Sending is
best-effort: a failed alert must not crash the collection job.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from finagent.config import PROJECT_ROOT

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing vars."""
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            values[key] = value  # a later duplicate wins, as in dotenv files
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _tenant_token() -> str | None:
    load_env()
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        return None
    resp = requests.post(
        _TOKEN_URL,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"feishu auth failed: code={payload.get('code')} msg={payload.get('msg')}")
    return payload.get("tenant_access_token")


def send_text(text: str, chat_id: str | None = None) -> bool:
    load_env()
    chat_id = chat_id or os.environ.get("FEISHU_CHAT_ID") or os.environ.get("FEISHU_MY_OPEN_ID")
    if not chat_id:
        return False
    token = _tenant_token()
    if not token:
        return False
    resp = requests.post(
        _MESSAGE_URL,
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}"},
        json={"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=10,
    )
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"feishu send failed: code={payload.get('code')} msg={payload.get('msg')}")
    return True
