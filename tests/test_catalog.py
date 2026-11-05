from __future__ import annotations

from finagent.data.catalog import coverage_notes, load_catalog, validate_catalog

COLLECTED = {
    "etf_daily_hfq",
    "etf_nav",
    "etf_spot",
    "etf_scale_sse",
    "index_daily",
    "index_valuation",
    "index_value_snapshot",
    "sector_flow_rank",
    "sector_flow_hist",
    "market_flow",
    "margin_sse",
    "bond_yield",
    "macro",
    "trade_calendar",
}


def test_real_catalog_registers_every_collected_dataset():
    catalog = load_catalog()
    assert validate_catalog(catalog, required=COLLECTED) == []


def test_unavailable_datasets_are_documented():
    notes = coverage_notes(load_catalog())
    assert "sector_flow_hist" in notes
    assert "Eastmoney" in notes["sector_flow_hist"]


def test_validate_flags_missing_and_incomplete(tmp_path):
    path = tmp_path / "catalog.yaml"
    path.write_text(
        """
datasets:
  etf_daily_hfq:
    source: x
    frequency: daily
    fields: [date]
""",
        encoding="utf-8",
    )
    catalog = load_catalog(path)
    problems = validate_catalog(catalog, required={"etf_daily_hfq", "macro"})
    assert any("macro: used by the collector" in p for p in problems)
    assert any("etf_daily_hfq: missing" in p for p in problems)
