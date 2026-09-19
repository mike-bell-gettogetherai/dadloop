"""Build the baseline-vs-Jev report page: per model, per rung, per scenario, plus the stress block.

usage: python build_ab_report.py <out.html> key=path [key=path ...]
keys:  haiku_base haiku_jev haiku_jev2 sonnet_base sonnet_jev sonnet_jev2
       stress_haiku_base stress_haiku_jev stress_haiku_jev2 stress_sonnet_base stress_sonnet_jev stress_sonnet_jev2
Missing keys are tolerated; sections render with what exists.
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/Users/mikemaddiemacmini/Code/dadloop")
from bench.prompts import LADDER, STRESS  # noqa: E402

out_path = sys.argv[1]
files = dict(kv.split("=", 1) for kv in sys.argv[2:])


def rows(p):
    if not p:
        return []
    p = Path(p)
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def st(rs, k):
    v = [r.get(k) for r in rs if r.get(k) is not None]
    return {"mean": statistics.fmean(v), "p50": statistics.median(v)} if v else {"mean": None, "p50": None}


def majority(rs):
    n = len(rs)
    c = Counter(s for r in rs for s in r.get("loaded_skills", []))
    return sorted(s for s, k in c.items() if k * 2 > n)


def effective(rs):
    """Skills in play for the turn: pre-selected plus loaded, majority over repeats."""
    n = len(rs)
    c = Counter(s for r in rs for s in set(r.get("preselected", []) + r.get("loaded_skills", [])))
    return sorted(s for s, k in c.items() if k * 2 > n)


def jaccard(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


JEV_USD_PER_MTOK_IN = 0.042   # TypeSafe list price 2026-09: input only, output free


def agg(rs):
    if not rs:
        return None
    rs = [{**r, "preselect_cost": (r.get("preselect_tokens_in") or 0) / 1e6 * JEV_USD_PER_MTOK_IN,
           "total_cost": (r.get("cost") or 0.0) + (r.get("preselect_tokens_in") or 0) / 1e6 * JEV_USD_PER_MTOK_IN}
          for r in rs]
    return {
        "preselect_cost": st(rs, "preselect_cost"), "total_cost": st(rs, "total_cost"),
        "n": len(rs),
        "llm_calls": st(rs, "llm_calls"), "llm_ms": st(rs, "llm_ms"), "total_ms": st(rs, "total_ms"),
        "tokens_in": st(rs, "tokens_in"), "tokens_out": st(rs, "tokens_out"), "cost": st(rs, "cost"),
        "preselect_ms": st(rs, "preselect_ms"), "preselect_tokens": st(rs, "preselect_tokens_in"),
        "wall_ms": {"mean": statistics.fmean([(r.get("llm_ms") or 0) + (r.get("preselect_ms") or 0) for r in rs])},
        "load_rate": sum(1 for r in rs if r.get("loaded_skills")) / len(rs),
        "skills_per_turn": sum(len(r.get("loaded_skills", [])) for r in rs) / len(rs),
        "leak_calls": sum(r.get("load_skill_calls", 0) for r in rs) / len(rs),
        "preselected_per_turn": sum(len(r.get("preselected", [])) for r in rs) / len(rs),
        "unpriced": sum(r.get("unpriced_calls") or 0 for r in rs),
        "ceiling_rate": sum(1 for r in rs if r.get("hit_ceiling")) / len(rs),
        "max_calls": max((r.get("llm_calls") or 0) for r in rs),
        "outcomes": dict(sorted(Counter(r.get("outcome") for r in rs).items())),
        "majority": majority(rs),
        "effective": effective(rs),
        "skills_seen": sorted({s for r in rs for s in r.get("loaded_skills", [])}),
        "preselected_seen": sorted({s for r in rs for s in r.get("preselected", [])}),
    }


MODELS = {"haiku": "Haiku 4.5", "sonnet": "Sonnet 5"}
ARMS = {"base": "Baseline", "jev": "Jev v1 (descriptions)", "jev2": "Jev v2 (triggers + composition)"}


def block(prefix, cases):
    data = {"cases": [{"id": c["id"], "tier": c.get("tier"), "prompt": c["prompt"], "expected": c["expected_skills"]} for c in cases],
            "per_case": {}, "per_tier": {}, "overall": {}, "model_ids": {}}
    for m in MODELS:
        for a in ARMS:
            key = f"{prefix}{m}_{a}"
            rs = rows(files.get(key, ""))
            if not rs:
                continue
            by_case, by_tier = defaultdict(list), defaultdict(list)
            for r in rs:
                by_case[r["case_id"]].append(r)
                by_tier[str(r.get("tier"))].append(r)
            data["per_case"][f"{m}_{a}"] = {cid: agg(v) for cid, v in by_case.items()}
            data["per_tier"][f"{m}_{a}"] = {t: agg(v) for t, v in sorted(by_tier.items())}
            data["overall"][f"{m}_{a}"] = agg(rs)
            data["model_ids"][f"{m}_{a}"] = sorted({x for r in rs for x in r.get("models", [])} |
                                                   {r.get("preselect_model") for r in rs if r.get("preselect_model")})
    # agreement per case: jev's effective set vs baseline's majority set, per model
    data["agreement"] = {}
    for m in MODELS:
        b = data["per_case"].get(f"{m}_base")
        if not b:
            continue
        for a in ("jev", "jev2"):
            j = data["per_case"].get(f"{m}_{a}")
            if not j:
                continue
            data["agreement"][f"{m}_{a}"] = {cid: {"base": b[cid]["majority"], "jev_pre": j[cid]["preselected_seen"],
                                                   "jev_effective": j[cid]["effective"],
                                                   "jaccard": jaccard(b[cid]["majority"], j[cid]["effective"]),
                                                   "leak": j[cid]["leak_calls"]}
                                             for cid in b if cid in j}
    # reference truth: Sonnet baseline's majority set (Sonnet loads skills reliably; Haiku does not)
    ref = data["per_case"].get("sonnet_base")
    data["ref_agreement"] = {}
    if ref:
        for key, pc in data["per_case"].items():
            data["ref_agreement"][key] = {cid: jaccard(ref[cid]["majority"], pc[cid]["effective"])
                                          for cid in ref if cid in pc}
    return data


payload = {"models": MODELS, "arms": ARMS, "max_steps": 8,
           "ladder": block("", LADDER), "stress": block("stress_", STRESS)}

html = r"""<title>Dadloop Jev A/B</title>
<style>
:root{color-scheme:light;
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
  --base:#2a78d6;--jev:#eb6834;--jev2:#1baf7a;--good:#006300;--tip-bg:#0b0b0b;--tip-ink:#fcfcfb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
  --base:#3987e5;--jev:#d95926;--jev2:#199e70;--good:#0ca30c;--tip-bg:#fcfcfb;--tip-ink:#0b0b0b}}
:root[data-theme="dark"]{color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
  --base:#3987e5;--jev:#d95926;--jev2:#199e70;--good:#0ca30c;--tip-bg:#fcfcfb;--tip-ink:#0b0b0b}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:40px 28px 64px}
h1{font-size:28px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance}
.sub{color:var(--ink-2);max-width:70ch;margin:0 0 24px}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
section{margin:0 0 40px}
h2{font-size:17px;font-weight:600;margin:0 0 4px}
h3{font-size:14px;font-weight:600;margin:0 0 2px}
.note{color:var(--ink-2);margin:0 0 14px;max-width:74ch}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:18px 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:0 0 16px}
.kpi{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:14px 16px}
.kpi .l{color:var(--muted);font-size:12px}
.kpi .v{font-size:26px;font-weight:600;margin:2px 0 0}
.kpi .d{font-size:12px;color:var(--ink-2)}
.kpi .d.up{color:var(--good)}
.legend{display:flex;gap:18px;align-items:center;margin:0 0 6px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:7px}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:16px}
.panel .unit{color:var(--muted);font-size:12px;margin:0 0 6px}
svg{display:block;width:100%;height:auto;overflow:visible}
.gl{stroke:var(--grid);stroke-width:1}.ax{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.xl{fill:var(--ink-2);font-size:11px}
.band{fill:var(--muted);font-size:10px;letter-spacing:.06em;text-transform:uppercase}
.bar{transition:opacity .12s}.bar.base{fill:var(--base)}.bar.jev{fill:var(--jev)}.bar.jev2{fill:var(--jev2)}
.bar:hover,.bar:focus{opacity:.78;outline:none}.hit{fill:transparent}
.tip{position:fixed;pointer-events:none;background:var(--tip-bg);color:var(--tip-ink);padding:8px 10px;border-radius:6px;font-size:12px;line-height:1.35;display:none;z-index:9;max-width:300px}
.tip b{font-size:14px}.tip .k{display:inline-block;width:10px;height:2px;vertical-align:middle;margin-right:6px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--muted);font-weight:500;font-size:12px}
th:first-child,td:first-child{text-align:left}
td.l{text-align:left;color:var(--ink-2);white-space:normal}
tr.sep td{border-top:2px solid var(--axis)}
.tbl{overflow-x:auto}
details{margin-top:10px}summary{cursor:pointer;color:var(--ink-2)}
.finding{border-left:2px solid var(--axis);padding:2px 0 2px 14px;margin:10px 0}
.finding b{font-weight:600}
.model-h{display:flex;align-items:baseline;gap:10px;margin:18px 0 8px}
.model-h h3{font-size:15px}
@media (prefers-reduced-motion:reduce){.bar{transition:none}}
</style>
<main>
<p class="eyebrow">dadloop &middot; benchmark &middot; baseline vs jev pre-selection</p>
<h1>Dadloop Jev A/B</h1>
<p class="sub">Same ten-prompt ladder and two stress prompts, five runs each, on Haiku 4.5 and Sonnet 5. The Jev arms ask TypeSafe's Jev fifteen yes/no questions in one call before the first Claude call and pre-load the skill bodies that clear 0.5. Jev v1 judged the one-line descriptions written for Claude. Jev v2 judges selector-facing triggers with absence-phrased negatives, then expands composition in code from the skill bodies. Everything else is identical: fresh memory per case, frozen world, nested web search off, <code>load_skill</code> still available. Every number is read back from the harness journal.</p>

<section id="kpi-section"><h2>Headline, per model</h2>
<p class="note">Each Jev arm versus baseline, means over 50 ladder turns; the headline value is the newest arm that ran, with both deltas beneath it. "Wall" is model time plus the selector's own latency, because a pre-selector that saves a Claude call but costs as long is not a win. Jev is priced at TypeSafe's list rate, $0.042 per million input tokens with output free, so the selector adds about four thousandths of a cent per turn.</p>
<div id="kpis"></div></section>

<section><h2>Per rung</h2>
<p class="note">Four rows per tier. "Skills in play" for the Jev arm counts pre-loaded plus later-loaded bodies; "leak" is how many load_skill calls Dad still made after pre-selection.</p>
<div class="card tbl" id="rung"></div></section>

<section><h2>Per scenario, side by side</h2>
<p class="note">One panel per model per metric. Bars are means over five runs; hover for the median. Model time for the Jev arm excludes the selector call, which is shown as its own panel.</p>
<div class="legend"><span><i class="sw" style="background:var(--base)"></i>Baseline</span><span><i class="sw" style="background:var(--jev)"></i>Jev v1 (descriptions)</span><span><i class="sw" style="background:var(--jev2)"></i>Jev v2 (triggers + composition)</span></div>
<div id="charts"></div>
<details><summary>Table view of every scenario and arm</summary><div class="card tbl" id="scen"></div></details></section>

<section><h2>Did Jev pick the right skills?</h2>
<p class="note">Each model's own baseline majority set is one ground truth; Sonnet's baseline is the stricter reference, because Sonnet loads skills reliably and Haiku does not. Jev's effective set is what it pre-loaded plus what Dad still loaded. Jaccard 1.00 means the same set; 0 means no overlap. Leak counts the load_skill calls Dad made anyway.</p>
<div class="card tbl" id="agree"></div></section>

<section id="stress-section" hidden><h2>Stress block, reported on its own</h2>
<p class="note">Two prompts no real Saturday would produce. They exist to find the loop's hard ceiling of eight model calls per turn. Not folded into the ladder means.</p>
<div class="card tbl" id="stress"></div></section>

<section><h2>What it says</h2><div id="findings"></div></section>
</main>
<div class="tip" id="tip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const MODELS=['haiku','sonnet'], ARMS=['base','jev','jev2'];
const tip=document.getElementById('tip');
const fmt={calls:v=>v.toFixed(1), s:v=>(v/1000).toFixed(1)+' s', ms:v=>Math.round(v).toLocaleString()+' ms', cost:v=>'$'+v.toFixed(4), pct:v=>Math.round(v*100)+'%', k:v=>v.toFixed(1)};
function el(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e;}
function h(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
function swatch(arm){const i=h('i','sw'); i.style.background='var(--'+arm+')'; i.style.marginRight='7px'; return i;}
function armCell(arm,label){const m=h('td'); m.appendChild(swatch(arm)); m.appendChild(document.createTextNode(label||D.arms[arm])); m.style.textAlign='left'; return m;}
const L=D.ladder;

// ---- KPIs -------------------------------------------------------------------
(function(){
  const wrap=document.getElementById('kpis');
  const delta=(bv,v,f,lowerBetter)=>{ const d=v-bv; const good=lowerBetter?d<0:d>0; const txt=(f===fmt.pct?((d>0?'+':'')+Math.round(d*100)+' pts'):((d<0?'\u2212':'+')+f(Math.abs(d)))); return {txt,good}; };
  MODELS.forEach(m=>{ const b=L.overall[m+'_base'], j1=L.overall[m+'_jev'], j2=L.overall[m+'_jev2']; if(!b) return;
    const newest=j2||j1; const newestName=j2?'Jev v2':'Jev v1';
    const head=h('div','model-h'); head.appendChild(h('h3',null,D.models[m])); head.appendChild(h('span','note',newest?'baseline '+b.n+' turns; '+newestName+' shown, deltas for each arm below':'baseline only')); wrap.appendChild(head);
    const row=h('div','kpis');
    const items=[['Round trips','llm_calls',v=>v.mean,fmt.calls,true],
                 ['Model time','llm_ms',v=>v.mean,fmt.s,true],
                 ['Wall incl. selector','wall_ms',v=>v.mean,fmt.s,true],
                 ['Claude cost / turn','cost',v=>v.mean,fmt.cost,true],
                 ['Total cost incl. Jev','total_cost',v=>v.mean,fmt.cost,true],
                 ['Turns calling load_skill','load_rate',v=>v,fmt.pct,false],
                 ['Hit the 8-call ceiling','ceiling_rate',v=>v,fmt.pct,true]];
    items.forEach(([l,key,get,f,lowerBetter])=>{ const k=h('div','kpi'); k.appendChild(h('div','l',l));
      const bv=get(b[key]); k.appendChild(h('div','v',newest?f(get(newest[key])):f(bv)));
      if(!newest){ k.appendChild(h('div','d','baseline')); }
      else { k.appendChild(h('div','d','baseline '+f(bv)));
        [['v1',j1],['v2',j2]].forEach(([nm,arm])=>{ if(!arm) return; const {txt,good}=delta(bv,get(arm[key]),f,lowerBetter); const dd=h('div','d'+(good?' up':''),nm+': '+txt); k.appendChild(dd); }); }
      row.appendChild(k); });
    wrap.appendChild(row); });
})();

// ---- per-rung table -----------------------------------------------------------
(function(){
  const wrap=document.getElementById('rung'); const t=h('table'); const hr=h('tr');
  ['tier','model','arm','n','round trips','model time','selector','Claude cost','Jev cost','total cost','loaded any','skills in play','leak','ceiling','outcomes'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  ['0','1','2','3','4'].forEach(tier=>{ let first=true;
    MODELS.forEach(m=>ARMS.forEach(a=>{ const s=(L.per_tier[m+'_'+a]||{})[tier]; if(!s) return;
      const tr=h('tr',first?'sep':null);
      tr.appendChild(h('td',null,first?'tier '+tier:'')); first=false;
      tr.appendChild(h('td',null,D.models[m])); tr.appendChild(armCell(a));
      tr.appendChild(h('td',null,String(s.n))); tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean)));
      tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean))); tr.appendChild(h('td',null,a!=='base'?fmt.ms(s.preselect_ms.mean||0):'\u2014'));
      tr.appendChild(h('td',null,fmt.cost(s.cost.mean))); tr.appendChild(h('td',null,a!=='base'?'$'+s.preselect_cost.mean.toFixed(6):'\u2014')); tr.appendChild(h('td',null,fmt.cost(s.total_cost.mean)));
      tr.appendChild(h('td',null,fmt.pct(s.load_rate)));
      tr.appendChild(h('td',null,fmt.k(a!=='base'?(s.preselected_per_turn+s.skills_per_turn):s.skills_per_turn)));
      tr.appendChild(h('td',null,a!=='base'?fmt.k(s.leak_calls):'\u2014')); tr.appendChild(h('td',null,fmt.pct(s.ceiling_rate)));
      tr.appendChild(h('td','l',Object.entries(s.outcomes).map(([k,v])=>k.toLowerCase()+' '+v).join(' \u00b7 ')));
      tb.appendChild(tr); })); });
  t.appendChild(tb); wrap.appendChild(t);
})();

// ---- grouped bars per scenario, one panel per model per metric ------------------
const PANELS=[
  {key:'llm_calls', title:'Round trips', unit:'Claude calls per turn, mean of 5', f:fmt.calls},
  {key:'llm_ms', title:'Model time', unit:'ms waiting on Claude, mean of 5 (selector excluded)', f:fmt.ms},
  {key:'preselect_ms', title:'Selector latency', unit:'ms spent in the Jev call, mean of 5 (baseline has none)', f:fmt.ms, jevOnly:true},
  {key:'cost', title:'Claude cost', unit:'dollars per turn at each model\'s rate, mean of 5', f:fmt.cost},
  {key:'load_rate', title:'Loaded any skill via load_skill', unit:'share of runs; for Jev this is leakage after pre-selection', f:fmt.pct, flat:true},
];
function niceMax(v){ if(v<=0) return 1; const e=Math.pow(10,Math.floor(Math.log10(v))); const m=v/e; const nm=m<=1?1:m<=2?2:m<=2.5?2.5:m<=3?3:m<=4?4:m<=5?5:m<=6?6:m<=8?8:10; return nm*e; }
function tickLabel(p,v){ if(v===0) return p.key==='cost'?'$0':'0'; if(p.key==='cost') return '$'+v.toFixed(v<0.01?3:2); if(p.key==='load_rate') return Math.round(v*100)+'%'; if(p.key==='llm_ms'||p.key==='preselect_ms') return (v/1000).toFixed(v<1000?1:0)+'s'; return String(Math.round(v*10)/10); }
function val(s,p){ if(!s) return null; return p.flat? s[p.key] : (s[p.key]&&s[p.key].mean!=null? s[p.key].mean : null); }
function panel(p,m){
  const W=560,H=250,padL=44,padR=8,padT=14,padB=48; const cases=L.cases, n=cases.length;
  const series=ARMS.filter(a=>L.per_case[m+'_'+a]);
  const bw=series.length>2?13:18,gap=2,groupW=bw*series.length+gap*(series.length-1); const slot=(W-padL-padR)/n;
  const vals=[]; cases.forEach(c=>series.forEach(a=>{const v=val((L.per_case[m+'_'+a]||{})[c.id],p); if(v!=null) vals.push(v);}));
  const nice=niceMax(Math.max(...vals,0.0001)); const y=v=>padT+(H-padT-padB)*(1-v/nice);
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':p.title+' '+D.models[m]});
  for(let i=0;i<=5;i++){const v=nice*i/5,yy=y(v); svg.appendChild(el('line',{x1:padL,x2:W-padR,y1:yy,y2:yy,class:i===0?'ax':'gl'})); svg.appendChild(el('text',{x:padL-6,y:yy+4,'text-anchor':'end',class:'tick'},tickLabel(p,v)));}
  let prev=null,start=0; cases.forEach((c,i)=>{ if(c.tier!==prev){ if(prev!==null) svg.appendChild(el('text',{x:padL+slot*(start+(i-start)/2),y:H-8,'text-anchor':'middle',class:'band'},'tier '+prev)); prev=c.tier; start=i; } });
  svg.appendChild(el('text',{x:padL+slot*(start+(n-start)/2),y:H-8,'text-anchor':'middle',class:'band'},'tier '+prev));
  cases.forEach((c,i)=>{ const cx=padL+slot*i+slot/2; svg.appendChild(el('text',{x:cx,y:H-24,'text-anchor':'middle',class:'xl'},c.id.replace(/^t\d-/,'')));
    series.forEach((a,j)=>{ const s=(L.per_case[m+'_'+a]||{})[c.id]; const v=val(s,p); if(v==null) return;
      const x=cx-groupW/2+j*(bw+gap), top=y(v), base=y(0), hgt=Math.max(0,base-top), r=Math.min(4,hgt/2);
      const d=`M${x},${base} V${top+r} a${r},${r} 0 0 1 ${r},-${r} h${bw-2*r} a${r},${r} 0 0 1 ${r},${r} V${base} Z`;
      const bar=el('path',{d,class:'bar '+a,tabindex:0}); const hit=el('rect',{x:x-3,y:padT,width:bw+6,height:H-padT-padB,class:'hit'});
      const show=ev=>{ tip.replaceChildren(); tip.appendChild(h('b',null,p.f(v))); tip.appendChild(document.createElement('br'));
        const k=h('i','k'); k.style.background='var(--'+a+')'; tip.appendChild(k); tip.appendChild(document.createTextNode(D.arms[a]+' \u00b7 '+D.models[m]+' \u00b7 '+c.id));
        tip.appendChild(document.createElement('br'));
        if(!p.flat && s[p.key] && s[p.key].p50!=null) tip.appendChild(document.createTextNode('median '+p.f(s[p.key].p50)+' \u00b7 n='+s.n));
        else tip.appendChild(document.createTextNode('n='+s.n));
        if(a!=='base'){ tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode('pre-loaded: '+(s.preselected_seen.join(', ')||'none'))); }
        tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode('loaded via tool: '+(s.skills_seen.join(', ')||'none')));
        tip.style.display='block'; move(ev); };
      const move=ev=>{ tip.style.left=Math.min((ev.clientX||0)+14, window.innerWidth-320)+'px'; tip.style.top=((ev.clientY||0)+14)+'px'; };
      const hide=()=>{ tip.style.display='none'; };
      [hit,bar].forEach(t=>{ t.addEventListener('pointerenter',show); t.addEventListener('pointermove',move); t.addEventListener('pointerleave',hide); });
      bar.addEventListener('focus',()=>{ const r=bar.getBoundingClientRect(); show({clientX:r.left+r.width/2, clientY:r.top}); }); bar.addEventListener('blur',hide);
      svg.appendChild(hit); svg.appendChild(bar); }); });
  const wrap=h('div','card panel'); wrap.appendChild(h('h3',null,p.title+' \u00b7 '+D.models[m])); wrap.appendChild(h('p','unit',p.unit)); wrap.appendChild(svg); return wrap;
}
(function(){ const root=document.getElementById('charts');
  PANELS.forEach(p=>{ const g=h('div','grid'); g.style.marginBottom='16px'; let any=false;
    MODELS.forEach(m=>{ const anyArm=ARMS.some(a=>L.per_case[m+'_'+a]); if(!anyArm) return; if(p.jevOnly && !L.per_case[m+'_jev'] && !L.per_case[m+'_jev2']) return; g.appendChild(panel(p,m)); any=true; });
    if(any) root.appendChild(g); }); })();

// ---- agreement table ----------------------------------------------------------
(function(){ const wrap=document.getElementById('agree'); if(!Object.keys(L.agreement).length){ wrap.appendChild(h('p','note','Jev arm not run yet.')); return; }
  const t=h('table'); const hr=h('tr'); ['scenario','model','arm','baseline loaded (majority)','pre-loaded','effective set','jaccard vs own baseline','jaccard vs Sonnet baseline','leak calls'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  L.cases.forEach(c=>{ let first=true; MODELS.forEach(m=>['jev','jev2'].forEach(a=>{ const A=(L.agreement[m+'_'+a]||{})[c.id]; if(!A) return; const tr=h('tr',first?'sep':null);
    tr.appendChild(h('td',null,first?c.id:'')); first=false; tr.appendChild(h('td',null,D.models[m])); tr.appendChild(armCell(a));
    tr.appendChild(h('td','l',A.base.join(', ')||'none')); tr.appendChild(h('td','l',A.jev_pre.join(', ')||'none')); tr.appendChild(h('td','l',A.jev_effective.join(', ')||'none'));
    tr.appendChild(h('td',null,A.jaccard.toFixed(2)));
    const rj=((L.ref_agreement||{})[m+'_'+a]||{})[c.id]; tr.appendChild(h('td',null,rj==null?'\u2014':rj.toFixed(2)));
    tr.appendChild(h('td',null,fmt.k(A.leak))); tb.appendChild(tr); })); });
  t.appendChild(tb); wrap.appendChild(t); })();

// ---- scenario table view --------------------------------------------------------
(function(){ const wrap=document.getElementById('scen'); const t=h('table'); const hr=h('tr');
  ['scenario','tier','model','arm','round trips','model time','selector','Claude cost','loaded via tool','skills in play','skills seen'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  L.cases.forEach(c=>{ let first=true; MODELS.forEach(m=>ARMS.forEach(a=>{ const s=(L.per_case[m+'_'+a]||{})[c.id]; if(!s) return; const tr=h('tr',first?'sep':null);
    tr.appendChild(h('td',null,first?c.id:'')); tr.appendChild(h('td',null,first?String(c.tier):'')); first=false;
    tr.appendChild(h('td',null,D.models[m])); tr.appendChild(armCell(a));
    tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean))); tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean))); tr.appendChild(h('td',null,a!=='base'?fmt.ms(s.preselect_ms.mean||0):'\u2014'));
    tr.appendChild(h('td',null,fmt.cost(s.cost.mean))); tr.appendChild(h('td',null,fmt.pct(s.load_rate)));
    tr.appendChild(h('td',null,fmt.k(a!=='base'?(s.preselected_per_turn+s.skills_per_turn):s.skills_per_turn)));
    tr.appendChild(h('td','l',[...new Set([...(s.preselected_seen||[]),...(s.skills_seen||[])])].join(', ')||'\u2014'));
    tb.appendChild(tr); })); });
  t.appendChild(tb); wrap.appendChild(t); })();

// ---- stress block ---------------------------------------------------------------
(function(){ const S=D.stress; if(!Object.keys(S.overall).length) return; document.getElementById('stress-section').hidden=false;
  const wrap=document.getElementById('stress'); const t=h('table'); const hr=h('tr');
  ['scenario','model','arm','round trips','max calls','hit ceiling','model time','selector','cost','skills in play','leak','outcomes'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  S.cases.forEach(c=>{ let first=true; MODELS.forEach(m=>ARMS.forEach(a=>{ const s=(S.per_case[m+'_'+a]||{})[c.id]; if(!s) return; const tr=h('tr',first?'sep':null);
    tr.appendChild(h('td',null,first?c.id:'')); first=false; tr.appendChild(h('td',null,D.models[m])); tr.appendChild(armCell(a));
    tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean))); tr.appendChild(h('td',null,s.max_calls+' / '+D.max_steps)); tr.appendChild(h('td',null,fmt.pct(s.ceiling_rate)));
    tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean))); tr.appendChild(h('td',null,a!=='base'?fmt.ms(s.preselect_ms.mean||0):'\u2014')); tr.appendChild(h('td',null,fmt.cost(s.cost.mean)));
    tr.appendChild(h('td',null,fmt.k(a!=='base'?(s.preselected_per_turn+s.skills_per_turn):s.skills_per_turn))); tr.appendChild(h('td',null,a!=='base'?fmt.k(s.leak_calls):'\u2014'));
    tr.appendChild(h('td','l',Object.entries(s.outcomes).map(([k,v])=>k.toLowerCase()+' '+v).join(' \u00b7 '))); tb.appendChild(tr); })); });
  t.appendChild(tb); wrap.appendChild(t);
  S.cases.forEach(c=>{ const q=h('p','note'); q.style.marginTop='12px'; q.appendChild(h('b',null,c.id+' ')); q.appendChild(document.createTextNode('\u201c'+c.prompt+'\u201d (designed: '+c.expected.length+' skills)')); wrap.appendChild(q); }); })();

// ---- findings, computed ---------------------------------------------------------
(function(){ const f=document.getElementById('findings');
  const add=(b,txt)=>{ const d=h('div','finding'); d.appendChild(h('b',null,b+' ')); d.appendChild(document.createTextNode(txt)); f.appendChild(d); };
  const pc=v=>Math.round(v*100)+'%';
  MODELS.forEach(m=>{ const b=L.overall[m+'_base']; if(!b) return;
    ['jev','jev2'].forEach(a=>{ const j=L.overall[m+'_'+a]; if(!j) return; const nm=D.arms[a];
      const ag=Object.values(L.agreement[m+'_'+a]||{}); const jac=ag.length? ag.reduce((s,x)=>s+x.jaccard,0)/ag.length : NaN;
      const rr=Object.values((L.ref_agreement||{})[m+'_'+a]||{}); const rjac=rr.length? rr.reduce((s,v)=>s+v,0)/rr.length : NaN;
      const rb=Object.values((L.ref_agreement||{})[m+'_base']||{}); const rbjac=rb.length? rb.reduce((s,v)=>s+v,0)/rb.length : NaN;
      add(D.models[m]+' \u00b7 '+nm+': round trips '+b.llm_calls.mean.toFixed(1)+' \u2192 '+j.llm_calls.mean.toFixed(1)+'.', 'Model time '+fmt.s(b.llm_ms.mean)+' \u2192 '+fmt.s(j.llm_ms.mean)+'; wall clock including the selector '+fmt.s(b.wall_ms.mean)+' \u2192 '+fmt.s(j.wall_ms.mean)+'. Claude cost '+fmt.cost(b.cost.mean)+' \u2192 '+fmt.cost(j.cost.mean)+' per turn; total incl. Jev '+fmt.cost(b.total_cost.mean)+' \u2192 '+fmt.cost(j.total_cost.mean)+'. Selector '+fmt.ms(j.preselect_ms.mean||0)+', '+Math.round(j.preselect_tokens.mean||0)+' Jev input tokens per turn.');
      add(D.models[m]+' \u00b7 '+nm+': skill agreement '+(isNaN(jac)?'n/a':jac.toFixed(2))+' vs its own baseline, '+(isNaN(rjac)?'n/a':rjac.toFixed(2))+' vs the Sonnet baseline (that model\'s own baseline scores '+(isNaN(rbjac)?'n/a':rbjac.toFixed(2))+' on the same reference).', 'Pre-loaded '+j.preselected_per_turn.toFixed(1)+' skills per turn; Dad still called load_skill on '+pc(j.load_rate)+' of turns ('+j.leak_calls.toFixed(1)+' calls per turn) versus '+pc(b.load_rate)+' at baseline. Outcomes baseline '+JSON.stringify(b.outcomes)+' vs '+JSON.stringify(j.outcomes)+'.');
    }); });
  const S=D.stress; MODELS.forEach(m=>{ const b=S.overall[m+'_base']; if(!b) return; const arms=['jev','jev2'].filter(a=>S.overall[m+'_'+a]);
    add('Stress, '+D.models[m]+': ceiling hit '+pc(b.ceiling_rate)+arms.map(a=>' \u2192 '+pc(S.overall[m+'_'+a].ceiling_rate)).join('')+'.', 'Max calls '+b.max_calls+arms.map(a=>' \u2192 '+S.overall[m+'_'+a].max_calls).join('')+' of '+D.max_steps+'. Round trips '+b.llm_calls.mean.toFixed(1)+arms.map(a=>' \u2192 '+S.overall[m+'_'+a].llm_calls.mean.toFixed(1)).join('')+', cost '+fmt.cost(b.cost.mean)+arms.map(a=>' \u2192 '+fmt.cost(S.overall[m+'_'+a].cost.mean)).join('')+' (baseline \u2192 v1 \u2192 v2 where run).'); });
  const ids=Object.entries(L.model_ids).map(([k,v])=>k+': '+v.join(', ')).join('; '); add('Models that actually answered.', ids);
})();
</script>
"""
Path(out_path).write_text(html.replace("__DATA__", json.dumps(payload)), encoding="utf-8")
have = {k: (len(rows(v))) for k, v in files.items()}
print("wrote", out_path, "| rows per file:", have)
