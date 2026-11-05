"""Immutable Parquet cache with a checksum manifest.

Layout:
    <root>/<dataset>/<key>.parquet
    <root>/<dataset>/<key>.manifest.json

Every file is accompanied by metadata (source, fetched_at, rows, last_date,
checksum, columns). Writes are atomic: a temp file is renamed into place, so a
crashed download never leaves a truncated parquet that looks valid.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")


def safe_key(key: str) -> str:
    """Keys come from dates/symbols; sanitise so they can be file names."""
    return _SAFE.sub("_", str(key)).strip("_") or "default"


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CacheManifest:
    dataset: str
    key: str
    source: str
    fetched_at: str
    rows: int
    columns: list[str] = field(default_factory=list)
    last_date: str | None = None
    first_date: str | None = None
    checksum: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def fetched_on(self) -> date | None:
        try:
            return datetime.fromisoformat(self.fetched_at).date()
        except ValueError:
            return None

    def to_dict(self) -> dict:
        return asdict(self)


class ParquetCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def parquet_path(self, dataset: str, key: str) -> Path:
        return self.root / safe_key(dataset) / f"{safe_key(key)}.parquet"

    def manifest_path(self, dataset: str, key: str) -> Path:
        return self.root / safe_key(dataset) / f"{safe_key(key)}.manifest.json"

    def exists(self, dataset: str, key: str) -> bool:
        return self.parquet_path(dataset, key).exists()

    # -- read / write --------------------------------------------------
    def read(self, dataset: str, key: str) -> pd.DataFrame | None:
        path = self.parquet_path(dataset, key)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def manifest(self, dataset: str, key: str) -> CacheManifest | None:
        path = self.manifest_path(dataset, key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        payload.pop("path", None)
        allowed = {f for f in CacheManifest.__dataclass_fields__}
        return CacheManifest(**{k: v for k, v in payload.items() if k in allowed})

    def write(
        self,
        dataset: str,
        key: str,
        df: pd.DataFrame,
        *,
        source: str,
        params: dict | None = None,
        date_column: str = "date",
    ) -> CacheManifest:
        path = self.parquet_path(dataset, key)
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".parquet.tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            df.to_parquet(tmp, index=False)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

        first_date = last_date = None
        if date_column in df.columns and len(df):
            dates = pd.to_datetime(df[date_column], errors="coerce").dropna()
            if len(dates):
                first_date = dates.min().date().isoformat()
                last_date = dates.max().date().isoformat()

        manifest = CacheManifest(
            dataset=safe_key(dataset),
            key=safe_key(key),
            source=source,
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            rows=int(len(df)),
            columns=[str(c) for c in df.columns],
            last_date=last_date,
            first_date=first_date,
            checksum=checksum(path),
            params=params or {},
        )
        mpath = self.manifest_path(dataset, key)
        mpath.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def describe(self, dataset: str) -> list[CacheManifest]:
        folder = self.root / safe_key(dataset)
        if not folder.exists():
            return []
        out = []
        for mpath in sorted(folder.glob("*.manifest.json")):
            key = mpath.name[: -len(".manifest.json")]
            m = self.manifest(dataset, key)
            if m:
                out.append(m)
        return out
