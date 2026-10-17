"""Fixture-based public datasets, bounded network accounting and backward-compatible builds."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_trading.dashboard import macro, options, pipeline_external, sec_insiders, sec_institutions, short_interest
from agent_trading.dashboard.decision_sources import FilingText, parse_efts, risk_excerpt
from agent_trading.dashboard.http import SEC_SUBCAPS, BudgetExceeded, FetchError, HttpClient, ProviderLimits
from agent_trading.dashboard.providers import Providers
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.site_external import OLD, csv_fields, macro_rows
from agent_trading.dashboard.store import IntegrityError, Store
from tests.dashboard_ci import check_links
from tests.dashboard_fixtures import demo_site
from tests.test_dashboard_http import Resp, Session

FIX = Path(__file__).parent / "fixtures" / "dashboard_external"
AS_OF = date(2026, 10, 15)
ACC = "0000000123-26-000004"


def fixture(name):
    return (FIX / name).read_text(encoding="utf-8")


def archive(*names, replacements=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.writestr(name, (replacements or {}).get(name, fixture(name)))
    return out.getvalue()


def http(responses, tmp_path=None):
    session = Session(responses)
    client = HttpClient(tmp_path, "fixture test@example.com", session=session, sleep=lambda _: None)
    client.limits = {key: ProviderLimits(0, val.budget) for key, val in client.limits.items()}
    return client, session


def parsed_form():
    return sec_insiders.parse_form4((FIX / "form4.xml").read_bytes(), ACC, "2026-10-03", 123)


def test_form4_classification_windows_plans_and_future_rows():
    filing = parsed_form()
    assert filing["plan_10b5_1"] is True
    result = sec_insiders.aggregate([filing], AS_OF)
    assert result["state"] == "available"
    assert result["classification_basis"] == sec_insiders.CLASSIFICATION
    assert result["windows"]["90d"]["net_shares"] == 60
    assert result["windows"]["90d"]["net_dollars"] == 1000
    assert result["windows"]["12m"]["net_shares"] == 90
    assert result["windows"]["12m"]["net_dollars"] == 1300
    assert result["windows"]["12m"]["buyers"] == result["windows"]["12m"]["sellers"] == 1
    assert result["excluded_rows"] == {"A": 1, "M": 1, "F": 1, "G": 1, "derivative": 1}
    assert result["latest_transaction_date"] == "2026-10-02"


def test_incomplete_form4_windows_are_never_zero_or_partial_totals():
    filing = parsed_form()
    for reason in ("deferred to next run", "Unusable filing"):
        result = sec_insiders.aggregate([filing], AS_OF, reason)
        assert result["state"] == "partial"
        assert all(w["net_shares"] is None and w["buyers"] is None for w in result["windows"].values())
    filing["form"] = "4/A"
    result = sec_insiders.aggregate([filing], AS_OF)
    assert "reconciliation" in result["reason"] and result["windows"]["90d"]["net_dollars"] is None
    filing = parsed_form()
    filing["transactions"][0]["price"] = None
    result = sec_insiders.aggregate([filing], AS_OF)
    assert result["windows"]["90d"]["net_shares"] == 60
    assert result["windows"]["90d"]["net_dollars"] is None


def test_form4_rejects_wrong_issuer_and_entities():
    with pytest.raises(FetchError):
        sec_insiders.parse_form4((FIX / "form4.xml").read_bytes(), ACC, "2026-10-03", 999)
    with pytest.raises(FetchError):
        sec_insiders.parse_form4(b'<!DOCTYPE x [<!ENTITY x "x">]><ownershipDocument/>', ACC, "2026-10-03", 123)


def test_form4_reuses_prior_filings_and_reports_budget_shortfall():
    sub = {
        "filings": {
            "recent": {
                "form": ["4"],
                "filingDate": ["2026-10-03"],
                "accessionNumber": [ACC],
                "primaryDocument": ["xslF345X05/owner.xml"],
            }
        }
    }
    c, session = http([Resp(body=json.dumps(sub).encode()), Resp(body=(FIX / "form4.xml").read_bytes())])
    p = Providers(c)
    first = sec_insiders.collect(p, 123, AS_OF)
    assert first["state"] == "available" and len(session.calls) == 2
    second = sec_insiders.collect(p, 123, AS_OF, first)
    assert second == first and len(session.calls) == 2
    c.group_used["sec_insiders"] = SEC_SUBCAPS["sec_insiders"]
    result = sec_insiders.collect(p, 456, AS_OF)
    assert result["state"] == "partial" and result["reason"] == "deferred to next run"
    assert len(session.calls) == 2


def test_sec_subcaps_count_retries_and_preserve_core_reserve():
    c, session = http([Resp(503), Resp(503), Resp(), Resp()])
    with c.budget_group("sec_risk", max_attempts=2), pytest.raises(BudgetExceeded):
        c.get_bytes("https://efts.sec.gov/LATEST/search-index")
    assert c.group_used["sec_risk"] == 2 and len(session.calls) == 2
    c.group_used["sec_insiders"] = 1800
    with c.budget_group("sec_insiders"), pytest.raises(BudgetExceeded):
        c.get_bytes("https://www.sec.gov/Archives/test")
    c.get_bytes("https://data.sec.gov/core")
    assert c.group_used["sec_core"] == 1 and c.used["sec"] == 3
    assert all(call[2]["User-Agent"] == c.user_agent for call in session.calls)
    assert sum(SEC_SUBCAPS.values()) <= 6000


def test_sec_pacing_is_shared_across_hosts():
    waits = []
    c, _ = http([Resp(), Resp()])
    now = [100.0]
    c.clock = lambda: now[0]
    c.sleep = lambda delay: (waits.append(delay), now.__setitem__(0, now[0] + delay))
    c.limits["sec"].min_interval = 0.15
    c.get_bytes("https://data.sec.gov/first")
    with c.budget_group("sec_risk"):
        c.get_bytes("https://efts.sec.gov/second")
    assert sum(waits) >= 0.15


def test_13f_slice_reconciles_managers_amendments_and_share_types():
    body = archive("SUBMISSION.tsv", "COVERPAGE.tsv", "INFOTABLE.tsv")
    data = sec_institutions.aggregate_zip(body, date(2026, 6, 30), AS_OF)
    assert data["state"] == "available"
    assert data["archive_sha256"] == hashlib.sha256(body).hexdigest()
    record = data["by_cusip"]["000000001"]
    assert record["holder_count"] == 2 and record["reported_shares"] == 200
    assert record["top_holders"] == [
        {"cik": "100", "name": "Manager One", "shares": 140},
        {"cik": "200", "name": "Manager Two", "shares": 60},
    ]
    bad = archive(
        "SUBMISSION.tsv",
        "COVERPAGE.tsv",
        "INFOTABLE.tsv",
        replacements={"COVERPAGE.tsv": fixture("COVERPAGE.tsv").replace("RESTATEMENT", "UNKNOWN")},
    )
    assert sec_institutions.aggregate_zip(bad, date(2026, 6, 30), AS_OF)["state"] == "partial"


def test_ftd_gaps_ambiguity_and_institutional_change_staleness():
    mapping = sec_institutions.ftd_mapping(archive("ftd.txt"), AS_OF)
    assert mapping["symbols"]["ABC"]["cusip"] == "000000001"
    assert "FUT" not in mapping["symbols"]
    assert mapping["symbols"]["AMB"]["reason"] == "Ambiguous CUSIP mapping"
    assert sec_institutions.company([], mapping, "GAP", AS_OF)["reason"] == "no CUSIP mapping"
    latest = sec_institutions.aggregate_zip(
        archive("SUBMISSION.tsv", "COVERPAGE.tsv", "INFOTABLE.tsv"), date(2026, 6, 30), AS_OF
    )
    prior = copy.deepcopy(latest)
    prior["report_quarter_end"] = "2026-03-31"
    prior["by_cusip"]["000000001"].update(holder_count=1, reported_shares=150)
    result = sec_institutions.company([latest, prior], mapping, "ABC", AS_OF)
    assert result["state"] == "available" and result["holder_count_change"] == 1
    assert result["reported_shares_change"] == 50 and result["stale_after"] == "2026-11-14"
    assert sec_institutions.company([latest], mapping, "ABC", date(2026, 11, 15))["state"] == "stale"
    assert sec_institutions.archive_period("https://www.sec.gov/files/01jun2026-31aug2026_form13f.zip") == (
        date(2026, 8, 31),
        date(2026, 6, 30),
    )


def test_aggregate_cache_is_immutable_hashed_and_contains_no_raw_archive(tmp_path):
    store = Store(tmp_path)
    payload = {"source": "https://www.sec.gov/archive.zip", "archive_sha256": "a" * 64, "by_cusip": {}}
    store.write_source_aggregate("13f", "2026-06-30", payload)
    assert store.write_source_aggregate("13f", "2026-06-30", {"different": True}) == payload
    assert store.verify_all() == []
    assert {p.suffix for p in tmp_path.rglob("*") if p.is_file()} == {".json"}
    file = tmp_path / "source_aggregates/13f/2026-06-30/aggregate.json"
    file.write_text("{}", encoding="utf-8")
    with pytest.raises(IntegrityError, match="hash mismatch"):
        store.source_aggregate("13f", "2026-06-30")
    assert store.verify_all()


def test_efts_filters_dates_issuer_and_extracts_exact_quotation():
    filing = parse_efts(json.loads(fixture("efts.json")), 123, AS_OF)
    assert filing["form"] == "10-Q" and filing["filed"] == "2026-08-01"
    result = risk_excerpt(fixture("risk.html"), filing)
    parser = FilingText()
    parser.feed(fixture("risk.html"))
    normalized = re.sub(r"\s+", " ", " ".join(parser.parts))
    lo, hi = result["character_range"]
    assert result["excerpt"] == normalized[lo:hi]
    assert result["excerpt"].startswith("Our dependence")
    assert result["text_sha256"] == hashlib.sha256(normalized.encode()).hexdigest()
    assert risk_excerpt("<p>No identified section.</p>", filing)["state"] == "missing"
    with pytest.raises(FetchError):
        parse_efts({"changed": True}, 123, AS_OF)


def test_risk_refresh_max_two_attempts_retains_prior_excerpt():
    c, session = http([Resp(503), Resp(503)])
    ctx = SimpleNamespace(as_of=AS_OF, providers=Providers(c))
    prior = {"risk_excerpt": {"excerpt": "Stored quotation", "filed": "2025-01-01", "state": "available"}}
    result = pipeline_external._risk(ctx, 123, prior, {})
    assert result["excerpt"] == "Stored quotation"
    assert result["state"] == "partial" and result["reason"] == "excerpt refresh deferred"
    assert len(session.calls) == 2


def test_legacy_risk_quotation_is_reused_without_efts_when_current():
    c, session = http([])
    p = Providers(c)
    p._submissions[123] = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "filingDate": ["2026-02-01"],
                "accessionNumber": ["0000000123-26-000001"],
                "primaryDocument": ["annual.htm"],
            }
        }
    }
    ctx = SimpleNamespace(as_of=AS_OF, providers=p)
    prior = {
        "legacy_business": {
            "risk": "Previously stored issuer quotation.",
            "filed": "2026-02-01",
            "url": "https://www.sec.gov/Archives/annual.htm",
        }
    }
    result = pipeline_external._risk(ctx, 123, prior, {})
    assert result["excerpt"] == prior["legacy_business"]["risk"]
    assert result["state"] == "available" and result["character_range"] is None
    assert "Legacy" in result["range_reason"] and not session.calls


def test_fred_vintage_cpi_dates_and_missing_year_prior():
    raw = json.loads(fixture("fred.json"))
    result = macro.parse_series(raw["observations"], raw["metadata"], "CPIAUCSL", AS_OF)
    assert result["value"] == 309 and result["yoy"] == pytest.approx(0.03)
    assert result["yoy_dates"] == ["2025-09-01", "2026-09-01"]
    assert result["last_updated"] == "2026-10-14 07:42:00-05"
    raw["observations"]["observations"].pop(1)
    result = macro.parse_series(raw["observations"], raw["metadata"], "CPIAUCSL", AS_OF)
    assert result["state"] == "partial" and result["yoy"] is None


def test_fred_missing_key_budget_and_error_redaction():
    c, session = http([])
    assert macro.collect(Providers(c), AS_OF)["state"] == "missing" and not session.calls
    c.used["fred"] = c.limits["fred"].budget
    p = Providers(c, fred_key="fixture-placeholder")
    result = macro.collect(p, AS_OF)
    assert result["state"] == "partial" and all(r["state"] == "partial" for r in result["series"].values())
    assert "fixture-placeholder" not in json.dumps(result)


def test_dated_rate_changes_model_values_but_preserves_contract_ranking():
    rate = {"value": 0.025, "date": "2026-10-14", "source": "https://fred.stlouisfed.org/series/DGS1MO"}
    original = options.sensitivity(100, 100, 0.5, 0.3, 5)
    row = {
        "spot": 100,
        "strike": 100,
        "dte": 182.5,
        "iv": 0.3,
        "mid": 5,
        "type": "call",
        "rank": 1,
        "rank_components": {"total": 75},
        "sensitivity": original,
    }
    options.apply_dated_rate([row], rate)
    assert row["rank_components"] == {"total": 75} and row["rank"] == 1
    assert row["sensitivity"]["model_value_now"] != original["model_value_now"]
    assert row["sensitivity"]["rate_input"]["date"] == "2026-10-14"
    options.apply_dated_rate([row], macro.rate_input(None))
    assert row["sensitivity"]["grid"] == [] and "unavailable" in row["sensitivity"]["note"]


def test_finra_strict_schema_and_xbrl_denominator_not_float_or_report_volume():
    row = short_interest.parse_file(fixture("finra.csv"), AS_OF)["ABC"]
    assert row["shares_short"] == 500 and row["change_shares"] == 100
    got = short_interest.with_denominator(row, 10000, "2026-06-30")
    assert got["percent_of_diluted_shares"] == 0.05 and got["percent_label"] == short_interest.LABEL
    assert got["days_to_cover"] is None and "not stored" in got["days_to_cover_reason"]
    assert short_interest.with_denominator(row, 10000, None)["percent_of_diluted_shares"] is None
    assert short_interest.with_denominator(row, 10000, "2026-06-30", 250)["days_to_cover"] == 2
    for bad in (
        fixture("finra.csv").replace("symbolCode", "changed"),
        fixture("finra.csv") + fixture("finra.csv").splitlines()[1],
        fixture("finra.csv").replace('"500"', '"invalid"'),
    ):
        with pytest.raises(FetchError, match="entire dataset rejected"):
            short_interest.parse_file(bad, AS_OF)


def test_old_snapshot_build_keeps_bytes_and_explains_all_new_gaps(tmp_path):
    data, _ = demo_site(tmp_path / "original")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()}
    out = tmp_path / "rebuilt"
    build_site(data, out)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()}
    assert check_links(out) == []
    html = next((out / "stock").glob("*.html")).read_text(encoding="utf-8")
    assert all(
        label in html
        for label in ("Insider activity", "Institutional holders", "Short interest", "Risk-factor quotation")
    )
    assert OLD in html and "Macro data not collected this week" in (out / "index.html").read_text(encoding="utf-8")
    assert all(
        csv_fields({})[key + "_reason"] == OLD for key in ("insiders", "institutions", "short_interest", "risk_excerpt")
    )
    assert all(r["state"] == "missing" and r["reason"] == OLD for r in macro_rows({}))
    assert max(p.stat().st_size for p in out.rglob("*.html")) < 150_000


def test_dry_run_is_manual_read_only_artifacts_and_skips_production():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/research-dashboard.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["workflow_dispatch"]["inputs"]["dry_run"]["default"] is False
    jobs = workflow["jobs"]
    job = jobs["dry-run"]
    assert job["if"] == "github.event_name == 'workflow_dispatch' && inputs.dry_run == true"
    assert job["timeout-minutes"] == jobs["update"]["timeout-minutes"] == 240
    assert job["permissions"] == {"contents": "read"}
    for name in ("update", "deploy", "result"):
        assert "!inputs.dry_run" in jobs[name]["if"]
    for step in job["steps"]:
        assert not any(x in step.get("run", "") for x in ("git push", "git worktree", "git checkout"))
        assert "deploy-pages" not in step.get("uses", "")
    upload = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert "scratch/http" not in upload["with"]["path"]


def test_company_scope_and_exhaustion_keep_ranks_and_report_shortfall():
    c, session = http([])
    c.group_used = dict(SEC_SUBCAPS)
    c.used["finra"] = c.limits["finra"].budget
    ctx = SimpleNamespace(as_of=AS_OF, started="2026-10-16T12:00:00+00:00", providers=Providers(c), facts={})
    ranked = {"ticker": "ABC", "cik": 123, "rank": 1, "score": 71}
    watch = {"ticker": "DEF", "cik": 456, "asset_type": "operating company"}
    fund = {"ticker": "ETF", "asset_type": "unleveraged ETF"}
    bands, watchlist = {"large": {"candidates": [ranked]}}, {"entries": [watch, fund]}
    status = pipeline_external.collect(ctx, bands, watchlist, None)
    assert status["insiders"]["requested"] == status["insiders"]["deferred"] == 2
    assert all(r["state"] == "partial" for r in status.values())
    assert ranked["rank"] == 1 and ranked["score"] == 71 and "external" not in fund
    assert not session.calls


def test_bulk_indexes_are_not_used_to_infer_historical_release_dates():
    c, session = http([])
    ctx = SimpleNamespace(as_of=date(2026, 1, 2), started="2026-10-16T12:00:00+00:00", providers=Providers(c), facts={})
    ranked = {"ticker": "ABC"}
    pipeline_external.collect(ctx, {"large": {"candidates": [ranked]}}, {}, None)
    for key in ("institutions", "short_interest"):
        assert "historical" in ranked["external"][key]["reason"]
    assert not session.calls


def test_populated_renderers_and_csv_keep_sources_and_specific_gaps():
    import csv

    from agent_trading.dashboard.site_downloads import external_csv, macro_csv
    from agent_trading.dashboard.site_external import company, macro_context, rate_note
    from tests.test_dashboard_site import FORBIDDEN, visible_text

    holdings = sec_institutions.aggregate_zip(
        archive("SUBMISSION.tsv", "COVERPAGE.tsv", "INFOTABLE.tsv"), date(2026, 6, 30), AS_OF
    )
    holdings["source"] = "https://www.sec.gov/archive.zip"
    mapping = sec_institutions.ftd_mapping(archive("ftd.txt"), AS_OF)
    mapping.update(file_date="2026-09-30", source="https://www.sec.gov/ftd.zip")
    insider = sec_insiders.aggregate([parsed_form()], AS_OF)
    insider["filings"][0]["url"] = "https://www.sec.gov/Archives/owner.xml"
    short = short_interest.with_denominator(
        short_interest.parse_file(fixture("finra.csv"), AS_OF)["ABC"], 10000, "2026-06-30"
    )
    short["source"] = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260930.csv"
    record = {
        "ticker": "ABC",
        "external": {
            "insiders": insider,
            "institutions": sec_institutions.company([holdings], mapping, "ABC", AS_OF),
            "short_interest": short,
            "risk_excerpt": risk_excerpt(
                fixture("risk.html"), parse_efts(json.loads(fixture("efts.json")), 123, AS_OF)
            ),
        },
    }
    snap = {
        "as_of": str(AS_OF),
        "bands": {"large": {"candidates": [record]}},
        "macro": {
            "series": {
                "DGS1MO": {
                    "state": "available",
                    "value": 3.5,
                    "observation_date": "2026-10-14",
                    "source": "https://fred.stlouisfed.org/series/DGS1MO",
                }
            }
        },
    }
    rendered = company(record) + macro_context(snap) + rate_note(snap)
    assert "Manager One" in rendered and "2026-06-30" in rendered and "DGS1MO 3.500%" in rendered
    assert "Average daily share volume not stored" in rendered and "characters" in rendered
    csv_text = external_csv(snap)
    row = next(csv.DictReader(io.StringIO(csv_text)))
    assert row["insider_90d_net_shares"] == "60" and "10b5-1: yes" in row["insider_filings"]
    assert "Manager One" in row["institutions_top_holders"] and row["short_interest_shares_date"] == "2026-06-30"
    assert len(list(csv.DictReader(io.StringIO(macro_csv(snap))))) == 7
    for pattern, _ in FORBIDDEN:
        assert not re.search(pattern, visible_text(rendered))
        assert not re.search(pattern, csv_text)
