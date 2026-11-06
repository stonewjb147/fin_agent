"""Append-only prediction ledger: write down every call, settle it later.

Two files under `data/predictions/`:

- `ledger.jsonl`     one line per generated signal, never rewritten;
- `settled.jsonl`    one line per matured signal, appended when its horizon ends.

Settlement is relative to the equal-weight universe over the same window, not
to absolute return: a long call in a market-wide rally is not skill. Hit rate
and the Brier score below all use that relative return.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from finagent import config
from finagent.data.panel import as_date

LEDGER_FIELDS = [
    "signal_id",
    "as_of",
    "symbol",
    "name",
    "category",
    "direction",
    "horizon",
    "execution_lag",
    "composite",
    "confidence",
    "n_factors",
    "evidence_json",
    "thesis",
]

SETTLEMENT_FIELDS = [
    "signal_id",
    "as_of",
    "symbol",
    "direction",
    "horizon",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "ret",
    "excess",
    "dir_ret",
    "dir_excess",
    "hit",
    "hit_excess",
    "settled_at",
]

CALIBRATION_EDGES = (0.0, 0.6, 0.7, 0.8, 1.0001)


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


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


class PredictionLedger:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or config.PREDICTION_DIR)

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def settled_path(self) -> Path:
        return self.root / "settled.jsonl"

    def load(self) -> pd.DataFrame:
        return _read_jsonl(self.ledger_path, LEDGER_FIELDS)

    def settlements(self) -> pd.DataFrame:
        return _read_jsonl(self.settled_path, SETTLEMENT_FIELDS)

    def append(self, records: Iterable[dict[str, Any]]) -> int:
        """Append new predictions; a repeated signal_id is never written twice."""
        existing = set(self.load()["signal_id"].dropna())
        new: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            sid = str(record["signal_id"])
            if sid in existing or sid in seen:
                continue
            seen.add(sid)
            new.append({key: record.get(key) for key in LEDGER_FIELDS})
        return _append_jsonl(self.ledger_path, new)

    def settle(
        self,
        close: pd.DataFrame,
        as_of: date | str,
        *,
        symbols: Iterable[str] | None = None,
        write: bool = True,
    ) -> pd.DataFrame:
        """Settle every prediction whose exit date is on or before `as_of`.

        Prices come from `close`, which must already be truncated to `as_of`, so
        settlement can never peek ahead. Rows whose `as_of` is not a trading day
        in the panel are left pending rather than anchored to a nearby day.
        """
        as_of = as_date(as_of)
        ledger = self.load()
        if ledger.empty:
            return pd.DataFrame(columns=SETTLEMENT_FIELDS)

        done = set(self.settlements()["signal_id"].dropna())
        pending = ledger[~ledger["signal_id"].isin(done)]
        if pending.empty:
            return pd.DataFrame(columns=SETTLEMENT_FIELDS)

        index = close.index
        universe = [s for s in (symbols if symbols is not None else close.columns) if s in close.columns]
        new_rows: list[dict[str, Any]] = []

        for row in pending.itertuples(index=False):
            signal_as_of = pd.Timestamp(str(row.as_of))
            pos = int(index.searchsorted(signal_as_of, side="right") - 1)
            if pos < 0 or index[pos] != signal_as_of:
                continue  # not a price date in this panel; retry on a later run
            entry_pos = pos + int(row.execution_lag)
            exit_pos = entry_pos + int(row.horizon)
            if exit_pos >= len(index):
                continue  # horizon has not elapsed yet
            if index[exit_pos] > pd.Timestamp(as_of):
                continue  # the caller passed an untruncated panel; never peek ahead

            symbol = str(row.symbol)
            if symbol not in close.columns:
                continue
            entry_price = close[symbol].iloc[entry_pos]
            exit_price = close[symbol].iloc[exit_pos]
            if not np.isfinite(entry_price) or not np.isfinite(exit_price) or entry_price <= 0:
                continue

            ret = float(exit_price / entry_price - 1.0)
            cross_section = close.iloc[exit_pos][universe] / close.iloc[entry_pos][universe] - 1.0
            cross_section = cross_section.replace([np.inf, -np.inf], np.nan).dropna()
            excess = ret - float(cross_section.mean()) if len(cross_section) else float("nan")

            direction = int(row.direction)
            dir_ret = ret * direction
            dir_excess = excess * direction
            new_rows.append(
                {
                    "signal_id": row.signal_id,
                    "as_of": str(row.as_of),
                    "symbol": symbol,
                    "direction": direction,
                    "horizon": int(row.horizon),
                    "entry_date": index[entry_pos].date().isoformat(),
                    "exit_date": index[exit_pos].date().isoformat(),
                    "entry_price": round(float(entry_price), 6),
                    "exit_price": round(float(exit_price), 6),
                    "ret": round(ret, 8),
                    "excess": round(excess, 8) if np.isfinite(excess) else None,
                    "dir_ret": round(dir_ret, 8),
                    "dir_excess": round(dir_excess, 8) if np.isfinite(dir_excess) else None,
                    "hit": bool(dir_ret > 0),
                    "hit_excess": bool(dir_excess > 0) if np.isfinite(dir_excess) else None,
                    "settled_at": as_of.isoformat(),
                }
            )

        if write:
            _append_jsonl(self.settled_path, new_rows)
        return pd.DataFrame(new_rows, columns=SETTLEMENT_FIELDS)

    def summary(self, as_of: date | str | None = None) -> dict[str, Any]:
        """Hit rate, directional excess and calibration over settled predictions."""
        ledger = self.load()
        settled = self.settlements()
        total = int(len(ledger))
        done = int(settled["signal_id"].nunique()) if not settled.empty else 0
        out: dict[str, Any] = {
            "as_of": as_date(as_of).isoformat() if as_of else None,
            "n_predictions": total,
            "n_settled": done,
            "n_pending": max(total - done, 0),
        }
        if settled.empty:
            out.update(
                {
                    "hit_rate_excess": None,
                    "mean_directional_excess": None,
                    "brier": None,
                    "notes": "no settled predictions yet",
                }
            )
            return out

        frame = settled.merge(
            ledger[["signal_id", "confidence", "composite", "category"]],
            on="signal_id",
            how="left",
        )
        valid = frame.dropna(subset=["dir_excess"])
        out.update(
            {
                "hit_rate": float(frame["hit"].astype(float).mean()),
                "hit_rate_excess": float(valid["hit_excess"].astype(float).mean()) if len(valid) else None,
                "mean_directional_return": float(frame["dir_ret"].mean()),
                "mean_directional_excess": float(valid["dir_excess"].mean()) if len(valid) else None,
            }
        )

        if len(valid):
            p_up = (valid["confidence"].astype(float) * 0.5 + 0.5).clip(0.0, 1.0)
            out["brier"] = float(((p_up - valid["hit_excess"].astype(float)) ** 2).mean())
            out["brier_baseline"] = 0.25  # always predicting 0.5
            out["calibration"] = _calibration(valid)
            out["by_direction"] = {
                str(int(k)): {
                    "n": int(len(g)),
                    "hit_rate_excess": float(g["hit_excess"].astype(float).mean()),
                    "mean_directional_excess": float(g["dir_excess"].mean()),
                }
                for k, g in valid.groupby("direction")
            }
        else:
            out["brier"] = None
        out["notes"] = (
            "Confidence is a heuristic agreement score, not a calibrated probability; "
            "the Brier score here measures whether it is at least better than a coin flip. "
            "Excess return is measured against the equal-weight universe over the same window."
        )
        return out


def _calibration(frame: pd.DataFrame) -> list[dict[str, Any]]:
    bins = pd.cut(
        frame["confidence"].astype(float),
        bins=list(CALIBRATION_EDGES),
        right=False,
        include_lowest=True,
    )
    rows = []
    for label, group in frame.groupby(bins, observed=True):
        rows.append(
            {
                "confidence_bucket": f"[{label.left:.2f}, {label.right:.2f})",
                "n": int(len(group)),
                "mean_confidence": float(group["confidence"].mean()),
                "realised_outperformance": float(group["hit_excess"].astype(float).mean()),
            }
        )
    return rows


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"Prediction ledger  as_of={summary.get('as_of')}  "
        f"predictions={summary['n_predictions']}  settled={summary['n_settled']}  "
        f"pending={summary['n_pending']}"
    ]
    if not summary.get("n_settled"):
        lines.append("no settled predictions yet — the first settlement needs a full horizon")
        return "\n".join(lines)

    def _pct(value) -> str:
        return f"{value:.1%}" if value is not None else "n/a"

    lines.append(
        f"hit rate: absolute {_pct(summary.get('hit_rate'))}  "
        f"vs universe {_pct(summary.get('hit_rate_excess'))}   "
        f"mean directional excess {_pct(summary.get('mean_directional_excess'))}"
    )
    if summary.get("brier") is not None:
        lines.append(f"Brier {summary['brier']:.3f} (coin-flip baseline 0.250)")
    calibration = summary.get("calibration") or []
    if calibration:
        lines.append("")
        lines.append(f"{'CONFIDENCE':16s} {'N':>4s} {'MEAN':>6s} {'REALISED':>9s}")
        for row in calibration:
            lines.append(
                f"{row['confidence_bucket']:16s} {row['n']:4d} "
                f"{row['mean_confidence']:6.2f} {row['realised_outperformance']:9.1%}"
            )
    return "\n".join(lines)


def record_settlement(frame: pd.DataFrame) -> dict[str, Any]:
    """Compact one-line summary for terminal output."""
    if frame.empty:
        return {"n_new": 0}
    return {
        "n_new": int(len(frame)),
        "hit_rate_excess": float(frame["hit_excess"].dropna().astype(float).mean())
        if frame["hit_excess"].notna().any()
        else None,
        "mean_directional_excess": float(frame["dir_excess"].dropna().mean())
        if frame["dir_excess"].notna().any()
        else None,
    }
