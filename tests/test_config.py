import re
import subprocess
from dataclasses import replace

import pytest
import yaml

from agent_trading.config import ConfigError, get_api_key, load_settings, validate

from .conftest import ROOT


def test_shipped_config_is_paper_and_safe():
    s = load_settings(ROOT / "config" / "settings.yaml")
    assert s.mode == "paper"
    assert s.risk.risk_per_trade_pct == 0.005
    assert s.risk.max_open_risk_pct == 0.015
    assert not any([s.risk.allow_short, s.risk.allow_margin, s.risk.allow_options, s.risk.allow_crypto])
    assert len(s.symbols) <= 24, "universe must fit the free API budget"


@pytest.mark.parametrize("mode", ["live", "LIVE", ""])
def test_non_paper_mode_rejected(settings, mode):
    with pytest.raises(ConfigError):
        validate(replace(settings, mode=mode))


@pytest.mark.parametrize("flag", ["allow_short", "allow_margin", "allow_options", "allow_crypto"])
def test_prohibited_flags_rejected(settings, flag):
    with pytest.raises(ConfigError):
        validate(replace(settings, risk=replace(settings.risk, **{flag: True})))


def test_excessive_risk_rejected(settings):
    with pytest.raises(ConfigError):
        validate(replace(settings, risk=replace(settings.risk, risk_per_trade_pct=0.05)))
    with pytest.raises(ConfigError):
        validate(replace(settings, risk=replace(settings.risk, max_open_risk_pct=0.002)))


def test_unknown_keys_rejected(tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    raw["risk"]["allow_leverage"] = True
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "s.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="Unknown keys"):
        load_settings(path)


def test_missing_api_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        get_api_key()


def private_config(tmp_path):
    path = tmp_path / "config" / "settings.yaml"
    path.parent.mkdir()
    path.write_bytes((ROOT / "config" / "settings.yaml").read_bytes())
    return path


def test_broker_suffix_loaded_from_local_env_without_logging(tmp_path, monkeypatch, capsys):
    path = private_config(tmp_path)
    monkeypatch.delenv("BROKER_ACCOUNT_LAST4")
    (tmp_path / ".env").write_text("BROKER_ACCOUNT_LAST4=0042\n", encoding="utf-8")
    assert load_settings(path).broker.account_last4 == "0042"
    assert capsys.readouterr() == ("", "")


def test_process_broker_suffix_takes_precedence(tmp_path, monkeypatch):
    path = private_config(tmp_path)
    (tmp_path / ".env").write_text("BROKER_ACCOUNT_LAST4=0042\n", encoding="utf-8")
    monkeypatch.setenv("BROKER_ACCOUNT_LAST4", " 1234 ")
    assert load_settings(path).broker.account_last4 == "1234"


@pytest.mark.parametrize("suffix", ["", "123", "12345", "abcd", "１２３４"])
def test_live_tickets_require_four_ascii_digits(tmp_path, monkeypatch, suffix):
    monkeypatch.setenv("BROKER_ACCOUNT_LAST4", suffix)
    with pytest.raises(ConfigError, match="account_last4"):
        load_settings(private_config(tmp_path))


def test_missing_suffix_is_allowed_only_with_live_disabled(tmp_path, monkeypatch):
    path = private_config(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["live"]["enabled"] = False
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.delenv("BROKER_ACCOUNT_LAST4")
    assert load_settings(path).broker.account_last4 == ""


def test_tracked_config_contains_no_account_suffix():
    paths = subprocess.check_output(["git", "ls-files", "config/"], cwd=ROOT).decode("utf-8").splitlines()
    assert paths
    for name in paths:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r'(?i)account_(?:last4|number)["\x27]?\s*[:=]\s*["\x27]?\d{4}', text), name
