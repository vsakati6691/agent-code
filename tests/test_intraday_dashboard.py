"""Exercise real Streamlit controls without a network provider or runtime ledger."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from agent_trading.intraday import store as store_module


def test_dashboard_controls_and_missing_data(monkeypatch, tmp_path):
    real_store = store_module.Store
    path = tmp_path / "ui.sqlite3"
    monkeypatch.setattr(store_module, "Store", lambda unused, cfg: real_store(path, cfg))
    app = Path(__file__).resolve().parents[1] / "src/agent_trading/intraday/dashboard.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    assert not at.exception
    assert "Intraday options lab" in at.title[0].value
    next(b for b in at.button if b.label == "Start scanner").click().run()
    next(b for b in at.button if b.label == "Enable paper entries").click().run()
    next(b for b in at.button if b.label == "Emergency stop").click().run()
    assert not at.exception
    assert next(b for b in at.button if b.label == "Enable paper entries").disabled
    next(b for b in at.button if b.label == "Run manual scan").click().run()
    assert not at.exception
    assert any("Scan unavailable" in e.value for e in at.error)
