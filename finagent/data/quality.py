"""Data-quality checks.

Failures never abort a research run silently: they surface as structured issues
that are carried into the report (`data_quality`) and can page via Feishu in
scripts/health_check.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

import pandas as pd

Level = Literal["error", "warning", "info"]


@dataclass
class Issue:
    level: Level
    code: str
    message: str
    context: dict = field(default_factory=dict)


@dataclass
class QualityReport:
    dataset: str
    key: str
    as_of: str
    rows: int
    issues: list[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    def add(self, level: Level, code: str, message: str, **context) -> None:
        self.issues.append(Issue(level, code, message, context))

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "key": self.key,
            "as_of": self.as_of,
            "rows": self.rows,
            "ok": self.ok,
            "issues": [
                {"level": i.level, "code": i.code, "message": i.message, "context": i.context}
                for i in self.issues
            ],
            "metrics": self.metrics,
        }


def check_frame(
    df: pd.DataFrame,
    dataset: str,
    key: str,
    as_of: date | str,
    *,
    date_col: str = "date",
    keys: tuple[str, ...] = (),
    price_cols: tuple[str, ...] = ("open", "close"),
    max_missing_ratio: float = 0.05,
    min_rows: int = 1,
    allow_future: bool = False,
) -> QualityReport:
    """Validate one frame.

    `allow_future` exists for genuinely forward-looking datasets: the trading
    calendar lists days that have not happened yet, and flagging them as
    look-ahead would make every quality report fail.
    """
    as_of_str = pd.Timestamp(as_of).date().isoformat()
    report = QualityReport(dataset=dataset, key=key, as_of=as_of_str, rows=int(len(df)))

    if df.empty:
        report.add("error", "empty", f"{dataset}/{key} is empty")
        return report
    if len(df) < min_rows:
        report.add("error", "too_few_rows", f"rows={len(df)} < {min_rows}")

    if date_col not in df.columns:
        report.add("error", "missing_date_column", f"no {date_col!r} column")
        return report

    dates = pd.to_datetime(df[date_col], errors="coerce")
    if dates.isna().any():
        report.add("error", "unparsable_dates", f"{int(dates.isna().sum())} unparsable dates")

    cutoff = pd.Timestamp(as_of_str)
    future = dates > cutoff
    if future.any() and not allow_future:
        report.add(
            "error",
            "future_data",
            f"{int(future.sum())} rows after as_of={as_of_str}",
            first_future=str(dates[future].min().date()),
        )

    if keys:
        present = [k for k in keys if k in df.columns]
        if len(present) == len(keys):
            dup = df.duplicated(subset=list(keys)).sum()
            if dup:
                report.add("error", "duplicate_keys", f"{int(dup)} duplicated {keys}")

    for col in price_cols:
        if col not in df.columns:
            report.add("warning", "missing_column", f"no {col!r} column")
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        bad = series <= 0
        if bad.any():
            report.add("error", "non_positive_price", f"{int(bad.sum())} rows {col} <= 0")
        missing = series.isna().mean()
        if missing > max_missing_ratio:
            report.add(
                "warning",
                "high_missing",
                f"{col} missing {missing:.1%} > {max_missing_ratio:.1%}",
                column=col,
            )

    report.metrics.update(
        {
            "first_date": None if dates.dropna().empty else str(dates.min().date()),
            "last_date": None if dates.dropna().empty else str(dates.max().date()),
            "missing_ratio": round(float(df.isna().mean().mean()), 4),
        }
    )
    return report


def check_freshness(
    last_date: str | None,
    as_of: date | str,
    *,
    dataset: str,
    key: str,
    max_lag_days: int = 5,
) -> QualityReport:
    as_of_d = pd.Timestamp(as_of).date()
    report = QualityReport(dataset=dataset, key=key, as_of=as_of_d.isoformat(), rows=0)
    if not last_date:
        report.add("error", "no_last_date", f"{dataset}/{key} has no data date")
        return report
    lag = (as_of_d - pd.Timestamp(last_date).date()).days
    report.metrics["lag_days"] = lag
    if lag > max_lag_days:
        report.add(
            "error" if lag > max_lag_days * 2 else "warning",
            "stale",
            f"{dataset}/{key} last date {last_date}, lag {lag}d > {max_lag_days}d",
        )
    return report


def merge_reports(reports: list[QualityReport]) -> dict:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": all(r.ok for r in reports),
        "reports": [r.to_dict() for r in reports],
    }
