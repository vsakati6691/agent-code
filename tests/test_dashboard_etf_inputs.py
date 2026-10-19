import hashlib
import json
from datetime import date
from unittest.mock import Mock

import pytest

from agent_trading.dashboard import etf_inputs, spec, watchlist
from agent_trading.dashboard.pipeline import Context, _watchlist_etf
from agent_trading.dashboard.site_watchlist import _assumptions, etf_metadata_line, etf_sources
from tests.dashboard_fixtures import FakeProviders, make_bars

AS_OF = date(2026, 10, 16)
XML = """<edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><genInfo><seriesName>Corgi Lithography &amp; Semiconductor Photonics ETF</seriesName><seriesId>S000102689</seriesId><repPdDate>2026-06-30</repPdDate></genInfo><invstOrSecs><invstOrSec><name>Largest &amp; Co</name><pctVal>20.5</pctVal></invstOrSec><invstOrSec><name>Smaller</name><pctVal>3</pctVal></invstOrSec></invstOrSecs></edgarSubmission>"""


def test_new_version_changes_only_input_registration():
    raw = spec.spec_dict()
    raw.pop("live_gaps")  # 2026-10-19.3
    raw.pop("resilience_validation")  # 2026-10-19.2
    raw.pop("resilience")  # 2026-10-19.1
    raw.pop("xbrl_fill")  # 2026-10-19.5
    raw.pop("quarter_windows")  # 2026-10-19.4
    raw["market_cap_definition"] = spec.MARKET_CAP_DEFINITION_2026_10_13_1  # 2026-10-19.4
    # Remove later additive registrations (Leaders, private history, Cboe bars, Buy/Sell desk) to check the ETF delta.
    raw.pop("decision_desk")
    assert raw.pop("private_history") == spec.PRIVATE_HISTORY_RULE
    raw.pop("leaders_2030")
    raw.pop("external_datasets")
    raw.pop("price_bars")  # 2026-10-17.4
    raw.pop("snapshot_cadence")  # 2026-10-18.1
    raw["display_rules"]["freshness"][1] = spec.FRESHNESS_STALE_SESSIONS_2026_10_14_5
    raw["display_rules"]["watchlist_price"][0] = spec.WATCHLIST_PRICE_RULE_2026_10_14_5
    raw["version"] = "2026-10-14.9"
    assert raw["watchlist"].pop("etf_inputs_sha256") == etf_inputs.config_hash(etf_inputs.load())
    assert hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:16] == "13c2a70787a83822"


def test_dated_metadata_never_leaks_into_earlier_snapshots():
    assert etf_inputs.metadata("LAZR", date(2026, 10, 14)) is None
    meta = etf_inputs.metadata("LAZR", AS_OF)
    assert meta["label"] == "owner-supplied, unverified"
    assert meta["launched_under_12_months"]
    assert not etf_inputs.metadata("QQQ", AS_OF)["launched_under_12_months"]
    assert etf_inputs.metadata("RVI", AS_OF) is None  # closed-end venture fund is not relabelled as an ETF


@pytest.mark.parametrize("ticker", ["LAZR", "NCLD", "QQQ", "AIPO", "EUV", "NASA", "DRAM", "TQQQ", "SMH"])
def test_all_nine_etfs_use_curated_class_and_fee_with_assumptions(ticker):
    p = FakeProviders(AS_OF)
    p.bars["QQQ"] = make_bars(n=1300, end=AS_OF.isoformat())
    meta = etf_inputs.metadata(ticker, AS_OF)
    entry = {
        "ticker": ticker,
        "name": "ProShares UltraPro QQQ" if ticker == "TQQQ" else "Ambiguous listed ETF",
        "asset_type": "leveraged/inverse ETF" if ticker == "TQQQ" else "ETF",
        "sources": [],
        "missing": [],
    }
    _watchlist_etf(Context(AS_OF, p), entry, 100, 4)
    assert set(entry["scenarios"]) == {"bear", "base", "bull"}
    assert all(row["assumptions"]["assumed_fee"] == meta["expense_ratio"] for row in entry["scenarios"].values())
    assert "owner-supplied, unverified" in etf_metadata_line(entry)
    assert "inception:" in etf_metadata_line(entry) and "dated expense input" in _assumptions(entry)
    assert "SEC enrichment unavailable" in etf_sources(entry)


def test_fee_override_preserves_existing_default_and_equation():
    rule = spec.ETF_EXPOSURE_RULES[0]
    old = watchlist.etf_scenarios(100, rule, 4)
    assert old["base"]["annualized"] == pytest.approx(1.06 / 1.002 / 1.006 - 1)
    sourced = watchlist.etf_scenarios(100, rule, 4, fee=0.0018)
    assert sourced["base"]["annualized"] == pytest.approx(1.06 / 1.0018 / 1.006 - 1)


def test_filing_matches_series_dates_and_holding_units_without_inventing_expense():
    meta = etf_inputs.metadata("EUV", AS_OF)
    result = etf_inputs.parse_filing(XML, meta, "NPORT-P", AS_OF)
    assert result["top_holdings"][0] == {"name": "Largest & Co", "weight": 0.205}
    assert result["expense_ratio"] is None
    with pytest.raises(ValueError, match="series"):
        etf_inputs.parse_filing(XML.replace("S000102689", "S000000000"), meta, "NPORT-P", AS_OF)
    with pytest.raises(ValueError, match="future"):
        etf_inputs.parse_filing(XML.replace("2026-06-30", "2027-06-30"), meta, "NPORT-P", AS_OF)
    with pytest.raises(ValueError, match="Unsupported"):
        etf_inputs.parse_filing("<!DOCTYPE fake>" + XML, meta, "NPORT-P", AS_OF)


def test_collect_filters_future_filings_and_uses_raw_xml_only():
    p = Mock()
    p.http.budget_left.return_value = 100
    p.http.get_text.return_value = XML
    p.submissions.return_value = {
        "filings": {
            "recent": {
                "form": ["NPORT-P", "NPORT-P"],
                "filingDate": ["2027-01-01", "2026-08-01"],
                "accessionNumber": ["0000000000-27-000001", "0000000000-26-000001"],
                "primaryDocument": ["future.xml", "xslFormNPORT-P_X01/primary_doc.xml"],
            }
        }
    }
    result = etf_inputs.collect_filing(p, etf_inputs.metadata("EUV", AS_OF), AS_OF)
    assert result["status"] == "available" and result["filed_at"] == "2026-08-01"
    p.http.get_text.assert_called_once_with(
        "https://www.sec.gov/Archives/edgar/data/2078265/000000000026000001/primary_doc.xml", max_age_hours=168
    )
    p.http.budget_left.return_value = 25
    assert "reserved" in etf_inputs.collect_filing(p, etf_inputs.metadata("EUV", AS_OF), AS_OF)["reason"]
