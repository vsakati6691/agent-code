"""Local-only explorer controls. Arithmetic mirrors bets.py; no requests or uploads."""

CSS = r"""
.bets-tools { display:grid;grid-template-columns:1fr 1fr;gap:16px; }
.bets-tools .card { min-width:0;margin:0; }
.bets-tools label,.bets-controls label { display:flex;flex-direction:column;gap:5px;font-size:13px; }
.bets-tools input,.bets-tools select { font:inherit;padding:8px;border:1px solid var(--border);border-radius:6px;
  background:var(--surface-1);color:var(--text-primary);width:100%;min-width:0; }
.bets-tools input[aria-invalid=true] { border-color:var(--bad-border); }
.bets-tools button,.bets-table button { font:inherit;cursor:pointer; }
.bets-tools h2 { margin-top:0; }
.bets-table td { white-space:normal; }
.bets-table td.num { white-space:normal;min-width:90px; }
.bets-table .contract { min-width:150px;overflow-wrap:anywhere; }
.bets-slip { padding-left:20px;overflow-wrap:anywhere; }
.bets-slip li { margin:8px 0; }
.bets-slip button { margin-left:8px; }
@media(max-width:700px) {
 .bets-tools { grid-template-columns:1fr; }
 .bets-table,.bets-table tbody { display:block; }
 .bets-table thead,.bets-table thead tr { display:flex;flex-wrap:wrap; }
 .bets-table th { display:none; }
 .bets-table th[data-sort] { display:block;white-space:normal; }
 .bets-table tr { display:grid;grid-template-columns:1fr 1fr;border-bottom:2px solid var(--border);padding:8px; }
 .bets-table tr[hidden] { display:none; }
 .bets-table td,.bets-table td.num { min-width:0;text-align:left;border:0;padding:6px;overflow-wrap:anywhere; }
 .bets-table td::before { content:attr(data-label);display:block;color:var(--text-muted);font-size:11px;font-weight:400; }
 .bets-table td.contract { grid-column:1/-1;min-width:0; }
}
"""

# Kept separate for cross-runtime tests without a DOM or browser storage.
MATH_JS = r"""
var BetMath = (function () {
  var MAX = 99999999999, QMAX = 9999;
  function budgetCents(value) {
    var text = String(value).trim();
    if (!/^\d{1,9}(?:\.\d{1,2})?$/.test(text)) return null;
    var parts = text.split('.'), result = Number(parts[0]) * 100 + Number(((parts[1] || '') + '00').slice(0,2));
    return result <= MAX ? result : null;
  }
  function premiumCents(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
    var cents = Math.ceil(value * 100 - 1e-7);
    return cents > 0 && cents <= MAX ? cents : null;
  }
  function withinBudget(premium, budget) {
    var cost = premiumCents(premium), limit = budgetCents(budget);
    return cost !== null && limit !== null && cost <= limit;
  }
  function size(premium, budget) {
    var cost = premiumCents(premium), limit = budgetCents(budget);
    if (cost === null || limit === null) return {status:'invalid',contracts:null,max_loss_cents:null};
    var count = Math.floor(limit / cost);
    return {status:'ok',contracts:count,max_loss_cents:count * cost};
  }
  function slipTotal(entries, budget) {
    var total = 0;
    for (var item of entries) {
      if (!Number.isSafeInteger(item.cost_cents) || item.cost_cents <= 0 || item.cost_cents > MAX ||
          !Number.isSafeInteger(item.quantity) || item.quantity < 1 || item.quantity > QMAX) {
        return {status:'invalid',max_loss_cents:null,over_budget:null};
      }
      total += item.cost_cents * item.quantity;
      if (!Number.isSafeInteger(total)) return {status:'invalid',max_loss_cents:null,over_budget:null};
    }
    var limit = budgetCents(budget);
    return {status:'ok',max_loss_cents:total,over_budget:limit === null ? null : total > limit};
  }
  return {budgetCents:budgetCents,premiumCents:premiumCents,withinBudget:withinBudget,size:size,slipTotal:slipTotal};
})();
"""

JS = (
    MATH_JS
    + r"""
(function () {
  var source = document.getElementById('bets-data');
  if (!source) return;
  var data = JSON.parse(source.textContent), table = document.getElementById('bets-table');
  var budget = document.getElementById('bet-budget'), choice = document.getElementById('bet-contract');
  var sizing = document.getElementById('bet-sizing'), quantity = document.getElementById('bet-quantity');
  var slip = document.getElementById('bet-slip'), status = document.getElementById('bet-slip-status');
  var notice = document.getElementById('bet-notice'), entries = [], key = 'betslip-v1';
  var rows = data.rows.map(function (values) {
    var row = {}; data.columns.forEach(function (name, i) { row[name] = values[i]; }); return row;
  });
  rows.sort(function (a,b) { return a.premium - b.premium || a.option.localeCompare(b.option); });
  function node(tag, text, cls) {
    var n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n;
  }
  function money(cents) { return (cents / 100).toLocaleString('en-US',{style:'currency',currency:'USD'}); }
  function dollars(value) { return Number.isFinite(value) ? value.toLocaleString('en-US',{style:'currency',currency:'USD'}) : 'Unavailable'; }
  function pct(value) { return Number.isFinite(value) ? (100 * value).toFixed(1) + '%' : 'Unavailable'; }
  function cell(tr, label, text, value, cls) {
    var td = node('td', text, cls); td.setAttribute('data-label', label);
    if (value !== undefined) td.dataset.v = value;
    tr.appendChild(td); return td;
  }
  var body = table.tBodies[0]; body.textContent = '';
  var frag = document.createDocumentFragment();
  rows.forEach(function (r, index) {
    var tr = document.createElement('tr');
    tr.dataset.tier = r.tier; tr.dataset.type = r.type; tr.dataset.horizon = r.horizon;
    tr.dataset.premium = r.premium;
    var name = r.underlying + ' ' + r.type + ' · ' + r.expiration + ' · strike ' + dollars(r.strike);
    var main = cell(tr,'Contract',r.underlying + ' · ' + r.type + ' · ' + r.tier,undefined,'contract');
    main.appendChild(node('div',r.expiration + ' · ' + r.dte + ' days','small'));
    main.appendChild(node('div','Strike ' + dollars(r.strike) + ' · underlying ' + dollars(r.spot),'small'));
    var use = node('button','Use in calculator','action'); use.type = 'button';
    use.setAttribute('aria-label','Use ' + name + ' in calculator');
    use.addEventListener('click',function () { choice.value = String(index); updateSizing();
      document.getElementById('bet-calculator').open = true; choice.focus(); });
    main.appendChild(use);
    cell(tr,'Premium · ask × 100',dollars(r.premium),r.premium,'num');
    cell(tr,'Maximum loss · before fees',dollars(r.premium),r.premium,'num crit');
    cell(tr,'Breakeven at expiry',dollars(r.breakeven),r.breakeven,'num');
    var ratio = r.implied_move > 0 ? r.required_move / r.implied_move : null;
    cell(tr,'Needed / implied move',pct(r.required_move) + ' needed / ' + pct(r.implied_move) + ' implied' +
      (ratio === null ? '' : ' · ' + ratio.toFixed(2) + 'x'),ratio === null ? '' : ratio,'num');
    cell(tr,'Delta · not a probability',r.delta.toFixed(2),r.delta,'num');
    cell(tr,'Spread / mid',pct(r.spread_pct),r.spread_pct,'num');
    cell(tr,'Open interest',r.open_interest.toLocaleString('en-US'),r.open_interest,'num');
    cell(tr,'Volume',r.volume.toLocaleString('en-US'),r.volume,'num');
    cell(tr,'Earnings before expiry',r.events_status + (r.events_status === 'unknown' ? '' : ' (unverified)'));
    cell(tr,'Chain timestamp',r.quote_time_utc ? r.quote_time_utc.replace('T',' ').replace('+00:00',' UTC') : 'Unknown · last-trade session verified');
    frag.appendChild(tr);
    var option = node('option',name + ' · ' + dollars(r.premium)); option.value = String(index); choice.appendChild(option);
  });
  body.appendChild(frag);
  table.acceptRow = function (item) {
    return budget.value.trim() === '' || BetMath.withinBudget(Number(item.dataset.premium),budget.value);
  };
  table.dispatchEvent(new Event('tabledatachange'));
  function persist() {
    try {
      if (entries.length) localStorage.setItem(key,JSON.stringify(entries)); else localStorage.removeItem(key);
      return true;
    } catch(e) {
      notice.textContent = 'Device storage could not be updated. Changes last only on this page; previously saved entries may return after reloading.';
      return false;
    }
  }
  function renderSlip() {
    slip.textContent = '';
    entries.forEach(function (entry,index) {
      var li = node('li',entry.label + ' · ' + entry.quantity + ' contract(s) · max loss ' + money(entry.cost_cents * entry.quantity) +
        ' · saved quote session ' + entry.as_of);
      var remove = node('button','Remove'); remove.type = 'button'; remove.setAttribute('aria-label','Remove ' + entry.label);
      remove.addEventListener('click',function () { entries.splice(index,1); persist(); renderSlip(); });
      li.appendChild(remove); slip.appendChild(li);
    });
    var total = BetMath.slipTotal(entries,budget.value);
    status.textContent = total.status === 'invalid' ? 'Slip total unavailable: invalid stored amounts. Clear the slip.' :
      'Total maximum loss ' + money(total.max_loss_cents) + '. If every bet expires worthless you lose ' + money(total.max_loss_cents) +
      ', before fees.' + (total.over_budget ? ' Warning: combined slip loss is above your typed per-bet budget.' : '');
    status.className = total.over_budget ? 'banner warn' : 'small';
  }
  function updateSizing() {
    var r = rows[Number(choice.value)], limit = BetMath.budgetCents(budget.value);
    budget.setAttribute('aria-invalid',budget.value !== '' && limit === null ? 'true' : 'false');
    var result = r && choice.value !== '' ? BetMath.size(r.premium,budget.value) : null;
    sizing.textContent = !result || result.status !== 'ok' ? 'Choose a contract and enter a dollar budget with at most two decimal places.' :
      result.contracts + ' whole contract(s) fit this budget at the delayed ask; maximum loss ' + money(result.max_loss_cents) +
      ', before fees. This is arithmetic, not a suggested size.';
  }
  budget.addEventListener('input',function () { table.dispatchEvent(new Event('tablefilterchange')); updateSizing(); renderSlip(); });
  choice.addEventListener('change',updateSizing);
  document.getElementById('bet-save').addEventListener('click',function () {
    var r = rows[Number(choice.value)], qty = Number(quantity.value);
    if (!r || choice.value === '' || !Number.isSafeInteger(qty) || qty < 1 || qty > 9999) {
      notice.textContent = 'Choose a contract and a whole quantity from 1 to 9,999.'; return;
    }
    if (entries.length >= 100) { notice.textContent = 'This device slip holds up to 100 entries. Remove an entry first.'; return; }
    var entry = {label:r.underlying + ' ' + r.type + ' ' + r.expiration + ' strike ' + dollars(r.strike),
      option:r.option,quantity:qty,cost_cents:BetMath.premiumCents(r.premium),as_of:data.as_of};
    if (BetMath.slipTotal(entries.concat([entry]),budget.value).status !== 'ok') {
      notice.textContent = 'Amounts exceed the calculator range.'; return;
    }
    entries.push(entry); var saved = persist(); renderSlip();
    if (saved) notice.textContent = 'Saved on this device only. No order was sent.';
  });
  document.getElementById('bet-clear').addEventListener('click',function () {
    entries = []; var cleared = persist(); renderSlip();
    if (cleared) notice.textContent = 'Local slip cleared.';
  });
  try {
    var stored = JSON.parse(localStorage.getItem(key) || '[]');
    if (!Array.isArray(stored) || stored.length > 100 || !stored.every(function (e) {
      return e && typeof e.label === 'string' && e.label.length <= 200 && typeof e.option === 'string' &&
        e.option.length <= 40 && /^\d{4}-\d{2}-\d{2}$/.test(e.as_of);
    }) || BetMath.slipTotal(stored,'').status !== 'ok') throw new Error('invalid slip');
    entries = stored;
  } catch(e) { notice.textContent = 'Stored slip could not be read. Use Clear to remove it.'; }
  updateSizing(); renderSlip();
})();
"""
)
