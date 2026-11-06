"""End-to-end growth runs: daily state, periodic review and journal settlement."""

from __future__ import annotations

import json
from pathlib import Path

from finagent import config
from finagent.data.panel import as_date
from finagent.factors.build import load_close_panel
from finagent.growth.journal import DecisionJournal, format_journal
from finagent.growth.review import (
    build_growth_review,
    format_growth_review,
    render_growth_review,
)
from finagent.growth.state import build_growth_state, format_growth


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_growth(
    as_of: str,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    window: int = 30,
    write: bool = True,
) -> dict:
    data_dir = Path(data_dir or config.DATA_DIR)
    state = build_growth_state(
        as_of, data_dir=data_dir, cache_dir=cache_dir, window=window
    )
    if write:
        target = Path(out_dir or data_dir / "growth")
        path = target / f"growth_{state['as_of']}.json"
        _write_json(path, state)
        state["growth_file"] = str(path)
    return state


def run_growth_review(
    as_of: str,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    window: int = 30,
    write: bool = True,
) -> dict:
    data_dir = Path(data_dir or config.DATA_DIR)
    state = build_growth_state(
        as_of, data_dir=data_dir, cache_dir=cache_dir, window=window
    )
    review = build_growth_review(state, window=window)
    review["markdown"] = render_growth_review(review)
    if write:
        target = Path(out_dir or data_dir / "growth")
        target.mkdir(parents=True, exist_ok=True)
        md_path = target / f"review_{review['as_of']}.md"
        json_path = target / f"review_{review['as_of']}.json"
        md_path.write_text(review["markdown"], encoding="utf-8")
        payload = {key: value for key, value in review.items() if key != "markdown"}
        _write_json(json_path, payload)
        review["files"] = {"markdown": str(md_path), "json": str(json_path)}
    return review


def run_journal_review(
    as_of: str,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    universe_symbols: list[str] | None = None,
    out_dir: str | Path | None = None,
    write: bool = True,
) -> dict:
    data_dir = Path(data_dir or config.DATA_DIR)
    cache_dir = Path(cache_dir or data_dir / "cache")
    as_of = as_date(as_of).isoformat()
    journal = DecisionJournal(data_dir / "journal")
    entries = journal.load()
    result: dict = {
        "as_of": as_of,
        "n_entries": int(len(entries)),
        "n_new_reviews": 0,
        "new_reviews": [],
        "summary": journal.summary(as_of),
    }
    if entries.empty:
        result["note"] = "no decisions recorded yet"
    else:
        symbols = sorted(
            set(entries["symbol"].dropna().astype(str))
            | set(universe_symbols or [])
        )
        try:
            close = load_close_panel(cache_dir, symbols, as_of)
        except ValueError as exc:
            result["note"] = f"price cache unavailable: {exc}"
        else:
            new = journal.review(
                close,
                as_of,
                universe_symbols=universe_symbols,
                write=write,
            )
            result["n_new_reviews"] = int(len(new))
            result["new_reviews"] = new.to_dict("records")
            result["summary"] = journal.summary(as_of)
    if write:
        target = Path(out_dir or data_dir / "journal")
        path = target / f"review_{as_of}.json"
        _write_json(path, result)
        result["review_file"] = str(path)
    return result


def format_journal_review(result: dict) -> str:
    lines = [
        f"Journal review {result['as_of']}  entries={result['n_entries']}  "
        f"new reviews={result['n_new_reviews']}",
    ]
    if result.get("note"):
        lines.append(f"Note: {result['note']}")
    lines.append("")
    lines.append(format_journal(result["summary"]))
    if result.get("new_reviews"):
        lines.append("")
        lines.append("Newly reviewed:")
        for row in result["new_reviews"]:
            lines.append(
                f"  - {row['decision_id']}  {row['entry_date']} → {row['exit_date']}  "
                f"excess={row['excess']}  outcome={row['outcome']}"
            )
    if result.get("review_file"):
        lines.append(f"\nJSON: {result['review_file']}")
    return "\n".join(lines)


__all__ = [
    "build_growth_state",
    "format_growth",
    "format_growth_review",
    "format_journal_review",
    "run_growth",
    "run_growth_review",
    "run_journal_review",
]
