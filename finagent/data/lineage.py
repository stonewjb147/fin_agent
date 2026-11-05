"""Snapshot lineage: snapshot_id -> files -> checksums.

A snapshot is an immutable list of cache entries used by one run. The id is
derived from the contents, so the same data always produces the same id and a
re-fetch that changes bytes produces a new one. Reports carry the id; anyone
can walk backwards to the exact parquet files and their checksums.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from finagent.config import SNAPSHOT_DIR
from finagent.data.cache import ParquetCache, checksum, safe_key


@dataclass
class SnapshotEntry:
    dataset: str
    key: str
    path: str
    checksum: str
    rows: int
    last_date: str | None
    first_date: str | None
    fetched_at: str | None
    source: str | None


@dataclass
class Snapshot:
    snapshot_id: str
    as_of: str
    created_at: str
    note: str = ""
    entries: list[SnapshotEntry] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "as_of": self.as_of,
            "created_at": self.created_at,
            "note": self.note,
            "entries": [asdict(e) for e in self.entries],
            "extras": self.extras,
        }

    def find(self, dataset: str, key: str) -> SnapshotEntry | None:
        ds, k = safe_key(dataset), safe_key(key)
        for e in self.entries:
            if e.dataset == ds and e.key == k:
                return e
        return None


class SnapshotStore:
    def __init__(self, root: str | Path = SNAPSHOT_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, snapshot_id: str) -> Path:
        return self.root / f"{snapshot_id}.json"

    def build(
        self,
        cache: ParquetCache,
        pairs: list[tuple[str, str]],
        as_of: date | str,
        *,
        note: str = "",
        extras: dict | None = None,
    ) -> Snapshot:
        as_of_s = str(as_of)
        entries: list[SnapshotEntry] = []
        for dataset, key in sorted(set(pairs)):
            manifest = cache.manifest(dataset, key)
            parquet = cache.parquet_path(dataset, key)
            if manifest is None or not parquet.exists():
                raise FileNotFoundError(f"cache miss for snapshot entry: {dataset}/{key}")
            entries.append(
                SnapshotEntry(
                    dataset=safe_key(dataset),
                    key=safe_key(key),
                    path=str(parquet.relative_to(cache.root)),
                    checksum=manifest.checksum or checksum(parquet),
                    rows=manifest.rows,
                    last_date=manifest.last_date,
                    first_date=manifest.first_date,
                    fetched_at=manifest.fetched_at,
                    source=manifest.source,
                )
            )
        import hashlib

        blob = json.dumps(
            [(e.dataset, e.key, e.checksum) for e in entries], sort_keys=True, ensure_ascii=False
        )
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]
        snapshot_id = f"snap-{pd_date(as_of_s)}-{digest}"
        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            as_of=as_of_s,
            created_at=datetime.now().isoformat(timespec="seconds"),
            note=note,
            entries=entries,
            extras=extras or {},
        )
        self.path(snapshot_id).write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return snapshot

    def load(self, snapshot_id: str) -> Snapshot:
        payload = json.loads(self.path(snapshot_id).read_text(encoding="utf-8"))
        entries = [SnapshotEntry(**e) for e in payload["entries"]]
        return Snapshot(
            snapshot_id=payload["snapshot_id"],
            as_of=payload["as_of"],
            created_at=payload["created_at"],
            note=payload.get("note", ""),
            entries=entries,
            extras=payload.get("extras", {}),
        )

    def verify(self, snapshot_id: str, cache: ParquetCache) -> dict:
        snap = self.load(snapshot_id)
        results = []
        for e in snap.entries:
            path = cache.root / e.path
            actual = checksum(path) if path.exists() else None
            results.append(
                {
                    "dataset": e.dataset,
                    "key": e.key,
                    "exists": path.exists(),
                    "checksum_match": actual == e.checksum,
                    "expected": e.checksum,
                    "actual": actual,
                }
            )
        return {"snapshot_id": snapshot_id, "ok": all(r["checksum_match"] for r in results), "entries": results}


def pd_date(value: str) -> str:
    """'2026-11-05' -> '20261105'; tolerant of timestamps."""
    return str(value)[:10].replace("-", "")
