from __future__ import annotations

from datetime import date

import pytest

from finagent.data.universe import load_universe


def test_load_universe_parses_fields(universe_yaml):
    u = load_universe(universe_yaml)
    assert u.version == "u-test"
    assert len(u.etfs) == 3
    assert u.by_symbol()["510300"].benchmark is True
    assert u.by_symbol()["511010"].index_data is False
    assert u.benchmark_symbols() == ["510300"]


def test_effective_period_filters_entries(universe_yaml):
    u = load_universe(universe_yaml)
    assert "511010" in u.symbols(date(2024, 6, 30))
    assert "511010" not in u.symbols(date(2025, 6, 30))
    assert "510300" in u.symbols(date(2015, 1, 1))
    assert "510300" not in u.symbols(date(2010, 1, 1))


def test_groups_map_symbols_to_categories(universe_yaml):
    u = load_universe(universe_yaml)
    groups = u.groups(date(2024, 6, 30))
    assert groups["512880"] == "sector"
    assert groups["510300"] == "broad"


def test_validate_flags_structural_problems(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
etfs:
  - symbol: "1"
    name: a
    category: nope
  - symbol: "1"
    name: b
    category: broad
    tracked_index: "000300"
""",
        encoding="utf-8",
    )
    problems = load_universe(path).validate()
    assert any("unknown category" in p for p in problems)
    assert any("duplicate symbol" in p for p in problems)
    assert "no benchmark ETF declared" in problems


def test_index_data_false_exempts_missing_tracked_index(tmp_path):
    path = tmp_path / "etfs.yaml"
    path.write_text(
        """
etfs:
  - symbol: "510300"
    name: 沪深300ETF
    category: broad
    tracked_index: "000300"
    benchmark: true
  - symbol: "513310"
    name: 中韩半导体ETF
    category: cross_border
    index_data: false
""",
        encoding="utf-8",
    )
    assert load_universe(path).validate() == []


def test_missing_required_field_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text('etfs:\n  - symbol: "510300"\n    name: x\n', encoding="utf-8")
    with pytest.raises(ValueError, match="category"):
        load_universe(path)


def test_real_config_is_valid():
    from finagent import config

    path = config.CONFIG_DIR / "universe.yaml"
    if not path.exists():
        pytest.skip("configs/universe.yaml not present")
    u = load_universe(path)
    assert u.validate() == []
