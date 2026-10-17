"""Shared request counting, crash-safe reservations and provider-wide stopping."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from agent_trading.dashboard.http import BudgetExceeded, ProviderUnavailable
from agent_trading.data.alphavantage import AlphaVantageClient, AlphaVantageQuotaError
from agent_trading.data.service import MarketDataService
from agent_trading.provider_budget import DailyBudgetExceeded, DailyRequestBudget
from tests.test_dashboard_http import Resp, client
from tests.test_data_service import FakeClient


def test_budget_survives_clients_restarts_and_rolls_over(tmp_path):
    path = tmp_path / "budget.sqlite3"
    a = DailyRequestBudget(path, limit=2, day=date(2026, 10, 12))
    b = DailyRequestBudget(path, limit=2, day=date(2026, 10, 12))
    a.reserve()
    b.reserve()
    with pytest.raises(DailyBudgetExceeded):
        DailyRequestBudget(path, limit=2, day=date(2026, 10, 12)).reserve()
    tomorrow = DailyRequestBudget(path, limit=2, day=date(2026, 10, 13))
    assert tomorrow.remaining() == 2


def test_concurrent_reservations_cannot_exceed_cap(tmp_path):
    path = tmp_path / "budget.sqlite3"

    def reserve(_):
        try:
            DailyRequestBudget(path, limit=3).reserve()
            return True
        except DailyBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 3


def test_dashboard_and_local_client_share_budget_and_fail_before_request(tmp_path):
    path = tmp_path / "shared.sqlite3"
    http, session = client([Resp(200, b"csv")])
    http.daily_budget = DailyRequestBudget(path, limit=1)
    http.get_bytes("https://www.alphavantage.co/query")
    local = AlphaVantageClient("synthetic", session=object(), budget=DailyRequestBudget(path, limit=1))
    with pytest.raises(AlphaVantageQuotaError):
        local.daily_bars("SPY")
    assert local.calls_made == 0 and len(session.calls) == 1


@pytest.mark.parametrize("response", [Resp(429), Resp(402), Resp(200, b'{"Information":"quota"}')])
def test_dashboard_quota_stops_without_retry_and_persists(response):
    http, session = client([response])
    with pytest.raises(ProviderUnavailable):
        http.get_bytes("https://www.alphavantage.co/query")
    other, other_session = client([])
    with pytest.raises(BudgetExceeded):
        other.get_bytes("https://www.alphavantage.co/query")
    assert len(session.calls) == 1 and other_session.calls == []


def test_local_quota_response_stops_future_clients():
    class Session:
        def get(self, *args, **kwargs):
            return Resp(200, b'{"Note":"quota"}')

    first = AlphaVantageClient("synthetic", session=Session(), pause_seconds=0)
    with pytest.raises(AlphaVantageQuotaError):
        first.daily_bars("SPY")
    second = AlphaVantageClient("synthetic", session=object(), pause_seconds=0)
    with pytest.raises(AlphaVantageQuotaError):
        second.daily_bars("SPY")
    assert second.calls_made == 0


def test_service_stops_after_quota_but_keeps_per_symbol_failures_independent(settings):
    class QuotaClient(FakeClient):
        def daily_bars(self, *args):
            self.calls_made += 1
            raise AlphaVantageQuotaError("quota")

    quota = QuotaClient()
    service = MarketDataService(settings, quota)
    statuses = service.refresh(["A", "B", "C"], date(2026, 10, 12))
    service.refresh_earnings(date(2026, 10, 12))
    assert quota.calls_made == 1 and "skipped" in statuses["B"]
    ordinary = FakeClient(fail={"A"})
    statuses = MarketDataService(settings, ordinary).refresh(["A", "B"], date(2026, 10, 12))
    assert ordinary.calls_made == 2 and statuses["B"].startswith("updated")


def test_corrupt_budget_fails_closed(tmp_path):
    path = tmp_path / "budget.sqlite3"
    path.write_text("not a database", encoding="utf-8")
    with pytest.raises(DailyBudgetExceeded):
        DailyRequestBudget(path).reserve()
