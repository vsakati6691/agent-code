"""Responsive research-field selector and local pin concentration display."""

CSS = r"""
.decision-research { margin: 30px 0; }
.decision-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
.research-metric { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px; padding:10px 0; border-top:1px solid var(--border); }
.research-metric dt { color:var(--text-secondary); font-size:13px; }
.research-metric dd { margin:0; font-variant-numeric:tabular-nums; text-align:right; font-weight:600; }
.research-metric small { display:block; font-size:11px; font-weight:400; overflow-wrap:anywhere; }
.decision-controls { display:flex; flex-wrap:wrap; gap:10px; margin:16px 0 4px; padding:16px; background:var(--surface-2); border-radius:10px; }
.decision-controls label { flex:1 1 115px; min-width:0; }
.decision-controls label:first-child { flex:2 1 220px; }
.decision-controls input,.decision-controls select { width:100%; min-width:0; }
.pin-sectors { margin:14px 0; } .sector-segment { display:inline-flex; padding:7px 10px; margin:3px; border-left:5px solid var(--series-1); background:var(--surface-2); border-radius:4px; font-size:12px; }
.sector-track { display:flex; height:12px; overflow:hidden; border-radius:8px; background:var(--surface-2); }
.sector-track span { background:var(--series-1); border-right:2px solid var(--surface-1); }
.research-value { min-width:175px; max-width:340px; white-space:normal; }
.research-value small { display:block; font-size:11px; color:var(--text-muted); }
.business-evidence { margin-top:15px; } .business-evidence p { max-width:90ch; }
@media(max-width:1000px){.decision-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:650px){.decision-grid{grid-template-columns:1fr;} .decision-controls{padding:10px;}
 #t-scan.decision-scan thead{display:none;} #t-scan.decision-scan tbody{display:grid;grid-template-columns:1fr;gap:12px;}
 #t-scan.decision-scan tr{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--border);border-radius:10px;padding:10px;background:var(--surface-1);}
 #t-scan.decision-scan tr[hidden]{display:none;} #t-scan.decision-scan td{display:block;min-width:0;border:0;padding:8px;text-align:left;white-space:normal;}
 #t-scan.decision-scan td:first-child,#t-scan.decision-scan .research-value,#t-scan.decision-scan .scan-risk{grid-column:1/-1;max-width:none;}
 #t-scan.decision-scan td:before{content:attr(data-label);display:block;font-size:11px;color:var(--text-muted);}
}
"""

JS = r"""
(async function(){
  var table=document.getElementById('t-scan'), raw=document.getElementById('decision-data');
  if(!table || !raw) return;
  var payload;
  try {
    if(raw.dataset.src){
      var response=await fetch(raw.dataset.src,{credentials:'same-origin'});
      if(!response.ok)throw new Error('Unavailable');
      payload=await response.json();
    }else payload=JSON.parse(raw.textContent);
  }catch(error){
    document.getElementById('research-units').textContent='Research fields could not be loaded. Reload to retry, or open a company page for its stored evidence.';
    document.querySelectorAll('.decision-controls input,.decision-controls select').forEach(function(el){el.disabled=true;});
    return;
  }
  var data=payload.rows, field=document.getElementById('research-field');
  var min=document.getElementById('research-min'), max=document.getElementById('research-max');
  var text=document.getElementById('research-text'), coverage=document.getElementById('research-coverage');
  var rows=Array.from(table.tBodies[0].rows), heading=table.querySelector('[data-research-heading]');
  function value(row){var x=(data[row.dataset.list+':'+row.dataset.ticker]||{})[field.value]||[];
    return {v:x[0],text:x[1],reason:x[2],note:x[3],as_of:x[4],kind:(payload.columns[field.value]||[])[1]};}
  function redraw(){
    var label=field.selectedOptions[0].textContent, kind='number';
    rows.forEach(function(row){
      var x=value(row), cell=row.querySelector('[data-research-value]'); kind=x.kind||kind;
      var missing=x.v===null||x.v===undefined;
      cell.dataset.v=missing?'':x.v; cell.dataset.label=label; cell.textContent=missing?'—':x.text;
      cell.title=[x.reason,x.note,'Data as of '+(x.as_of||'not stored')].filter(Boolean).join(' · ');
    });
    heading.dataset.sort=kind==='text'?'text':'num';
    (heading.querySelector('button')||heading).textContent=label;
    min.disabled=max.disabled=kind==='text';
    document.getElementById('research-units').textContent='Selected: '+label+'. '+(['pct','pp'].includes(kind)?'Range inputs use percentage points (20 means 20%). ':'')+'Dates and missing-data reasons are in cell tooltips. Valuation percentile: higher numeric value, not necessarily better.';
    table.dispatchEvent(new Event('tabledatachange'));
  }
  table.acceptRow=function(row){
    var x=value(row), missing=x.v===null||x.v===undefined;
    if(coverage.value==='available'&&missing||coverage.value==='missing'&&!missing)return false;
    if(text.value && ((x.text||'')+' '+(x.reason||'')).toLowerCase().indexOf(text.value.toLowerCase())<0)return false;
    if(!min.disabled && (min.value!==''||max.value!=='')){
      if(missing || typeof x.v!=='number')return false;
      var v=x.v*(['pct','pp'].includes(x.kind)?100:1);
      if(min.value!==''&&v<Number(min.value)||max.value!==''&&v>Number(max.value))return false;
    }return true;
  };
  field.addEventListener('change',function(){min.value=max.value=text.value=coverage.value='';redraw();});
  [min,max,text,coverage].forEach(function(el){el.addEventListener('input',function(){table.dispatchEvent(new Event('tablefilterchange'));});});
  document.querySelector('[data-reset="t-scan"]').addEventListener('click',function(){min.value=max.value=text.value=coverage.value='';redraw();});
  function sectors(){
    var seen=new Set(), counts={};
    rows.forEach(function(r){if(r.dataset.pinned==='yes'&&!seen.has(r.dataset.ticker)){seen.add(r.dataset.ticker);var s=r.dataset.sector||'Unknown';counts[s]=(counts[s]||0)+1;}});
    var box=document.getElementById('pin-sector-bar');box.textContent='';
    if(!seen.size){box.textContent='Pin a ticker to see sectors.';return;}
    var track=document.createElement('div');track.className='sector-track';track.setAttribute('aria-hidden','true');box.appendChild(track);
    Object.entries(counts).sort(function(a,b){return b[1]-a[1]||a[0].localeCompare(b[0]);}).forEach(function(pair,i){
      var part=document.createElement('span');part.style.width=(100*pair[1]/seen.size)+'%';part.style.opacity=String(1-i%4*.15);track.appendChild(part);
      var label=document.createElement('span');label.className='sector-segment';label.textContent=pair[0]+' '+pair[1]+'/'+seen.size+' · '+(100*pair[1]/seen.size).toFixed(0)+'%';box.appendChild(label);
    });
  }
  document.addEventListener('pinschange',sectors);redraw();sectors();
})();
"""
