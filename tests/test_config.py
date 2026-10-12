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
