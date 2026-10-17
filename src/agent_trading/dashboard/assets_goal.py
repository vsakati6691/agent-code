"""Local-only Plan 2030 arithmetic and form interaction; no network or snapshot writes."""

MATH_JS = r"""
const GoalMath = (() => {
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  function ending(capital, monthly, years, rate) {
    if (![capital,monthly,years,rate].every(finite) || capital<0 || monthly<0 || years<0 || years>100 || rate<=-1) return null;
    let value=capital*Math.pow(1+rate,years), n=Math.floor(years*12+1e-9);
    for(let i=1;i<=n;i++) value+=monthly*Math.pow(1+rate,years-i/12);
    return finite(value)?value:null;
  }
  function required(capital,target,monthly,years) {
    if (![capital,target,monthly,years].every(finite) || capital<=0 || target<=0 || monthly<0 || years<=0 || years>100) return null;
    let lo=-0.999999999999, hi=1, floor=ending(capital,monthly,years,lo);
    if(floor===null || floor>target) return null;
    while(hi<1000000 && (ending(capital,monthly,years,hi)??Infinity)<target) hi*=2;
    let ceiling=ending(capital,monthly,years,hi); if(ceiling!==null && ceiling<target) return null;
    for(let i=0;i<120;i++) {let mid=(lo+hi)/2,v=ending(capital,monthly,years,mid); if(v===null||v>target) hi=mid; else lo=mid;}
    return (lo+hi)/2;
  }
  function weighted(capital,monthly,years,weights,rates) {
    const values={bear:null,base:null,bull:null}, entries=Object.entries(weights);
    if(!entries.length || entries.some(([,w])=>!finite(w)||w<0||w>1)) return {values,reason:'Weights must be between 0 and 100%.'};
    if(Math.abs(entries.reduce((s,[,w])=>s+w,0)-1)>1e-8) return {values,reason:'Weights must total 100%.'};
    const missing=entries.filter(([t,w])=>w>0&&Object.keys(values).some(k=>!finite((rates[t]||{})[k]))).map(([t])=>t);
    if(missing.length) return {values,reason:'Stored scenario unavailable: '+missing.join(', ')};
    for(const key of Object.keys(values)) {
      const ends=entries.filter(([,w])=>w>0).map(([t,w])=>ending(capital*w,monthly*w,years,rates[t][key]));
      values[key]=ends.every(finite)?ends.reduce((s,v)=>s+v,0):null;
    }
    return {values,reason:''};
  }
  function stress(capital,monthly,years,rate,drawdown) {
    if(!finite(drawdown)||drawdown<0||drawdown>1||!finite(years)||years<1) return null;
    let first=ending(capital,monthly,1,0); return first===null?null:ending(first*(1-drawdown),monthly,years-1,rate);
  }
  return {ending,required,weighted,stress};
})();
"""

JS = (
    MATH_JS
    + r"""
(() => {
  const payload=document.getElementById('goal-data'); if(!payload) return;
  const data=JSON.parse(payload.textContent), form=document.getElementById('goal-form'), key='plan2030-v1';
  const fields=Array.from(form.querySelectorAll('input')), defaults=Object.fromEntries(fields.map(e=>[e.id,e.value]));
  const el=id=>document.getElementById(id), number=id=>el(id).value.trim()===''?NaN:Number(el(id).value);
  const pct=v=>Number.isFinite(v)?(v*100).toFixed(2)+'%/yr':'Unavailable';
  const money=v=>Number.isFinite(v)?v.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}):'Unavailable';
  let storage=true;
  try { const saved=JSON.parse(localStorage.getItem(key)||'{}'); fields.forEach(e=>{if(typeof saved[e.id]==='string')e.value=saved[e.id];}); }
  catch(_) {storage=false;}
  function update(save) {
    if(save)try{localStorage.setItem(key,JSON.stringify(Object.fromEntries(fields.map(e=>[e.id,e.value]))));}catch(_){storage=false;}
    el('goal-storage').textContent=storage?'Inputs stay in localStorage on this browser. They are never uploaded or added to research snapshots.':'Browser storage is unavailable. Inputs work for this visit and are never uploaded.';
    const capital=number('goal-capital'), target=number('goal-target'), monthly=number('goal-monthly');
    const date=el('goal-date').value, end=Date.parse(date+'T00:00:00Z'), start=Date.parse(data.start_date+'T00:00:00Z');
    const years=(end-start)/86400000/365.25;
    const valid=['goal-capital','goal-target','goal-monthly','goal-date'].every(id=>el(id).checkValidity())&&capital>0&&target>0&&monthly>=0&&years>0&&years<=100;
    const rate=valid?GoalMath.required(capital,target,monthly,years):null;
    el('goal-required').textContent=pct(rate);
    el('goal-no-contributions').textContent=valid?pct(GoalMath.required(capital,target,0,years)):'Unavailable';
    el('goal-error').textContent=!valid?'Enter positive capital and target, a nonnegative contribution and a target date within 100 years after the plan start.':rate===null?'No finite required rate could be found in the supported range. The target may be below the final contribution.':'';
    el('goal-horizon').textContent=valid?years.toFixed(2)+' years; '+Math.floor(years*12+1e-9)+' end-of-month contributions.':'';
    const weights={}, rates={};
    data.assets.forEach((a,i)=>{
      weights[a.ticker]=number('goal-weight-'+i)/100; rates[a.ticker]=a.rates;
      const r=el('goal-rate-'+i); if(r){r.textContent=pct(rate);r.dataset.v=Number.isFinite(rate)?String(rate):'';}
      const flag=el('goal-meets-'+i); if(flag){flag.textContent=rate===null?'Required rate unavailable':Number.isFinite(a.rates?.base)?(a.rates.base>=rate?'Meets required rate':'Below required rate'):'—';flag.dataset.v=flag.textContent;}
    });
    const portfolio=valid?GoalMath.weighted(capital,monthly,years,weights,rates):{values:{bear:null,base:null,bull:null},reason:'Inputs invalid.'};
    el('goal-portfolio-reason').textContent=portfolio.reason;
    for(const k of ['bear','base','bull']) el('goal-ending-'+k).textContent=money(portfolio.values[k]);
    let total=0, missing=[];
    if(!valid||portfolio.reason)missing.push(portfolio.reason||'Inputs invalid.');
    else if(years<1)missing.push('Stress requires a horizon of at least one year.');
    else data.assets.forEach(a=>{
      const w=weights[a.ticker]; if(w<=0)return;
      const index=data.classes.findIndex(c=>c.name===a.asset_class), dd=number('goal-stress-'+index)/100;
      const value=GoalMath.stress(capital*w,monthly*w,years,a.rates.base,dd);
      if(value===null)missing.push(a.ticker+': drawdown or base scenario unavailable');else total+=value;
    });
    el('goal-stress-ending').textContent=money(missing.length?null:total);
    el('goal-stress-reason').textContent=missing.join('; ');
  }
  form.addEventListener('submit',e=>e.preventDefault());
  form.addEventListener('input',()=>update(true));
  el('goal-reset').addEventListener('click',()=>{fields.forEach(e=>e.value=defaults[e.id]);update(true);});
  update(false);
})();
"""
)
