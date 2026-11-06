"""News overlay: point-in-time, bounded, and explainable per symbol."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from finagent.data.cache import ParquetCache
from finagent.data.universe import ETF, Universe
from finagent.news import apply_news_overlay, load_news, news_scores
from finagent.signals.pipeline import run_signal_pipeline


def _universe() -> Universe:
    return Universe(
        version="u-test",
        etfs=[
            ETF(symbol="510300", name="沪深300ETF", category="broad"),
            ETF(symbol="512880", name="证券ETF", category="sector", flow_sectors=("证券",)),
            ETF(symbol="159819", name="人工智能ETF", category="thematic", flow_sectors=("软件开发",)),
        ],
    )


def _write(tmp_path, items: list[dict]):
    path = tmp_path / "2024-06-28.json"
    path.write_text(json.dumps({"as_of": "2024-06-28", "items": items}, ensure_ascii=False), encoding="utf-8")
    return path


def test_future_headlines_are_not_usable(tmp_path):
    path = _write(
        tmp_path,
        [
            {"title": "今日新闻", "published_at": "2024-06-28T09:30:00+08:00", "sentiment": 0.5},
            {"title": "明日新闻", "published_at": "2024-06-29T09:30:00+08:00", "sentiment": 0.9},
        ],
    )
    loaded = load_news(path, "2024-06-28")

    assert loaded.available
    assert [item.title for item in loaded.items] == ["今日新闻"]
    assert loaded.dropped_future == 1


def test_missing_news_file_degrades_with_a_reason(tmp_path):
    loaded = load_news(tmp_path / "absent.json", "2024-06-28")

    assert not loaded.available
    assert "no news file" in loaded.status.reason
    assert loaded.items == []


def test_sectors_and_themes_reach_etfs(tmp_path):
    path = _write(
        tmp_path,
        [
            {"title": "券商走强", "sentiment": 0.6, "sectors": ["证券"]},
            {"title": "AI 政策", "sentiment": -0.2, "themes": ["人工智能"]},
            {"title": "无关新闻", "sentiment": 0.9},
        ],
    )
    loaded = load_news(path, "2024-06-28")
    mapping = {"人工智能": {"sectors": ["软件开发"]}}
    scores, diagnostics = news_scores(loaded, _universe(), "2024-06-28", mapping=mapping)
    scores = scores.set_index("symbol")

    assert scores.loc["512880", "news_score"] == pytest.approx(0.6)
    assert scores.loc["159819", "news_score"] == pytest.approx(-0.2)
    assert "510300" not in scores.index
    assert diagnostics["n_matched_items"] == 2
    assert diagnostics["n_unmatched_items"] == 1


def test_overlay_is_bounded_changes_only_the_latest_day_and_reports_its_size():
    day = pd.Timestamp("2024-06-28")
    earlier = pd.Timestamp("2024-06-27")
    scores = pd.DataFrame(
        {
            "date": [earlier, earlier, day, day],
            "symbol": ["512880", "510300", "512880", "510300"],
            "composite": [0.5, 0.1, 0.9, 0.1],
            "confidence": [0.8, 0.8, 0.8, 0.8],
            "n_factors": [3, 3, 3, 3],
        }
    )
    news = pd.DataFrame(
        {"date": [day], "symbol": ["512880"], "news_score": [1.0], "n_items": [3], "titles": ["a | b | c"]}
    )

    adjusted, contributions = apply_news_overlay(scores, news, weight=0.2, max_abs=0.3)
    before = adjusted[adjusted["date"] == day].set_index("symbol")
    old = adjusted[adjusted["date"] == earlier].set_index("symbol")

    assert before.loc["512880", "composite"] == pytest.approx(1.1)
    assert before.loc["510300", "composite"] == pytest.approx(0.1)
    assert old.loc["512880", "composite"] == pytest.approx(0.5)  # history untouched
    row = contributions.set_index("symbol").loc["512880"]
    assert row["contribution"] == pytest.approx(0.2)
    assert row["composite_after"] - row["composite_before"] == pytest.approx(0.2)
    assert row["n_items"] == 3


def test_overlay_cap_applies_before_the_score_moves():
    scores = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-06-28")],
            "symbol": ["512880"],
            "composite": [0.9],
            "confidence": [0.8],
            "n_factors": [3],
        }
    )
    news = pd.DataFrame(
        {"date": [pd.Timestamp("2024-06-28")], "symbol": ["512880"], "news_score": [1.0], "n_items": [1], "titles": ["x"]}
    )

    adjusted, contributions = apply_news_overlay(scores, news, weight=1.0, max_abs=0.3)

    assert adjusted["composite"].iloc[0] == pytest.approx(1.2)
    assert contributions["contribution"].iloc[0] == pytest.approx(0.3)


def _price_cache(tmp_path, n_symbols: int = 10, days: int = 80) -> tuple[ParquetCache, Universe, str]:
    cache = ParquetCache(tmp_path)
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2024-03-01", periods=days)
    symbols = [f"5103{i:02d}" for i in range(n_symbols)]
    etfs = []
    for offset, symbol in enumerate(symbols):
        prices = 100 * np.cumprod(1 + rng.normal(0.0002 + offset * 1e-5, 0.008, days))
        cache.write(
            "etf_daily_hfq",
            symbol,
            pd.DataFrame(
                {
                    "date": index,
                    "symbol": symbol,
                    "close": prices,
                    "amount": 3e8,
                }
            ),
            source="test",
        )
        etfs.append(ETF(symbol=symbol, name=symbol, category="broad"))
    universe = Universe(version="u-test", etfs=etfs)
    return cache, universe, index[-1].date().isoformat()


def test_pipeline_reports_a_missing_overlay_instead_of_guessing(tmp_path):
    cache, universe, as_of = _price_cache(tmp_path)
    result = run_signal_pipeline(
        universe,
        as_of=as_of,
        cache_dir=cache.root,
        factor_names=("momentum_20", "reversal_5"),
        news_path=tmp_path / "absent.json",
        write=False,
    )

    overlay = result["overlays"]["news"]
    assert overlay["available"] is False
    assert overlay["applied"] is False
    assert overlay["contributions"] == []


def test_pipeline_applies_news_to_the_reported_score(tmp_path):
    cache, universe, as_of = _price_cache(tmp_path)
    path = tmp_path / "news.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {"title": "定向新闻", "sentiment": 0.8, "symbols": [universe.etfs[0].symbol]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = run_signal_pipeline(
        universe,
        as_of=as_of,
        cache_dir=cache.root,
        factor_names=("momentum_20", "reversal_5"),
        news_path=path,
        news_weight=0.5,
        news_max_abs=0.5,
        write=False,
    )

    overlay = result["overlays"]["news"]
    assert overlay["available"] and overlay["applied"]
    contribution = overlay["contributions"][0]
    assert contribution["symbol"] == universe.etfs[0].symbol
    assert contribution["contribution"] == pytest.approx(0.4)
    assert contribution["composite_after"] - contribution["composite_before"] == pytest.approx(0.4)


def test_empty_overlay_leaves_scores_untouched():
    scores = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-06-28")],
            "symbol": ["512880"],
            "composite": [0.9],
            "confidence": [0.8],
            "n_factors": [3],
        }
    )
    adjusted, contributions = apply_news_overlay(scores, pd.DataFrame())

    assert adjusted.equals(scores)
    assert contributions.empty
