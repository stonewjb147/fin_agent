"""Data catalog loader.

The catalog is documentation with a schema: every dataset the collector writes
should be registered here, and every documented gap should be marked
`available: false` so reports can state it instead of silently omitting it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from finagent.config import CONFIG_DIR

DEFAULT_PATH = CONFIG_DIR / "catalog.yaml"

REQUIRED_KEYS = ("source", "frequency", "fields", "coverage", "license", "notes")


def load_catalog(path: str | Path | None = None) -> dict:
    path = Path(path or DEFAULT_PATH)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    datasets = payload.get("datasets") or {}
    return {"version": str(payload.get("version", "c1")), "datasets": datasets}


def validate_catalog(catalog: dict, required: set[str] | None = None) -> list[str]:
    problems: list[str] = []
    datasets = catalog.get("datasets", {})
    if not datasets:
        problems.append("catalog has no datasets")
    for name, meta in datasets.items():
        missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
        if missing:
            problems.append(f"{name}: missing {missing}")
        if meta.get("available", True) and not meta.get("fields"):
            problems.append(f"{name}: available dataset has no fields")
    for name in sorted(required or set()):
        if name not in datasets:
            problems.append(f"{name}: used by the collector but missing from catalog")
    return problems


def coverage_notes(catalog: dict) -> dict[str, str]:
    """Datasets the report must describe as unavailable."""
    return {
        name: str(meta.get("notes", "")).strip()
        for name, meta in catalog.get("datasets", {}).items()
        if not meta.get("available", True)
    }
