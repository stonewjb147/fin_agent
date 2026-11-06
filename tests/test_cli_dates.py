"""as_of resolution: a requested date must never label someone else's data.

Regression: `signals --date <Saturday>` used to raise a ValueError traceback and
`factor-report --date <Saturday>` used to write `2026-11-07.parquet` holding
Friday's rows. Both are now snapped to the last trading day at or before the
request, with a note on stderr.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from finagent.cli import _resolve_as_of
from finagent.signals.score import NoScoresError, score_row


class _StubProvider:
    def __init__(self, trading_days: list[date], today: date):
        self.days = sorted(trading_days)
        self.today = today

    def is_trading_day(self, day: date) -> bool:
        return day in set(self.days)

    def last_trading_day(self, as_of: date | None = None) -> date:
        as_of = as_of or self.today
        candidates = [d for d in self.days if d <= as_of]
        if not candidates:
            raise RuntimeError("trade calendar has no date <= as_of")
        return candidates[-1]


@pytest.fixture()
def provider() -> _StubProvider:
    return _StubProvider(
        [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)],
        today=date(2026, 11, 7),
    )


def test_no_date_means_last_trading_day(provider):
    assert _resolve_as_of(provider, None) == date(2026, 11, 5)


def test_a_trading_day_is_used_as_is(provider, capsys):
    assert _resolve_as_of(provider, "2026-11-04") == date(2026, 11, 4)
    assert capsys.readouterr().err == ""


def test_a_holiday_snaps_back_with_a_notice(provider, capsys):
    assert _resolve_as_of(provider, "2026-11-07") == date(2026, 11, 5)
    err = capsys.readouterr().err
    assert "2026-11-07 is not a trading day" in err
    assert "2026-11-05" in err


def test_an_unknown_symbol_date_raises_a_typed_error():
    """A date with no cross-section is operational, not a crash."""
    scores = pd.DataFrame(
        {"date": [pd.Timestamp("2026-11-05")], "symbol": ["510300"], "composite": [0.5], "confidence": [0.9], "n_factors": [3]}
    )
    with pytest.raises(NoScoresError) as info:
        score_row(scores, date(2026, 11, 4))
    assert "latest is 2026-11-05" in str(info.value)
    assert score_row(scores, date(2026, 11, 5)).index.tolist() == ["510300"]
