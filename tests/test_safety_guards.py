"""Static guards: the code base must not be able to reach a live broker."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agent_trading"

FORBIDDEN = [
    r"place_(equity|option|crypto|advanced)_order",
    r"cancel_(equity|option|crypto|advanced)_order",
    r"review_(equity|option|advanced)_order",
    r"exercise_option",
    r"robin_stocks",
    r"api\.robinhood\.com",
    r"mcp__",  # MCP tools are only for read-only use inside a Claude session
]


def test_no_broker_order_paths_in_source():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(SRC)}: {pattern}")
    assert not offenders, f"broker access found: {offenders}"


def test_no_network_calls_except_market_data():
    allowed = {"data/alphavantage.py"}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\brequests\.(get|post|put|delete|Session)\b|urllib\.request|http\.client", text):
            assert rel in allowed, f"unexpected network access in {rel}"


def test_no_secrets_in_source():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"ALPHAVANTAGE_API_KEY\s*=\s*['\"][A-Z0-9]{8,}", text)
        assert not re.search(r"\b\d{9}\b", text), f"possible account number in {path.name}"
