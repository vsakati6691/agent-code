"""Run with streamlit, bound to localhost. This UI is never published to GitHub Pages."""

import json
import os
from datetime import UTC, datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent_trading.intraday.calendar import NY, session
from agent_trading.intraday.config import load_config
from agent_trading.intraday.engine import Simulator
from agent_trading.intraday.longbridge_provider import LongbridgeProvider
from agent_trading.intraday.providers import FileProvider, MassiveProvider
from agent_trading.intraday.reporting import performance
from agent_trading.intraday.service import Service
from agent_trading.intraday.store import Store


def main():
    st.set_page_config(page_title="Intraday options lab", layout="wide")
    st.title("Intraday options lab")
    st.caption("Local paper simulation · Read-only market data · Research results, not an established edge")
    load_dotenv(".env", override=False)
    config_path = st.sidebar.text_input("Configuration", "config/intraday_options.yaml")
    database = st.sidebar.text_input("Local ledger", "data/intraday/longbridge-paper.sqlite3")
    source = st.sidebar.selectbox("Market data", ["Longbridge", "Normalized JSON", "Massive"])
    snapshot_path = st.sidebar.text_input("Snapshot file", "data/intraday/latest.json")
    events_path = st.sidebar.text_input("Event clearance file (Massive)", "")
    automate = st.sidebar.checkbox("Run scheduler while this dashboard is open", value=False)
    st.sidebar.info("For continuous operation, keep the CLI scheduler running. Closing every process stops monitoring.")
    try:
        cfg = load_config(config_path)
    except (OSError, ValueError):
        st.error("Configuration unavailable or invalid.")
        return

    def get_provider():
        key = (source, config_path, snapshot_path, events_path)
        if st.session_state.get("provider_key") != key:
            old = st.session_state.pop("market_provider", None)
            if isinstance(old, LongbridgeProvider):
                old.close()
            st.session_state["provider_key"] = key
        if "market_provider" not in st.session_state:
            if source == "Longbridge":
                provider = LongbridgeProvider(cfg)
            elif source == "Massive":
                provider = MassiveProvider(os.getenv("MASSIVE_API_KEY", ""), cfg, events_path or None)
            else:
                provider = FileProvider(snapshot_path)
            st.session_state["market_provider"] = provider
        return st.session_state["market_provider"]

    @st.fragment(run_every=5)
    def panel():
        now = datetime.now(UTC)
        try:
            store = Store(database, cfg)
        except (ValueError, OSError):
            st.error("Ledger unavailable or configuration differs from its pinned methodology.")
            return
        try:
            engine = Simulator(store, cfg)

            def service():
                return Service(store, cfg, get_provider(), alerts="data/intraday/alerts.jsonl")

            controls = st.columns(5)
            if controls[0].button("Start scanner"):
                engine.controls(now, running=True)
            if controls[1].button("Stop scanner"):
                engine.controls(now, running=False, enabled=False)
            if controls[2].button("Enable paper entries", disabled=store.get("killed") == "true"):
                engine.controls(now, enabled=True)
            if controls[3].button("Disable new entries"):
                engine.controls(now, enabled=False)
            if controls[4].button("Emergency stop", type="primary"):
                engine.controls(now, emergency=True)
                st.rerun()
            if st.button("Run manual scan"):
                try:
                    service().manual_scan()
                except Exception as exc:
                    with store.transaction():
                        store.event(
                            now, "provider_failure", {"reason": type(exc).__name__, "action": "manual scan failed"}
                        )
                    st.error("Scan unavailable. Check source, credentials, timestamps and event coverage.")
            if automate:
                try:
                    service().tick()
                except Exception:
                    st.error("Scheduler could not complete this tick; inspect local event log.")
            current = session(now.astimezone(NY).date())
            market_open = bool(current and current.open <= now < current.close)
            st.write(
                f"Scanner: {'running' if store.get('running') == 'true' else 'stopped'} · New entries: {store.get('enabled')} · Market: {'open' if market_open else 'closed'}"
            )
            if store.get("killed") == "true":
                st.error(
                    "Emergency stop latched. No new entries. Existing positions still require fresh quotes and an active monitor."
                )
            st.caption(f"Last scheduler heartbeat: {store.get('heartbeat') or 'none'}")
            provider_status = json.loads(store.get("provider_status", "{}"))
            if provider_status:
                st.caption(f"Data collector: {provider_status.get('progress', 'unknown')}")
                for problem in provider_status.get("problems", []):
                    st.warning(problem)
            report = performance(store, cfg)
            metrics = st.columns(4)
            metrics[0].metric("Realized net simulated P&L", f"${report['realized_net_pnl']:.2f}")
            metrics[1].metric("Closed trades", report["closed_trades"])
            metrics[2].metric("Win rate", "—" if report["win_rate"] is None else f"{report['win_rate']:.1%}")
            metrics[3].metric(
                "Profit factor", "—" if report["profit_factor"] is None else f"{report['profit_factor']:.2f}"
            )
            daily = performance(store, cfg, now.astimezone(NY).date())
            st.write(
                f"Today: {daily['filled_entries']} filled entries · Realized net P&L ${daily['realized_net_pnl']:.2f}"
            )
            raw = store.get("last_scan")
            if raw:
                latest = json.loads(raw)
                st.subheader("Latest scan")
                st.caption(
                    f"{latest['feed']} · {latest['source']} · observed {latest['timestamp']} · coverage {latest['scanned']}/{latest['expected']}"
                )
                if latest["feed"] == "fixture":
                    st.warning("SYNTHETIC TEST FIXTURES — these are not market signals or performance evidence.")
                stale = (now - datetime.fromisoformat(latest["timestamp"])).total_seconds() > cfg.max_bar_age_seconds
                if stale:
                    st.warning("Stored scan is stale. Displayed candidates cannot authorize new entries.")
                for problem in latest["problems"]:
                    st.warning(problem)
                for column, right in zip(st.columns(2), ["CALL", "PUT"], strict=True):
                    candidates = sorted(
                        [s for s in latest["signals"] if s["qualified"] and s["right"] == right],
                        key=lambda s: -s["score"],
                    )[:5]
                    column.write(f"Top {right} candidates")
                    column.dataframe(pd.DataFrame(candidates), hide_index=True)
                with st.expander("Rejection reasons"):
                    st.json(latest["rejected"])
                universe_scan = store.get("universe_scan")
                if universe_scan:
                    with st.expander("Full-universe ranking before contract checks"):
                        st.json(json.loads(universe_scan))
            else:
                st.info(
                    "No scan yet. Configure Longbridge in .env, verify OPRA OpenAPI access, and start the local scheduler."
                )
            st.subheader("Open simulated positions")
            marks = json.loads(store.get("marks", "{}"))
            rows = []
            for p in report["open_positions"]:
                mark = marks.get(p["contract"], {})
                stamp = mark.get("quote_at")
                if not stamp or (now - datetime.fromisoformat(stamp)).total_seconds() > cfg.max_quote_age_seconds:
                    mark = {"price": None, "unrealized_pnl": None, "status": "stale or missing"}
                rows.append(
                    {
                        "contract": p["contract"],
                        "quantity": p["quantity"],
                        "entry_with_fees": p["cost"] / 100 / p["quantity"] / 100,
                        **mark,
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            st.subheader("Selected contracts and order state")
            orders = store.rows("orders")
            st.dataframe(pd.DataFrame([{**o, "spec": json.loads(o["spec"])} for o in orders]), hide_index=True)
            st.subheader("Recorded equity")
            eq = store.rows("equity")
            if eq:
                chart = pd.DataFrame(eq)
                chart["equity"] = chart.apply(lambda r: r.cents / 100 if r.complete else float("nan"), axis=1)
                st.line_chart(chart.set_index("time")[["equity"]])
                st.caption(
                    "Historical simulated marks; gaps mean missing valuations. This is not a live account balance."
                )
            st.subheader("Fill history")
            history = pd.DataFrame(store.rows("fills"))
            st.dataframe(history, hide_index=True)
            st.download_button(
                "Download trade history CSV", history.to_csv(index=False), "simulated-fills.csv", "text/csv"
            )
            st.subheader("Events and errors")
            st.dataframe(pd.DataFrame(store.rows("events")[-50:]), hide_index=True)
            context = store.get("research_context")
            if context:
                with st.expander("Sourced event checks and unverified headlines"):
                    st.json(json.loads(context))
        finally:
            store.close()

    panel()


if __name__ == "__main__":
    main()
