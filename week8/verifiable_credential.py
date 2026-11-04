# ============================================
# 可验证凭证系统（W3C Verifiable Credential）
# 功能：签发、验证、存储决策凭证
# ============================================

import os, sys, json, hashlib, hmac
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from hermes_governor import GovernanceDecision, ConflictItem
from deterministic_rules import DeterministicRuleResult

class CredentialStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"

@dataclass
class VerifiableCredential:
    credential_id: str = ""
    governance_decision: Optional[GovernanceDecision] = None
    issuer: str = "CUFEI-Q-Master-Agent-v2.0"
    issued_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    expires_at: str = ""
    signature: str = ""
    status: CredentialStatus = CredentialStatus.ACTIVE

    def __post_init__(self):
        if not self.credential_id:
            self.credential_id = "VC-" + datetime.now().strftime("%Y%m%d%H%M%S")
        if not self.expires_at:
            self.expires_at = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        d = self.governance_decision
        return {
            "credential_id": self.credential_id,
            "issuer": self.issuer,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "final_action": d.final_action if d else "",
            "trace_id": d.trace_id if d else ""
        }

class CredentialIssuer:
    def __init__(self, secret_key=None):
        self.secret_key = secret_key or "cufei-q-default-key-2026"
        print("✅ 凭证签发器已初始化")

    def issue(self, governance_decision):
        credential = VerifiableCredential(governance_decision=governance_decision)
        d = governance_decision
        content = json.dumps({
            "credential_id": credential.credential_id,
            "trace_id": d.trace_id if d else "",
            "final_action": d.final_action if d else ""
        }, sort_keys=True)
        credential.signature = hmac.new(
            self.secret_key.encode(), content.encode(), hashlib.sha256
        ).hexdigest()
        print("📜 凭证已签发: " + credential.credential_id)
        return credential

class CredentialVerifier:
    def __init__(self):
        self.secret_key = "cufei-q-default-key-2026"
        print("✅ 凭证验证器已初始化")

    def verify(self, credential):
        d = credential.governance_decision
        content = json.dumps({
            "credential_id": credential.credential_id,
            "trace_id": d.trace_id if d else "",
            "final_action": d.final_action if d else ""
        }, sort_keys=True)
        expected = hmac.new(
            self.secret_key.encode(), content.encode(), hashlib.sha256
        ).hexdigest()
        sig_ok = hmac.compare_digest(credential.signature, expected)
        now = datetime.now()
        try:
            exp = datetime.strptime(credential.expires_at, "%Y-%m-%d %H:%M:%S")
            exp_ok = now < exp
        except:
            exp_ok = False
        all_ok = sig_ok and exp_ok
        return {
            "valid": all_ok,
            "credential_id": credential.credential_id,
            "checks": [
                {"check": "签名", "passed": sig_ok},
                {"check": "有效期", "passed": exp_ok}
            ],
            "message": "✅ 通过" if all_ok else "❌ 失败"
        }

class CredentialStore:
    def __init__(self):
        self._store = {}
        print("✅ 凭证存储已初始化")

    def save(self, c):
        self._store[c.credential_id] = c

    def revoke(self, cid):
        if cid in self._store:
            self._store[cid].status = CredentialStatus.REVOKED
            return True
        return False

    def list_all(self):
        return list(self._store.values())

    def export_all(self, fp):
        data = {
            "total": len(self._store),
            "credentials": [c.to_dict() for c in self._store.values()]
        }
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("📁 已导出 " + str(len(self._store)) + " 个凭证")