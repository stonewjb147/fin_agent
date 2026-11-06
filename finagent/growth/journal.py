"""Append-only decision journal: record what a human decided and why.

The system never creates a decision. It stores one, then later checks the
outcome against prices so the human can compare *process* with *result*. A good
decision can lose money, and a bad one can make money; the journal keeps both
facts separate.

Two JSONL files under `data/journal/`:

- `entries.jsonl`   one line per recorded decision, never rewritten;
- `reviews.jsonl`   one line per matured decision, appended once.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from finagent import config
from finagent.data.panel import as_date

DECISION_FIELDS = [
    "decision_id",
    "as_of",
    "scope",
    "symbol",
    "action",
    "rationale",
    "confidence",
    "review_days",
    "tags",
    "signal_ids",
    "mode",
    "created_at",
]

REVIEW_FIELDS = [
    "decision_id",
    "review_as_of",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "ret",
    "excess",
    "direction",
    "dir_excess",
    "outcome",
    "note",
]

# Direction implied by the action. `watch` and `no_trade` are observations, not
# predictions, so they are measured but excluded from hit-rate statistics.
ACTION_DIRECTION = {
    "add": 1,
    "hold": 1,
    "trim": -1,
    "exit": -1,
    "watch": 0,
    "no_trade": 0,
}

ACTION_LABELS = {
    "add": "加仓/买入",
    "hold": "持有",
    "trim": "减仓",
    "exit": "清仓",
    "watch": "观察",
    "no_trade": "不操作",
}


class JournalError(ValueError):
    """The decision record is incomplete or malformed."""


def _read_jsonl(path: Path, fields: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=fields)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    if not rows:
        return pd.DataFrame(columns=fields)
    frame = pd.DataFrame(rows)
    for col in fields:
        if col not in frame.columns:
            frame[col] = np.nan
    return frame


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


class DecisionJournal:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or config.JOURNAL_DIR)

    @property
    def entries_path(self) -> Path:
        return self.root / "entries.jsonl"

    @property
    def reviews_path(self) -> Path:
        return self.root / "reviews.jsonl"

    def load(self) -> pd.DataFrame:
        return _read_jsonl(self.entries_path, DECISION_FIELDS)

    def reviews(self) -> pd.DataFrame:
        return _read_jsonl(self.reviews_path, REVIEW_FIELDS)

    def add(
        self,
        *,
        as_of: str,
        action: str,
        rationale: str,
        symbol: str | None = None,
        confidence: float = 0.5,
        review_days: int = 20,
        tags: list[str] | None = None,
        signal_ids: list[str] | None = None,
        decision_id: str | None = None,
        mode: str = "research",
    ) -> dict[str, Any]:
        """Validate and append one decision. The rationale is mandatory."""
        as_of = as_date(as_of).isoformat()
        action = str(action).strip().lower()
        if action not in ACTION_DIRECTION:
            raise JournalError(f"unknown action {action!r}; choose from {sorted(ACTION_DIRECTION)}")
        rationale = str(rationale).strip()
        if not rationale:
            raise JournalError("rationale is required: a decision without a reason cannot be reviewed")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise JournalError("confidence must be a number in [0, 1]") from exc
        if not 0.0 <= confidence <= 1.0:
            raise JournalError("confidence must be in [0, 1]")
        try:
            review_days = int(review_days)
        except (TypeError, ValueError) as exc:
            raise JournalError("review_days must be a positive integer") from exc
        if review_days < 1:
            raise JournalError("review_days must be a positive integer")

        symbol = str(symbol).strip() if symbol else None
        scope = "symbol" if symbol else "portfolio"
        if decision_id is None:
            stem = f"dec-{as_of}-{symbol or 'portfolio'}-{action}"
            existing = set(self.load()["decision_id"].dropna())
            decision_id = stem
            suffix = 2
            while decision_id in existing:
                decision_id = f"{stem}-{suffix}"
                suffix += 1
        else:
            decision_id = str(decision_id).strip()
            if not decision_id:
                raise JournalError("decision_id must not be empty")

        record = {
            "decision_id": decision_id,
            "as_of": as_of,
            "scope": scope,
            "symbol": symbol,
            "action": action,
            "rationale": rationale,
            "confidence": round(confidence, 4),
            "review_days": review_days,
            "tags": list(tags or []),
            "signal_ids": list(signal_ids or []),
            "mode": mode,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if decision_id in set(self.load()["decision_id"].dropna()):
            raise JournalError(f"decision_id already exists: {decision_id}")
        _append_jsonl(self.entries_path, [record])
        return record

    def review(
        self,
        close: pd.DataFrame,
        as_of: str,
        *,
        universe_symbols: list[str] | None = None,
        write: bool = True,
    ) -> pd.DataFrame:
        """Review matured symbol decisions against the equal-weight universe.

        Prices must already be truncated to `as_of`. An entry whose exit date is
        later than `as_of` stays pending; the journal never peeks ahead.
        """
        as_of_date = as_date(as_of)
        entries = self.load()
        if entries.empty:
            return pd.DataFrame(columns=REVIEW_FIELDS)

        done = set(self.reviews()["decision_id"].dropna())
        pending = entries[~entries["decision_id"].isin(done)]
        pending = pending[pending["scope"] == "symbol"]
        if pending.empty:
            return pd.DataFrame(columns=REVIEW_FIELDS)

        index = pd.DatetimeIndex(close.index)
        benchmark = [
            str(s) for s in (universe_symbols if universe_symbols is not None else close.columns)
            if str(s) in close.columns
        ]
        rows: list[dict[str, Any]] = []
        for row in pending.itertuples(index=False):
            symbol = str(row.symbol or "")
            if not symbol or symbol not in close.columns:
                continue
            decision_date = pd.Timestamp(str(row.as_of))
            positions = index.get_indexer([decision_date])
            if len(positions) == 0 or positions[0] < 0:
                continue  # decision date is not a price date in this panel
            entry_pos = int(positions[0])
            exit_pos = entry_pos + int(row.review_days)
            if exit_pos >= len(index):
                continue
            if index[exit_pos] > pd.Timestamp(as_of_date):
                continue  # caller passed an untruncated panel; never peek ahead

            entry_price = close[symbol].iloc[entry_pos]
            exit_price = close[symbol].iloc[exit_pos]
            if not np.isfinite(entry_price) or not np.isfinite(exit_price) or entry_price <= 0:
                continue

            ret = float(exit_price / entry_price - 1.0)
            cross = close.iloc[exit_pos][benchmark] / close.iloc[entry_pos][benchmark] - 1.0
            cross = cross.replace([np.inf, -np.inf], np.nan).dropna()
            excess = ret - float(cross.mean()) if len(cross) else float("nan")
            direction = int(ACTION_DIRECTION.get(str(row.action), 0))
            dir_excess = direction * excess if np.isfinite(excess) else float("nan")
            if direction == 0:
                outcome = "observed"
                note = "观察项，不参与命中率"
            elif not np.isfinite(dir_excess):
                outcome = "unscored"
                note = "缺少可比基准，未评分"
            else:
                outcome = "hit" if dir_excess > 0 else "miss"
                note = ""
            rows.append(
                {
                    "decision_id": row.decision_id,
                    "review_as_of": as_of_date.isoformat(),
                    "entry_date": index[entry_pos].date().isoformat(),
                    "exit_date": index[exit_pos].date().isoformat(),
                    "entry_price": round(float(entry_price), 6),
                    "exit_price": round(float(exit_price), 6),
                    "ret": round(ret, 8),
                    "excess": round(excess, 8) if np.isfinite(excess) else None,
                    "direction": direction,
                    "dir_excess": round(dir_excess, 8) if np.isfinite(dir_excess) else None,
                    "outcome": outcome,
                    "note": note,
                }
            )

        frame = pd.DataFrame(rows, columns=REVIEW_FIELDS)
        if write and not frame.empty:
            _append_jsonl(self.reviews_path, frame.to_dict("records"))
        return frame

    def summary(self, as_of: str | None = None) -> dict[str, Any]:
        entries = self.load()
        reviews = self.reviews()
        n_entries = int(len(entries))
        reviewed_ids = set(reviews["decision_id"].dropna()) if not reviews.empty else set()
        n_reviewed = len(reviewed_ids)
        out: dict[str, Any] = {
            "as_of": as_date(as_of).isoformat() if as_of else None,
            "n_entries": n_entries,
            "n_reviewed": n_reviewed,
            "n_pending": max(n_entries - n_reviewed, 0),
            "n_directional_reviewed": 0,
            "hit_rate_excess": None,
            "mean_directional_excess": None,
            "by_action": {},
            "note": (
                "Decisions are recorded by a human. Outcome review is separate from "
                "decision quality: a good process can have a bad outcome."
            ),
        }
        if reviews.empty:
            return out

        merged = reviews.merge(
            entries[["decision_id", "action", "confidence"]],
            on="decision_id",
            how="left",
        )
        directional = merged[merged["outcome"].isin(["hit", "miss"])]
        neutral = merged[merged["outcome"] == "observed"]
        out["n_directional_reviewed"] = int(len(directional))
        out["n_neutral_reviewed"] = int(len(neutral))
        if len(directional):
            out["hit_rate_excess"] = float((directional["outcome"] == "hit").mean())
            out["mean_directional_excess"] = float(
                directional["dir_excess"].astype(float).mean()
            )
        if len(merged):
            out["by_action"] = {
                str(action): {
                    "n": int(len(group)),
                    "hit_rate_excess": float((group["outcome"] == "hit").mean())
                    if group["outcome"].isin(["hit", "miss"]).any()
                    else None,
                    "mean_directional_excess": float(
                        group.loc[group["outcome"].isin(["hit", "miss"]), "dir_excess"]
                        .astype(float)
                        .mean()
                    )
                    if group["outcome"].isin(["hit", "miss"]).any()
                    else None,
                }
                for action, group in merged.groupby("action")
            }
        return out


def format_journal(summary: dict[str, Any]) -> str:
    def _pct(value) -> str:
        return f"{value:.1%}" if value is not None else "n/a"

    lines = [
        f"Decision journal  as_of={summary.get('as_of')}  "
        f"entries={summary['n_entries']}  reviewed={summary['n_reviewed']}  "
        f"pending={summary['n_pending']}",
    ]
    if not summary["n_entries"]:
        lines.append("no decisions recorded yet — use `finagent journal --add ...`")
        return "\n".join(lines)
    lines.append(
        f"directional reviewed {summary.get('n_directional_reviewed', 0)}  "
        f"excess hit rate {_pct(summary.get('hit_rate_excess'))}  "
        f"mean directional excess {_pct(summary.get('mean_directional_excess'))}"
    )
    by_action = summary.get("by_action") or {}
    if by_action:
        lines.append("")
        lines.append(f"{'ACTION':10s} {'N':>4s} {'HIT':>7s} {'MEAN EXCESS':>12s}")
        for action, row in sorted(by_action.items()):
            lines.append(
                f"{ACTION_LABELS.get(action, action):10s} {row['n']:4d} "
                f"{_pct(row['hit_rate_excess']):>7s} {_pct(row['mean_directional_excess']):>12s}"
            )
    return "\n".join(lines)
