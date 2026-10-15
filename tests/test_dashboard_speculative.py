"""Speculative research arithmetic, strict eligibility and immutable IV history."""
from copy import deepcopy
from datetime import date, timedelta

import pytest

from agent_trading.dashboard import speculative as s
from tests.dashboard_fixtures import AS_OF, option_row


def row(kind="call", days=45, strike=100):
    r = option_row("ABC", AS_OF+timedelta(days=days), strike, 4.9, 5.1, delta=.3)
    if kind == "put":
        r.update(type="put", delta=-.3, option=f"ABC{r['expiration']:%y%m%d}P{int(strike*1000):08d}")
    return r


def chain(rows):
    return ({"symbol":"ABC","close":100,"last_trade_time":f"{AS_OF}T16:00:00","timestamp":f"{AS_OF} 22:00:00"},rows)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("days", [30,90])
@pytest.mark.parametrize("delta", [.25,.4])
def test_contract_inclusive_dte_delta_boundaries(kind,days,delta):
    r=row(kind,days);r["delta"]=delta if kind=="call" else -delta
    assert s.eligible(r,"ABC",AS_OF)==(True,"")


@pytest.mark.parametrize("changes", [
    {"expiration": AS_OF+timedelta(days=29)}, {"expiration": AS_OF+timedelta(days=91)},
    {"delta":.2499}, {"delta":.4001}, {"delta":-.3}, {"open_interest":500}, {"volume":9},
    {"bid":0}, {"ask":4.9}, {"bid":3}, {"iv":0}, {"theta":0}, {"theta":None},
    {"root":"ABC1"}, {"strike":float("inf")}, {"open_interest":None}])
def test_ineligible_and_missing_contracts(changes):
    r=row();r.update(changes)
    assert not s.eligible(r,"ABC",AS_OF)[0]
    assert s.eligible(r,"ABC",AS_OF)[1]


def test_spread_threshold_oi_strict_and_volume_threshold():
    r=row();r.update(bid=9.5,ask=10.5,open_interest=501,volume=10)
    assert s.eligible(r,"ABC",AS_OF)[0]
    r["ask"]=10.5001
    assert not s.eligible(r,"ABC",AS_OF)[0]


def test_atm_pair_uses_same_expiry_strike_and_nearest30day_expiry():
    rows=[row(kind,days,strike) for days in (25,30,40) for strike in (95,100,105) for kind in ("call","put")]
    for r in rows:r["iv"] = .3 if r["type"]=="call" else .5
    result=s.atm_pair(rows,"ABC",101,AS_OF)
    assert result["value"]==.4 and result["strike"]==100
    assert result["expiration"]==str(AS_OF+timedelta(days=30))
    assert s.atm_pair([row("call",30)],"ABC",100,AS_OF)["value"] is None
    assert s.atm_pair([row("call",45),row("put",45)],"ABC",100,AS_OF)["value"] is None
    assert s.atm_pair(rows,"ABC",None,AS_OF)["value"] is None
    for r in rows:
        if r['expiration']==AS_OF+timedelta(days=30) and r['strike']==100 and r['type']=='put': r['iv']=None
    assert s.atm_pair(rows,"ABC",101,AS_OF)['value'] is None  # no different strike/expiry substituted


def test_earnings_move_uses_first_expiry_after_event_and_positive_time():
    rows=[row(k,days) for days in (30,60) for k in ("call","put")]
    event=str(AS_OF+timedelta(days=35))
    result=s.earnings_move(rows,"ABC",100,AS_OF,event)
    assert result["value"]==pytest.approx(.3*(35/365)**.5)
    assert result["dollars"]==pytest.approx(result["value"]*100)
    assert result["iv_expiry"]==str(AS_OF+timedelta(days=60))
    for missing in (None,"invalid",str(AS_OF),str(AS_OF+timedelta(days=100))):
        assert s.earnings_move(rows,"ABC",100,AS_OF,missing)["value"] is None
    assert s.earnings_move([],"ABC",100,AS_OF,event)["value"] is None


def test_put_call_volume_ratio_coverage_dedup_and_zero_denominator():
    c,p=row(),row("put");c["volume"]=100;p["volume"]=250
    assert s.put_call_ratio([c,p,p],"ABC",AS_OF)["value"]==2.5
    assert s.put_call_ratio([p],"ABC",AS_OF)["value"] is None
    p["volume"]=None
    assert s.put_call_ratio([c,p],"ABC",AS_OF)["value"] is None


def test_iv_rank_needs252_comparable_unique_sessions_and_range():
    days = [AS_OF-timedelta(days=i) for i in range(1,367) if s.is_trading_day(AS_OF-timedelta(days=i))][:251]
    obs=[{"as_of":str(day),"iv":.2+i/1000,"method":s.IV_METHOD} for i, day in enumerate(days, 1)]
    assert s.iv_rank(.3,obs,AS_OF)["value"]==pytest.approx(100*(.3-.201)/(.451-.201))
    assert s.iv_rank(.3,obs[:-1],AS_OF)["value"] is None
    assert s.iv_rank(.3,obs[:-1]+[obs[0]],AS_OF)["value"] is None
    assert s.iv_rank(None,obs,AS_OF)["value"] is None
    assert s.iv_rank(.3,[{**x,"iv":.3} for x in obs],AS_OF)["value"] is None
    assert s.iv_rank(.3,[{**x,"method":"incompatible"} for x in obs],AS_OF)["value"] is None
    assert s.iv_rank(.3,[{"as_of":str(AS_OF+timedelta(days=i)),"iv":.2,"method":s.IV_METHOD} for i in range(1,253)],AS_OF)["value"] is None


def test_contract_math_calls_puts_exits_and_maximum_three_deterministic():
    rows=[row(kind,45,strike) for strike in (95,100,105,110) for kind in ("call","put")]
    out=s.build({"ABC":chain(rows)},AS_OF,{})["tickers"]["ABC"]
    reverse=s.build({"ABC":chain(list(reversed(rows)))},AS_OF,{})["tickers"]["ABC"]
    assert out["contracts"]==reverse["contracts"] and len(out["contracts"])==3
    for r in out["contracts"]:
        assert r["premium"]==r["max_loss"]==pytest.approx(510)
        assert r["breakeven"]==pytest.approx(r["strike"]+(5.1 if r["type"]=="call" else -5.1))
        needed=max(0,r["breakeven"]/100-1) if r["type"]=="call" else max(0,1-r["breakeven"]/100)
        assert r["required_move"]==pytest.approx(needed)
        assert r["exits"]=={"profit_premium":10.2,"loss_premium":2.55,"close_date":str(AS_OF+timedelta(days=24))}
    assert s.exits(None,AS_OF)["profit_premium"] is None
    assert s.exits(5,None)["close_date"] is None


def test_no_eligible_contracts_or_stale_chain_never_padded():
    c=chain([row()]);c[0]["last_trade_time"]="2020-01-01T16:00:00"
    for value in (c,"provider unavailable",chain([])):
        result=s.build({"ABC":value},AS_OF,{})["tickers"]["ABC"]
        assert not result["contracts"] and result["reason"]


@pytest.mark.parametrize("size,premium,cap,trade,valid,overall,per_trade", [
    (10000,100,5,1,True,False,False),(10000,100.01,5,1,True,False,True),
    (10000,501,5,1,True,True,True),(10000,1,0,0,True,True,True),
    (10000,100,1,5,True,False,False),(0,100,5,1,False,None,None),
    (None,100,5,1,False,None,None),(10000,100,-1,1,False,None,None),
    (10000,100,5,101,False,None,None),(float("nan"),100,5,1,False,None,None)])
def test_budget_caps_and_invalid_inputs(size,premium,cap,trade,valid,overall,per_trade):
    result=s.budget(size,premium,cap,trade)
    assert result["valid"]==valid
    if valid:
        assert result["exceeds_options"]==overall and result["exceeds_trade"]==per_trade
        assert result["options_budget"]==size*cap/100
        assert result["trade_budget"]==size*trade/100
        assert result["inconsistent_caps"]==(trade>cap)


def test_top_ranked_targets_bounded_and_deduplicated():
    snap={"bands":{k:{"candidates":[{"ticker":str(i)} for i in range(5)]} for k in ("large","mid","small","ai_large")}}
    assert s.targets(snap)==['0','1','2']


def test_options_flag_and_missing_payload_are_visible(monkeypatch):
    from agent_trading.dashboard.site_speculative import section
    assert 'Disabled by DASHBOARD_OPTIONS' in section({"options":{"enabled":False}})
    assert 'n/a' in section({"options":{"enabled":True}})
    focus=s.build({"ABC":chain([row()])},AS_OF,{})
    page=section({"options":{"enabled":True},"speculative":focus})
    assert '100% loss' in page and 'delayed, not live' in page and '510.00' in page
    assert 'id="spec-size"' in page and 'Illustrative exit rules' in page
    assert 'Disabled by DASHBOARD_OPTIONS' in section({"options":{"enabled":True},"speculative":focus},{"data":{"options":{"enabled":False}}})
    monkeypatch.setenv('DASHBOARD_OPTIONS','false')
    assert 'Disabled by DASHBOARD_OPTIONS' in section({"options":{"enabled":True},"speculative":focus})


def test_daily_extra_growth_chains_do_not_change_existing_explorer(tmp_path):
    from tests.test_dashboard_refresh import RefreshProviders, weekly, NOW
    from agent_trading.dashboard.refresh import collect
    from agent_trading.dashboard import bets
    p=RefreshProviders(); snap=weekly(tmp_path)
    p.add('MID',99,sp=False)
    midrow=option_row('MID',AS_OF+timedelta(days=40),100,4.9,5.1,delta=.3)
    p.chains['MID']=({**chain([])[0],"symbol":"MID"},[midrow])
    snap['bands']['mid']={"candidates":[{"ticker":"MID"}]}
    out=collect(p,snap,AS_OF,True,NOW.isoformat())
    assert 'MID' in out['speculative']['tickers']
    assert out['speculative']['tickers']['MID']['contracts']
    assert out['options']['underlyings']==['AAA']
    assert out['explorer']==bets.build({k:v for k,v in p.chains.items() if k!='MID'},AS_OF,{})
    assert p.calls.count('earnings')==1
    disabled=collect(p,snap,AS_OF,False,NOW.isoformat())
    assert disabled['speculative'] is None


def test_stored_iv_history_verifies_integrity_and_never_reads_future():
    class History:
        def __init__(self): self.read=[]
        def dates(self): return [str(AS_OF-timedelta(days=1)),str(AS_OF),str(AS_OF+timedelta(days=1))]
        def load(self,day):
            self.read.append(day)
            return {"speculative":{"iv_method":s.IV_METHOD,"tickers":{"ABC":{"iv":{"value":.3}}}}}
    store=History()
    result=s.stored_history(store,AS_OF)
    assert result['ABC'][0]['iv']==.3 and store.read==[str(AS_OF-timedelta(days=1))]
    def invalid(day): raise ValueError('integrity check failed')
    store.load=invalid
    with pytest.raises(ValueError,match='integrity'): s.stored_history(store,AS_OF)


def test_browser_budget_warnings_at_cent_boundaries_and_no_storage(tmp_path):
    import json, shutil, subprocess
    from agent_trading.dashboard.assets_speculative import JS
    node=shutil.which('node')
    if not node: pytest.skip('Node unavailable')
    assert all(token not in JS for token in ('localStorage','sessionStorage','fetch(', 'XMLHttpRequest'))
    harness = r'''
const nodes={};const listeners={};
function node(value=''){return {value,textContent:'',hidden:false,classList:{toggle(){}},addEventListener(k,f){this[k]=f;}};}
['spec-size','spec-cap','spec-trade','spec-budget-summary','spec-pin-filter','spec-empty'].forEach(k=>nodes[k]=node());
nodes['spec-cap'].value='5';nodes['spec-trade'].value='1';nodes['spec-pin-filter'].value='all';
const verdict=node();const card={dataset:{specPremium:'100.01'},querySelector(){return verdict;}};
const document={getElementById(k){return nodes[k];},querySelectorAll(s){return s==='[data-spec-premium]'?[card]:[];},addEventListener(){}};
'''
    script=tmp_path/'budget.js'
    script.write_text(harness+JS+'''\nnodes['spec-size'].value='10000';nodes['spec-size'].input();const over=verdict.textContent;
card.dataset.specPremium='100';nodes['spec-size'].input();const equal=verdict.textContent;
nodes['spec-trade'].value='';nodes['spec-trade'].input();console.log(JSON.stringify([over,equal,verdict.textContent]));''',encoding='utf-8')
    over,equal,missing=json.loads(subprocess.check_output([node,str(script)]))
    assert 'CAP EXCEEDED' in over and 'within the entered caps' in equal and 'n/a' in missing
