"""Customer edition (site_customer): left-out pages, links and broker-derived data never reach the output."""

import json
import re

import pytest

from agent_trading.dashboard import evidence, site_customer
from agent_trading.dashboard.render_context import RenderContext, rendering
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import Store
from tests.dashboard_ci import check_links
from tests.dashboard_fixtures import demo_site


@pytest.fixture(scope="module")
def editions(tmp_path_factory):
    data, full = demo_site(tmp_path_factory.mktemp("demo"))
    customer = tmp_path_factory.mktemp("customer") / "site"
    info = build_site(data, customer, edition="customer")
    return data, full, customer, info


def read(path):
    return path.read_text(encoding="utf-8")


def test_customer_edition_leaves_out_pages_data_and_links(editions):
    data, full, customer, info = editions
    assert info["edition"] == "customer" and json.loads(read(customer / "build.json"))["edition"] == "customer"
    for name in site_customer.HIDDEN_PAGES:
        assert (full / name).exists() and not (customer / name).exists()
    assert (full / "desk").is_dir() and not (customer / "desk").exists() and not (customer / "option").exists()
    assert not list(customer.glob("options-*.html")) and not list(customer.glob("downloads/*_options_*.csv"))
    assert site_customer.check(customer) == [] and check_links(customer) == []
    nav = re.search(r'<nav aria-label="Research sections">(.*?)</nav>', read(customer / "index.html")).group(1)
    assert 'href="terms.html"' in nav
    assert not any(f'href="{name}"' in nav for name in site_customer.HIDDEN_PAGES)
    for name in ("latest.json", f"{Store(data).dates()[-1]}.json"):
        published = json.loads(read(customer / "data" / name))
        assert not set(site_customer.DROPPED_KEYS) & set(published) and "broker_calendar" not in published
    schema = json.loads(read(customer / "data" / "schema.json"))
    assert not set(site_customer.DROPPED_KEYS) & set(schema["properties"])
    audit = read(customer / "audit.html")
    assert "Option chains" not in audit and "tradability verdicts" not in audit and 'id="options-data"' not in audit
    symbol = next((customer / "symbol").glob("*.html"))
    assert "Option contracts" not in read(symbol) and "Watchlist 2030" not in read(symbol)


def test_customer_terms_page_is_linked_and_marked_draft_until_reviewed(editions):
    customer = editions[2]
    terms = read(customer / "terms.html")
    assert "Not investment advice" in terms and "No performance claim" in terms and "No warranty" in terms
    assert "Draft terms" in terms and site_customer.TERMS_STATUS == "draft"
    assert 'href="terms.html">Terms of use</a>' in read(customer / "growth.html")


def test_full_edition_is_unchanged(editions):
    full = editions[1]
    assert (full / "options.html").exists() and (full / "desk.html").exists() and (full / "goal.html").exists()
    assert not (full / "terms.html").exists() and "terms.html" not in read(full / "index.html")
    assert json.loads(read(full / "build.json"))["edition"] == "full"


def test_sanitize_never_touches_the_stored_snapshot(editions):
    store = Store(editions[0])
    snap = store.load(store.dates()[-1])
    before = json.dumps(snap, sort_keys=True, default=str)
    clean = site_customer.sanitize(snap)
    assert json.dumps(snap, sort_keys=True, default=str) == before and store.verify_all() == []
    assert not set(site_customer.DROPPED_KEYS) & set(clean)
    assert "Robinhood tradability" not in json.dumps(clean)


def test_customer_datasets_omit_broker_and_option_rows(editions):
    store = Store(editions[0])
    snap = store.load(store.dates()[-1])
    full = {r["dataset"] for r in evidence.datasets(snap)}
    with rendering(RenderContext(edition="customer")):
        customer = {r["dataset"] for r in evidence.datasets(snap)}
    assert "Option chains" in full and not customer & evidence.CUSTOMER_OMITTED_DATASETS
    assert customer == full - evidence.CUSTOMER_OMITTED_DATASETS


def test_check_blocks_planted_leaks_but_allows_company_names(tmp_path):
    (tmp_path / "a.html").write_text('<p><a href="../desk/NVDA.html">x</a></p>', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"source": "Robinhood MCP get_equity_tradability"}', encoding="utf-8")
    (tmp_path / "c.html").write_text("<td>Robinhood Markets, Inc. Class A</td>", encoding="utf-8")
    (tmp_path / "d.json").write_text('{"options": {}}', encoding="utf-8")
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "2026-10-16_options_3m_calls.csv").write_text("rank\n", encoding="utf-8")
    (tmp_path / "goal.html").write_text("<p>plan</p>", encoding="utf-8")
    problems = site_customer.check(tmp_path)
    for marker in ("a.html", "b.json", "d.json", "_options_3m_calls.csv", "goal.html"):
        assert any(marker in p for p in problems), marker
    assert not any(p.startswith("c.html") for p in problems)


def test_unknown_edition_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown site edition"):
        build_site(tmp_path, tmp_path / "out", edition="public")
