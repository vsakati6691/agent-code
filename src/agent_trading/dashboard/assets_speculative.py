"""Local hypothetical arithmetic. Nothing persisted, transmitted or connected to execution."""

CSS = r"""
.speculative-section { margin:24px 0 40px; }
.risk-budget { margin:20px 0; border-left:4px solid var(--warn-border); }
.budget-inputs { display:grid;grid-template-columns:2fr 1fr 1fr;gap:12px; }
.budget-inputs input { width:100%;min-width:0; }
.speculative-ticker { margin:18px 0; }
.volatility-grid { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:15px 0; }
.volatility-grid>div { padding:12px;background:var(--surface-2);border-radius:8px; }
.volatility-grid span,.volatility-grid strong,.volatility-grid small { display:block; }
.volatility-grid strong { font-size:22px;margin:7px 0; }
.volatility-grid span,.volatility-grid small { color:var(--text-secondary);font-size:12px; }
.contract-grid { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px; }
.small-contract { padding:16px;border:1px solid var(--border);border-radius:10px;min-width:0; }
.small-contract h4 { margin:0;font-size:18px; } .small-contract p{overflow-wrap:anywhere;}
.contract-metrics { display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0 10px;font-size:13px; }
.contract-metrics dt,.contract-metrics dd { padding:7px 0;border-bottom:1px solid var(--border); }
.contract-metrics dd { margin:0;font-weight:600;text-align:right; }
.budget-verdict { padding:10px;border-radius:5px;background:var(--surface-2);font-size:13px; }
.budget-verdict.exceeded,#spec-budget-summary.exceeded { background:var(--bad-bg);color:var(--text-primary);border:2px solid var(--bad-border);padding:10px;font-weight:700; }
@media(max-width:1000px){.contract-grid{grid-template-columns:1fr;} .volatility-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:600px){.budget-inputs{grid-template-columns:1fr;} .volatility-grid{grid-template-columns:1fr 1fr;gap:7px;} .volatility-grid strong{font-size:18px;} .small-contract{padding:12px;}}
"""

JS = r"""
(function(){
  var size=document.getElementById('spec-size');if(!size)return;
  var cap=document.getElementById('spec-cap'), trade=document.getElementById('spec-trade'), summary=document.getElementById('spec-budget-summary');
  var cards=Array.from(document.querySelectorAll('[data-spec-premium]'));
  var money=function(x){return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x/100);};
  function update(){
    var account=Number(size.value), overall=Number(cap.value), one=Number(trade.value);
    var valid=size.value!==''&&cap.value!==''&&trade.value!==''&&Number.isFinite(account)&&account>0&&account<1e12&&Number.isFinite(overall)&&Number.isFinite(one)&&overall>=0&&overall<=100&&one>=0&&one<=100;
    var cents=Math.round((account+Number.EPSILON)*100), budget=Math.floor(cents*overall/100+1e-8), single=Math.floor(cents*one/100+1e-8);
    summary.classList.toggle('exceeded',valid&&one>overall);
    summary.textContent=valid?'Options cap: '+money(budget)+' · Per-trade cap: '+money(single)+'. '+(one>overall?'WARNING: per-trade cap exceeds the options cap. ':'')+'Existing option exposure is unknown.':'Enter a positive hypothetical account value below $1 trillion and both cap percentages from 0 to 100.';
    cards.forEach(function(card){
      var cost=Math.round((Number(card.dataset.specPremium)+Number.EPSILON)*100), verdict=card.querySelector('[data-budget-verdict]');
      var tooLarge=valid&&(cost>single||cost>budget);verdict.classList.toggle('exceeded',tooLarge);
      verdict.textContent=!valid?'Budget check: n/a · enter valid hypothetical inputs.':tooLarge?'CAP EXCEEDED — one contract costs '+money(cost)+'. '+(cost>single?'Above the per-trade cap. ':'')+(cost>budget?'Above the total options cap.':''):'One contract is within the entered caps; this does not account for existing exposure or establish suitability.';
    });
  }
  [size,cap,trade].forEach(function(el){el.addEventListener('input',update);});update();
  var view=document.getElementById('spec-pin-filter');
  function pins(){var shown=0;document.querySelectorAll('.speculative-ticker').forEach(function(card){card.hidden=view.value==='pinned'&&card.dataset.pinned!=='yes';if(!card.hidden)shown++;});document.getElementById('spec-empty').hidden=shown>0||view.value!=='pinned';}
  view.addEventListener('change',pins);document.addEventListener('pinschange',pins);pins();
})();
"""
