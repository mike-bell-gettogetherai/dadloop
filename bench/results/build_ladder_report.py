"""Build the ladder A/B artifact: per-rung table + side-by-side bars per scenario.

usage: python build_ladder_report.py <haiku.jsonl> <sonnet.jsonl> <out.html>
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/Users/mikemaddiemacmini/Code/dadloop")
from bench.prompts import LADDER, STRESS  # noqa: E402

haiku_path, sonnet_path, out_path = sys.argv[1:4]
stress_paths = sys.argv[4:6]   # optional: haiku-stress sonnet-stress


def rows(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def agg(rs):
    def st(k):
        v = [r[k] for r in rs if r.get(k) is not None]
        return {"mean": statistics.fmean(v), "p50": statistics.median(v)} if v else {"mean": None, "p50": None}
    return {
        "n": len(rs),
        "llm_calls": st("llm_calls"), "llm_ms": st("llm_ms"), "total_ms": st("total_ms"),
        "tokens_in": st("tokens_in"), "tokens_out": st("tokens_out"), "cost": st("cost"),
        "load_rate": sum(1 for r in rs if r.get("loaded_skills")) / len(rs),
        "skills_per_turn": sum(len(r.get("loaded_skills", [])) for r in rs) / len(rs),
        "unpriced": sum(r.get("unpriced_calls") or 0 for r in rs),
        "ceiling_rate": sum(1 for r in rs if r.get("hit_ceiling")) / len(rs),
        "max_calls": max(r.get("llm_calls") or 0 for r in rs),
        "outcomes": dict(sorted(defaultdict(int, {o: sum(1 for r in rs if r.get("outcome") == o)
                                                    for o in {r.get("outcome") for r in rs}}).items())),
        "skills_seen": sorted({s for r in rs for s in r.get("loaded_skills", [])}),
    }


arms = {"haiku": rows(haiku_path), "sonnet": rows(sonnet_path)}
labels = {"haiku": "Haiku 4.5", "sonnet": "Sonnet 5"}
model_ids = {a: sorted({m for r in rs for m in r.get("models", [])}) for a, rs in arms.items()}

by_case = {a: defaultdict(list) for a in arms}
by_tier = {a: defaultdict(list) for a in arms}
for a, rs in arms.items():
    for r in rs:
        by_case[a][r["case_id"]].append(r)
        by_tier[a][r["tier"]].append(r)

cases = [{"id": c["id"], "tier": c["tier"], "prompt": c["prompt"], "expected": c["expected_skills"]}
         for c in LADDER]
stress = None
if len(stress_paths) == 2:
    srows = {"haiku": rows(stress_paths[0]), "sonnet": rows(stress_paths[1])}
    sby = {a: defaultdict(list) for a in srows}
    for a, rs in srows.items():
        for r in rs:
            sby[a][r["case_id"]].append(r)
    stress = {
        "cases": [{"id": c["id"], "prompt": c["prompt"], "expected": c["expected_skills"]} for c in STRESS],
        "per_case": {a: {cid: agg(rs) for cid, rs in sby[a].items()} for a in srows},
        "overall": {a: agg(rs) for a, rs in srows.items()},
        "runs": {a: {cid: [{"llm_calls": r["llm_calls"], "hit_ceiling": r["hit_ceiling"], "loaded": r["loaded_skills"],
                            "cost": r["cost"], "llm_ms": r["llm_ms"], "outcome": r["outcome"]} for r in rs]
                     for cid, rs in sby[a].items()} for a in srows},
    }

data = {
    "labels": labels, "model_ids": model_ids, "stress": stress, "max_steps": 8,
    "cases": cases,
    "per_case": {a: {cid: agg(rs) for cid, rs in by_case[a].items()} for a in arms},
    "per_tier": {a: {str(t): agg(rs) for t, rs in sorted(by_tier[a].items())} for a in arms},
    "overall": {a: agg(rs) for a, rs in arms.items()},
}

html = r"""<title>Dadloop Ladder A/B</title>
<style>
:root{color-scheme:light;
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
  --haiku:#2a78d6;--sonnet:#eb6834;--tip-bg:#0b0b0b;--tip-ink:#fcfcfb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
  --haiku:#3987e5;--sonnet:#d95926;--tip-bg:#fcfcfb;--tip-ink:#0b0b0b}}
:root[data-theme="dark"]{color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
  --haiku:#3987e5;--sonnet:#d95926;--tip-bg:#fcfcfb;--tip-ink:#0b0b0b}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:40px 28px 64px}
h1{font-size:28px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance}
.sub{color:var(--ink-2);max-width:68ch;margin:0 0 28px}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
section{margin:0 0 40px}
h2{font-size:17px;font-weight:600;margin:0 0 4px}
.note{color:var(--ink-2);margin:0 0 14px;max-width:72ch}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:18px 20px}
.legend{display:flex;gap:18px;align-items:center;margin:0 0 6px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:7px}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:16px}
.panel h3{font-size:14px;font-weight:600;margin:0 0 2px}
.panel .unit{color:var(--muted);font-size:12px;margin:0 0 6px}
svg{display:block;width:100%;height:auto;overflow:visible}
.gl{stroke:var(--grid);stroke-width:1}
.ax{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.xl{fill:var(--ink-2);font-size:11px}
.band{fill:var(--muted);font-size:10px;letter-spacing:.06em;text-transform:uppercase}
.bar{transition:opacity .12s}
.bar.h{fill:var(--haiku)}.bar.s{fill:var(--sonnet)}
.bar:hover,.bar:focus{opacity:.78;outline:none}
.hit{fill:transparent}
.tip{position:fixed;pointer-events:none;background:var(--tip-bg);color:var(--tip-ink);padding:8px 10px;border-radius:6px;font-size:12px;line-height:1.35;display:none;z-index:9;max-width:280px}
.tip b{font-size:14px}
.tip .k{display:inline-block;width:10px;height:2px;vertical-align:middle;margin-right:6px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--muted);font-weight:500;font-size:12px}
th:first-child,td:first-child{text-align:left}
td.l{text-align:left;color:var(--ink-2)}
tr.model td:first-child{font-weight:600}
.tbl{overflow-x:auto}
details{margin-top:10px}summary{cursor:pointer;color:var(--ink-2)}
.finding{border-left:2px solid var(--axis);padding:2px 0 2px 14px;margin:10px 0}
.finding b{font-weight:600}
@media (prefers-reduced-motion:reduce){.bar{transition:none}}
</style>
<main>
<p class="eyebrow">dadloop &middot; benchmark &middot; baseline arm</p>
<h1>Dadloop Ladder A/B</h1>
<p class="sub">Ten prompts designed to need zero to four skills, run five times each through the stock Dad loop on two models. Fresh memory per case, frozen world state, nested web search disabled. Every number is read back from the harness's own journal.</p>

<section>
<h2>Per rung</h2>
<p class="note">Tier is the skill demand designed into the prompt. "Loaded any skill" and "skills per turn" are what Dad actually did, and the gap between designed and observed is the finding, not an error.</p>
<div class="card tbl" id="rung"></div>
</section>

<section>
<h2>Per scenario, side by side</h2>
<p class="note">Bars are means over five runs; hover a bar for the median and the spread. Scenarios are grouped by tier from left to right.</p>
<div class="legend"><span><i class="sw" style="background:var(--haiku)"></i>Haiku 4.5</span><span><i class="sw" style="background:var(--sonnet)"></i>Sonnet 5</span></div>
<div class="grid" id="charts"></div>
<details><summary>Table view of every scenario</summary><div class="card tbl" id="scen"></div></details>
</section>

<section id="stress-section" hidden>
<h2>Stress block, reported on its own</h2>
<p class="note">Two prompts no real Saturday would produce, run five times each. They exist to find the loop's hard ceiling of eight model calls per turn: a turn that wants seven skill bodies one round trip at a time can run out of calls and hand back "Dad got distracted" instead of an answer. Not folded into the ladder means.</p>
<div class="card tbl" id="stress"></div>
</section>

<section>
<h2>What it says</h2>
<div id="findings"></div>
</section>
</main>
<div class="tip" id="tip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const ARMS = ['haiku','sonnet'];
const CLS = {haiku:'h', sonnet:'s'};
const tip = document.getElementById('tip');
const fmt = {
  calls: v => v.toFixed(1), ms: v => Math.round(v).toLocaleString()+' ms', s: v => (v/1000).toFixed(1)+' s',
  cost: v => '$'+v.toFixed(4), pct: v => Math.round(v*100)+'%', k: v => v.toFixed(1),
};
function el(tag, attrs, text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e;}
function h(tag, cls, text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}

// ---- per-rung table -------------------------------------------------------
(function(){
  const wrap=document.getElementById('rung'); const t=h('table');
  const thead=h('thead'); const hr=h('tr');
  ['tier','model','n','round trips','model time','cost / turn','loaded any skill','skills / turn','outcomes'].forEach(x=>hr.appendChild(h('th',null,x)));
  thead.appendChild(hr); t.appendChild(thead); const tb=h('tbody');
  for(const tier of ['0','1','2','3','4']){
    ARMS.forEach((a,i)=>{
      const s=D.per_tier[a][tier]; if(!s) return;
      const tr=h('tr','model');
      tr.appendChild(h('td',null,i===0?'tier '+tier:''));
      const m=h('td'); const sw=h('i','sw'); sw.style.background='var(--'+a+')'; sw.style.marginRight='7px'; m.appendChild(sw); m.appendChild(document.createTextNode(D.labels[a])); m.style.textAlign='left'; tr.appendChild(m);
      tr.appendChild(h('td',null,String(s.n)));
      tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean)));
      tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean)));
      tr.appendChild(h('td',null,fmt.cost(s.cost.mean)));
      tr.appendChild(h('td',null,fmt.pct(s.load_rate)));
      tr.appendChild(h('td',null,fmt.k(s.skills_per_turn)));
      const oc=h('td','l',Object.entries(s.outcomes).map(([k,v])=>k.toLowerCase()+' '+v).join(' \u00b7 ')); tr.appendChild(oc);
      tb.appendChild(tr);
    });
  }
  t.appendChild(tb); wrap.appendChild(t);
})();

// ---- grouped bars per scenario --------------------------------------------
const PANELS=[
  {key:'llm_calls', title:'Round trips', unit:'model calls per turn, mean of 5', f:fmt.calls, sub:'p50'},
  {key:'llm_ms', title:'Model time', unit:'milliseconds spent waiting on the model, mean of 5', f:fmt.ms, sub:'p50'},
  {key:'cost', title:'Cost', unit:'dollars per turn at each model\'s own rate, mean of 5', f:fmt.cost, sub:'p50'},
  {key:'load_rate', title:'Loaded any skill', unit:'share of the 5 runs that called load_skill at least once', f:fmt.pct, flat:true},
];
function panel(p){
  const W=560, H=260, padL=44, padR=8, padT=14, padB=48;
  const cases=D.cases; const n=cases.length;
  const bw=18, gap=2, groupW=bw*2+gap; const slot=(W-padL-padR)/n;
  const vals=[]; cases.forEach(c=>ARMS.forEach(a=>{const s=D.per_case[a][c.id]; if(s) vals.push(p.flat?s[p.key]:s[p.key].mean);}));
  const maxV=Math.max(...vals,0.0001); const nice=niceMax(maxV); const y=v=>padT+(H-padT-padB)*(1-v/nice);
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':p.title});
  const ticks=5; for(let i=0;i<=ticks;i++){const v=nice*i/ticks; const yy=y(v); svg.appendChild(el('line',{x1:padL,x2:W-padR,y1:yy,y2:yy,class:i===0?'ax':'gl'})); svg.appendChild(el('text',{x:padL-6,y:yy+4,'text-anchor':'end',class:'tick'},tickLabel(p,v)));}
  // tier bands
  let prev=null, start=0;
  cases.forEach((c,i)=>{ if(c.tier!==prev){ if(prev!==null){svg.appendChild(el('text',{x:padL+slot*(start+(i-start)/2),y:H-8,'text-anchor':'middle',class:'band'},'tier '+prev));} prev=c.tier; start=i; } });
  svg.appendChild(el('text',{x:padL+slot*(start+(n-start)/2),y:H-8,'text-anchor':'middle',class:'band'},'tier '+prev));
  cases.forEach((c,i)=>{
    const cx=padL+slot*i+slot/2;
    svg.appendChild(el('text',{x:cx,y:H-24,'text-anchor':'middle',class:'xl'},c.id.replace(/^t\d-/,'')));
    ARMS.forEach((a,j)=>{
      const s=D.per_case[a][c.id]; if(!s) return; const v=p.flat?s[p.key]:s[p.key].mean;
      const x=cx-groupW/2+j*(bw+gap); const top=y(v); const base=y(0); const hgt=Math.max(0,base-top);
      const r=Math.min(4,hgt/2);
      const d=`M${x},${base} V${top+r} a${r},${r} 0 0 1 ${r},-${r} h${bw-2*r} a${r},${r} 0 0 1 ${r},${r} V${base} Z`;
      const bar=el('path',{d,class:'bar '+CLS[a],tabindex:0});
      const hit=el('rect',{x:x-3,y:padT,width:bw+6,height:H-padT-padB,class:'hit'});
      const show=(ev)=>{ tip.replaceChildren(); const b=h('b',null,p.f(v)); tip.appendChild(b); tip.appendChild(document.createElement('br'));
        const k=h('i','k'); k.style.background='var(--'+a+')'; tip.appendChild(k); tip.appendChild(document.createTextNode(D.labels[a]+' \u00b7 '+c.id));
        if(!p.flat){ tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode('median '+p.f(s[p.key].p50)+' \u00b7 n='+s.n)); }
        else { tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode(s.skills_seen.length? 'loaded: '+s.skills_seen.join(', ') : 'no skill loaded in any run')); }
        tip.appendChild(document.createElement('br')); const q=h('span',null,'\u201c'+c.prompt+'\u201d'); q.style.opacity='.75'; tip.appendChild(q);
        tip.style.display='block'; move(ev); };
      const move=(ev)=>{ const px=ev.clientX!=null?ev.clientX:0, py=ev.clientY!=null?ev.clientY:0; tip.style.left=Math.min(px+14, window.innerWidth-300)+'px'; tip.style.top=(py+14)+'px'; };
      const hide=()=>{ tip.style.display='none'; };
      [hit,bar].forEach(t=>{ t.addEventListener('pointerenter',show); t.addEventListener('pointermove',move); t.addEventListener('pointerleave',hide); });
      bar.addEventListener('focus',(ev)=>{ const r=bar.getBoundingClientRect(); show({clientX:r.left+r.width/2, clientY:r.top}); }); bar.addEventListener('blur',hide);
      svg.appendChild(hit); svg.appendChild(bar);
    });
  });
  const wrap=h('div','card panel'); wrap.appendChild(h('h3',null,p.title)); wrap.appendChild(h('p','unit',p.unit)); wrap.appendChild(svg); return wrap;
}
function niceMax(v){ if(v<=0) return 1; const e=Math.pow(10,Math.floor(Math.log10(v))); const m=v/e; const nm= m<=1?1: m<=2?2: m<=2.5?2.5: m<=3?3: m<=4?4: m<=5?5: m<=6?6: m<=8?8:10; return nm*e; }
function tickLabel(p,v){ if(v===0) return p.key==='cost'?'$0':'0'; if(p.key==='cost') return '$'+v.toFixed(v<0.01?3:2); if(p.key==='load_rate') return Math.round(v*100)+'%'; if(p.key==='llm_ms') return (v/1000).toFixed(v<1000?1:0)+'s'; return String(Math.round(v*10)/10); }
const charts=document.getElementById('charts'); PANELS.forEach(p=>charts.appendChild(panel(p)));

// ---- scenario table ---------------------------------------------------------
(function(){
  const wrap=document.getElementById('scen'); const t=h('table'); const hr=h('tr');
  ['scenario','tier','model','round trips','model time','cost','loaded any','skills / turn','skills seen'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  D.cases.forEach(c=>ARMS.forEach((a,i)=>{ const s=D.per_case[a][c.id]; if(!s) return; const tr=h('tr');
    tr.appendChild(h('td',null,i===0?c.id:'')); tr.appendChild(h('td',null,i===0?String(c.tier):''));
    const m=h('td'); const sw=h('i','sw'); sw.style.background='var(--'+a+')'; sw.style.marginRight='7px'; m.appendChild(sw); m.appendChild(document.createTextNode(D.labels[a])); m.style.textAlign='left'; tr.appendChild(m);
    tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean))); tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean))); tr.appendChild(h('td',null,fmt.cost(s.cost.mean)));
    tr.appendChild(h('td',null,fmt.pct(s.load_rate))); tr.appendChild(h('td',null,fmt.k(s.skills_per_turn))); tr.appendChild(h('td','l',s.skills_seen.join(', ')||'\u2014'));
    tb.appendChild(tr); }));
  t.appendChild(tb); wrap.appendChild(t);
})();

// ---- stress block -----------------------------------------------------------
(function(){
  if(!D.stress) return; document.getElementById('stress-section').hidden=false;
  const wrap=document.getElementById('stress'); const t=h('table'); const hr=h('tr');
  ['scenario','model','round trips','max calls','hit ceiling','model time','cost','skills / turn','skills seen','outcomes'].forEach(x=>hr.appendChild(h('th',null,x)));
  const th=h('thead'); th.appendChild(hr); t.appendChild(th); const tb=h('tbody');
  D.stress.cases.forEach(c=>ARMS.forEach((a,i)=>{ const s=D.stress.per_case[a][c.id]; if(!s) return; const tr=h('tr','model');
    tr.appendChild(h('td',null,i===0?c.id:''));
    const m=h('td'); const sw=h('i','sw'); sw.style.background='var(--'+a+')'; sw.style.marginRight='7px'; m.appendChild(sw); m.appendChild(document.createTextNode(D.labels[a])); m.style.textAlign='left'; tr.appendChild(m);
    tr.appendChild(h('td',null,fmt.calls(s.llm_calls.mean))); tr.appendChild(h('td',null,String(s.max_calls)+' / '+D.max_steps));
    tr.appendChild(h('td',null,fmt.pct(s.ceiling_rate))); tr.appendChild(h('td',null,fmt.s(s.llm_ms.mean))); tr.appendChild(h('td',null,fmt.cost(s.cost.mean)));
    tr.appendChild(h('td',null,fmt.k(s.skills_per_turn))); tr.appendChild(h('td','l',s.skills_seen.join(', ')||'\u2014'));
    tr.appendChild(h('td','l',Object.entries(s.outcomes).map(([k,v])=>k.toLowerCase()+' '+v).join(' \u00b7 ')));
    tb.appendChild(tr); }));
  t.appendChild(tb); wrap.appendChild(t);
  D.stress.cases.forEach(c=>{ const q=h('p','note'); q.style.marginTop='12px'; q.appendChild(h('b',null,c.id+' ')); q.appendChild(document.createTextNode('\u201c'+c.prompt+'\u201d  (designed: '+c.expected.length+' skills)')); wrap.appendChild(q); });
})();

// ---- findings (computed, not asserted) ------------------------------------
(function(){
  const f=document.getElementById('findings'); const H=D.overall.haiku, S=D.overall.sonnet;
  const T=(a,t,k)=>{const x=D.per_tier[a][t]; return x? (k==='load_rate'? x.load_rate : x[k].mean) : NaN;};
  const pc=v=>isNaN(v)?'n/a':Math.round(v*100)+'%'; const f1=v=>isNaN(v)?'n/a':v.toFixed(1);
  const add=(b,txt)=>{ const d=h('div','finding'); const bb=h('b',null,b+' '); d.appendChild(bb); d.appendChild(document.createTextNode(txt)); f.appendChild(d); };
  add('Skill loading is unreliable on both models.', `Across all 50 turns, Haiku loaded a skill on ${Math.round(H.load_rate*100)}% and Sonnet on ${Math.round(S.load_rate*100)}%. Tier 1 prompts, which need exactly one skill, loaded one on ${pc(T('haiku','1','load_rate'))} (Haiku) and ${pc(T('sonnet','1','load_rate'))} (Sonnet) of runs.`);
  add('Round trips barely climb the ladder.', `Haiku averages ${H.llm_calls.mean.toFixed(1)} calls per turn overall and ${f1(T('haiku','4','llm_calls'))} at tier 4; Sonnet ${S.llm_calls.mean.toFixed(1)} and ${f1(T('sonnet','4','llm_calls'))}. Both models batch several load_skill calls into one response, so pre-selection can remove at most about one round trip per turn.`);
  add('Cost per turn.', `Haiku ${fmt.cost(H.cost.mean)} mean, Sonnet ${fmt.cost(S.cost.mean)} mean, priced at each model's own rate with ${H.unpriced+S.unpriced} unpriced calls. Tokens in per turn: Haiku ${Math.round(H.tokens_in.mean).toLocaleString()}, Sonnet ${Math.round(S.tokens_in.mean).toLocaleString()}.`);
  add('Model time.', `Haiku ${fmt.s(H.llm_ms.mean)} per turn, Sonnet ${fmt.s(S.llm_ms.mean)}. Tool time is under a millisecond on every row because the nested web search was disabled, so model time is the whole wall clock.`);
  if(D.stress){ const hs=D.stress.overall.haiku, ss=D.stress.overall.sonnet;
    add('The eight-call ceiling.', `On the stress prompts Haiku hit the ceiling on ${Math.round(hs.ceiling_rate*100)}% of runs (max ${hs.max_calls} calls), Sonnet on ${Math.round(ss.ceiling_rate*100)}% (max ${ss.max_calls}). A pre-selector injects skill bodies before the first call, so this is the case it relieves most directly.`); }
  add('Models that actually answered.', `Haiku rows: ${D.model_ids.haiku.join(', ')}. Sonnet rows: ${D.model_ids.sonnet.join(', ')}.`);
})();
</script>
"""
Path(out_path).write_text(html.replace("__DATA__", json.dumps(data)), encoding="utf-8")
print("wrote", out_path, "| haiku rows", len(arms["haiku"]), "| sonnet rows", len(arms["sonnet"]))
