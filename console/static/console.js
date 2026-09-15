/* Mom's Console — controller.
 *
 * Everything on screen is a fold over an append-only event log. Given a
 * session's events and a cursor (idx), render() derives what the house, the
 * dock, the stage rail, the milestone list and the conversation thread all
 * looked like at that exact moment. Nothing is mutated incrementally.
 *
 * That one decision buys three things. Live and replay are the same code
 * path: live just moves the cursor forward as events land. Scrubbing
 * backwards is free: move the cursor and re-fold. And every business-level
 * claim can name its cause: milestones carry caused_by_seq, and bySeq resolves
 * it to the mechanical event underneath.
 *
 * The unit of replay is the SESSION, not the turn. A person talking to Dad
 * experiences "plan the sleepover" → "when is it?" → "this weekend" → "how
 * many kids?" → ... → the plan, as one exchange. Replaying only the final turn
 * (an earlier version of this file did) meant a session that was all
 * questions animated nothing at all. Now Play walks the whole conversation:
 * Dad asks in the house, the thread reveals row by row, and when the turn
 * that actually does work arrives, the rooms light up.
 */

// ------------------------------------------------------------------ mapping
// Which room a tool puts Dad in. Keyed by tool name.
const ROOM_OF = {
  check_grill:'grill', check_pantry:'pantry', check_weather:'weather',
  check_wallet:'budget', find_tool:'tools', check_hardware_store:'store',
  web_search:'store', set_thermostat:'hall',
};
// Skills with no dedicated tool still have a room. Keyed by SKILL name (the
// argument to load_skill), because "yard-work" never calls a check_* tool the
// way grilling calls check_grill; loading the playbook is the only signal.
const SKILL_ROOM = {
  'yard-work':'lawn', 'the-thermostat':'hall', 'grilling':'grill',
  'hosting':'pantry', 'money-decisions':'budget', 'grocery-runs':'store',
  'fixing-things':'tools',
};
// What Dad would say he is doing, in his own words, rather than the function name.
const DOING = {
  check_grill:'checking the grill', check_pantry:'checking the pantry',
  check_weather:'checking the sky', check_wallet:'counting the money',
  find_tool:'finding a tool', check_hardware_store:'heading to the store',
  web_search:'looking it up', set_thermostat:'thermostat...',
  load_skill:'pulling a playbook', remember:'making a note', recall:'remembering',
  tell_joke:'got a joke',
};
const SKILL_DOING = { 'yard-work':'out on the lawn' };
// The dock: one slot per tool. Keys starting with "__" are skills, not tools.
const DOCK = [
  ['check_grill','grill'], ['check_pantry','pantry'], ['check_wallet','wallet'],
  ['check_hardware_store','store'], ['check_weather','weather'],
  ['find_tool','tools'], ['web_search','search'], ['set_thermostat','thermostat'],
  ['__yard-work','lawn'],
];
// Only these tools send Dad out of the house entirely, car and all. Searching
// the web about the hardware store does not; actually going there does.
const SENDS_DAD_OUT = new Set(['check_hardware_store']);
const STAGES = ['RECEIVED','FRAMING','GATHERING','BLOCKED','REPLANNING',
                'GOVERNED','RESOLVING','AWAITING_INPUT','DELIVERED'];
const TICK_MS = 700;   // replay speed: one event per tick

// ------------------------------------------------------------------ state
const $ = id => document.getElementById(id);
let EVENTS = [];        // the whole session, in journal order
let bySeq = {};         // seq -> event, for resolving caused_by_seq
let idx = 0;            // replay cursor: events[0, idx) have "happened"
let timer = null;       // setInterval handle while playing
let ledger = {}, ledTab = 'grievances', ledRaw = false;
let prevTrouble = new Set();   // rooms already red last frame, so a shake fires once

const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* Room caption: the first sentence of a tool result, with the PROBLEM/CONFLICT
 * prefix stripped, cut to fit inside a room. */
function caption(txt){
  let t = (txt || '').replace(/^(PROBLEM|CONFLICT):\s*/i, '').split('. ')[0];
  return t.length > 30 ? t.slice(0, 29).replace(/\s+$/, '') + '\u2026' : t;
}
/* Speech-bubble caption: shorter still, since it sits over a sprite. */
function bubbleText(txt){
  const t = (txt || '').replace(/\s+/g, ' ').trim();
  return t.length > 34 ? t.slice(0, 33).replace(/\s+$/, '') + '\u2026' : t;
}

// ------------------------------------------------------------------- boot
async function boot({ keepCursor = false } = {}){
  // Two failure modes, two messages. A fetch that never connects means the
  // server is not running. Anything after that is OUR bug, and saying "is the
  // server running?" for it sends people to check the wrong thing.
  let meta, sessions;
  try{
    meta = await (await fetch('/api/meta')).json();
    sessions = await (await fetch('/api/sessions')).json();
  }catch(err){
    console.error('console API unreachable:', err);
    $('banner').innerHTML = '<div class="banner">Could not reach the console API at ' +
      esc(location.origin) + '. Start it with <code>dadloop --console</code>.</div>';
    return;
  }
  try{
    $('jpath').textContent = meta.journal;
    if(!meta.exists){
      $('banner').innerHTML = '<div class="banner">No journal yet at <code>' +
        esc(meta.journal) + '</code>. Run a dadloop turn and it will appear here.</div>';
    }
    if(!sessions.length){
      $('banner').innerHTML = '<div class="banner">The journal is empty. ' +
        'Talk to Dad once, then reload.</div>';
      drawDock({}); $('houseWorld').innerHTML = drawWorld(blankState()); placeDad(blankState());
      return;
    }
    const current = $('turnsel').value;
    $('turnsel').innerHTML = sessions.map(s => {
      const tag = s.turns > 1 ? ` (${s.turns} turns)` : '';
      const wait = s.status === 'waiting' ? ' \u00b7 waiting on you' : '';
      // Two or more people in a session: say who, so a shared house is
      // recognisable from the list alone.
      const who = (s.people || []).length > 1 ? ` \u00b7 ${esc(s.people.join(', '))}` : '';
      return `<option value="${esc(s.session_id)}">${esc(s.session_id.slice(11,19))} · ` +
             `${esc((s.prompt||'(no prompt)').slice(0,44))}${tag}${who}${wait}</option>`;
    }).join('');
    $('turnsel').onchange = e => loadSession(e.target.value);
    await loadLedger();
    // Live refresh. If the person is mid-replay, keep them on their session and
    // their cursor, but DO reload that session's events: a new answer in the
    // conversation they are watching must appear. Only jump to the newest
    // session when they have not started replaying anything.
    if(keepCursor && current && sessions.some(s => s.session_id === current) && idx > 0){
      $('turnsel').value = current;
      await loadSession(current, { keepCursor: true });
      return;
    }
    await loadSession(sessions[0].session_id);
    $('banner').innerHTML = '';
  }catch(err){
    console.error('console render failed:', err);
    $('banner').innerHTML = '<div class="banner">The console hit an error while drawing: <code>' +
      esc(err && err.message || err) + '</code>. Try a hard refresh (Ctrl+Shift+R); ' +
      'if it persists this is a bug in the console, not the server.</div>';
  }
}

const blankState = () => ({ roomStates:{}, details:{}, dadRoom:'hall', dadOut:false,
                            dadSays:'', momRoom:null, momSays:'' });

/* Load one session: every turn in it, oldest first. This is the whole unit of
 * replay. The milestone list is built from the entire session so a question
 * asked in turn one is on record alongside the plan landed in turn four. */
async function loadSession(sessionId, { keepCursor = false } = {}){
  if(!keepCursor) stop();
  EVENTS = await (await fetch('/api/session/' + encodeURIComponent(sessionId))).json();
  bySeq = {}; EVENTS.forEach(e => bySeq[e.seq] = e);
  // On a live refresh the log only grows, so the old cursor still points at
  // the same event; clamp defensively and keep the person where they were.
  idx = keepCursor ? Math.min(idx, EVENTS.length) : 0;
  $('scrub').max = EVENTS.length;
  buildThread(EVENTS);

  const ms = EVENTS.filter(e => e.kind === 'milestone');
  $('mlist').innerHTML = ms.length ? ms.map((m, i) => {
    const cls = m.milestone === 'CONSTRAINT_FOUND' ? 't'
              : m.milestone === 'AUTHORITY_APPLIED' ? 'g'
              : m.milestone === 'CLARIFICATION_ASKED' ? 'q' : '';
    const det = [m.subject, m.detail].filter(Boolean).map(esc).join(' &middot; ');
    const gl = icon(MILESTONE_ICON[m.milestone] || 'circle-check', { size:14 });
    return `<div class="ms ${cls}" data-seq="${m.seq}" data-cause="${m.caused_by_seq}" tabindex="0">
      <div class="circ">${gl}</div>
      <div><div class="nm">${esc(m.milestone.replace(/_/g,' ').toLowerCase())}
        <span class="ix">${String(i+1).padStart(2,'0')}</span></div>
      <div class="dt">${det || '&mdash;'}</div></div></div>`;
  }).join('') : '<div class="led"><div class="empty">No milestones in this session.</div></div>';

  $('stages').innerHTML = STAGES.map(s =>
    `<div class="stg" data-s="${s}">${s.toLowerCase().replace('_',' ')}</div>`).join('');
  render();
}

// ----------------------------------------------------------------- thread
/* The conversation, one row per turn. Built once per session with EVERY row
 * present in the DOM, each tagged with the seq of the event that makes it
 * appear. render() then toggles visibility against the cursor, so during
 * replay the thread fills in one exchange at a time instead of being dumped
 * on screen all at once. Before this existed, a clarifying round-trip lived
 * only in the ephemeral TUI. */
function buildThread(events){
  const byTurn = {}, order = [];
  events.forEach(e => {
    if(!e.turn_id) return;
    if(!byTurn[e.turn_id]){ byTurn[e.turn_id] = {}; order.push(e.turn_id); }
    const t = byTurn[e.turn_id];
    if(e.kind === 'turn_start') { t.prompt = e.prompt; t.askSeq = e.seq; t.user = e.user; }
    if(e.kind === 'clarify')    t.reply = { text: e.text, kind: 'q',     seq: e.seq };
    if(e.kind === 'final')      t.reply = { text: e.text, kind: 'final', seq: e.seq };
  });

  // Who took part, in order. With more than one person the thread is the
  // record of a shared house, and the card says so.
  const people = [];
  order.forEach(tid => { const u = byTurn[tid].user; if(u && !people.includes(u)) people.push(u); });
  const meta = $('threadcard').querySelector('.meta');
  if(meta) meta.textContent = people.length > 1 ? `${people.join(' and ')}, in order` : 'one session, in order';

  // A lone single-turn session has nothing to thread; the house tells it.
  $('threadcard').style.display = order.length > 1 ? '' : 'none';

  $('thread').innerHTML = order.map((tid, i) => {
    const t = byTurn[tid];
    const dadCls = t.reply?.kind === 'final' ? 'final' : 'q';
    const dadLabel = t.reply?.kind === 'final' ? 'Dad \u00b7 plan' : 'Dad \u00b7 asking';
    const dadIcon = t.reply?.kind === 'final'
      ? icon('circle-check', { size:11 }) : icon('message-square-quote', { size:11 });
    return `<div class="turn-row" data-turn="${i}">
      <div class="msg you" data-seq="${t.askSeq || 0}">
        <div class="who">${esc(t.user || 'You')}</div>${esc(t.prompt || '')}</div>
      ${t.reply ? `<div class="msg dad ${dadCls}" data-seq="${t.reply.seq}">
        <div class="who">${dadIcon}${dadLabel}</div>${esc(t.reply.text)}</div>` : ''}
    </div>`;
  }).join('');
}

/* Reveal thread messages up to the cursor, and keep the newest one in view. */
function revealThread(lastSeq){
  let newest = null;
  document.querySelectorAll('#thread .msg').forEach(m => {
    const on = +m.dataset.seq <= lastSeq;
    m.classList.toggle('hidden', !on);
    m.classList.remove('now');
    if(on) newest = m;
  });
  if(newest){
    newest.classList.add('now');
    // scrollIntoView on the message keeps the exchange readable as it grows
    newest.scrollIntoView({ block:'nearest', behavior: timer ? 'smooth' : 'auto' });
  } else {
    $('thread').scrollTop = 0;
  }
}

// ----------------------------------------------------------------- ledger
async function loadLedger(){
  ledger = await (await fetch('/api/household')).json();
  $('tabs').innerHTML = Object.keys(ledger).map(c =>
    `<div class="tab${c===ledTab?' on':''}" data-c="${c}">` +
    icon(LEDGER_ICON[c] || 'scroll-text', { size:13 }) +
    `<span>${c}</span><span class="n">${ledger[c].length}</span></div>`).join('');
  $('tabs').onclick = e => {
    const t = e.target.closest('.tab'); if(!t) return;
    ledTab = t.dataset.c;
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x.dataset.c === ledTab));
    renderLedger();
  };
  $('rawtoggle').onclick = () => { ledRaw = !ledRaw; renderLedger(); };
  renderLedger();
}
// A category's `text` is not always what a person wants to read (usage and
// outcomes are the harness's own telemetry, translated server-side into
// `friendly`). Raw mode shows the record exactly as it sits on disk -- the
// same data already in hand, no second fetch -- for whoever wants nothing
// between them and the file.
function renderLedger(){
  const rows = (ledger[ledTab] || []).slice().reverse();
  $('rawtoggle').classList.toggle('on', ledRaw);
  $('led').innerHTML = rows.length
    ? rows.map(r => `<div class="row">${
        ledRaw ? '<span class="mono">' + esc(JSON.stringify(r)) + '</span>'
               : esc(r.friendly || r.text || JSON.stringify(r))
      }</div>`).join('')
    : '<div class="empty">Nothing filed under ' + esc(ledTab) + ' yet.</div>';
}

// ---------------------------------------------------------------- tracing
/* "Why it says that": the mechanical event a milestone was derived from. This
 * is the console's honesty check made clickable — no milestone exists without
 * a real event underneath it, and this shows which one. */
function showCause(causeSeq, msSeq){
  const c = bySeq[causeSeq], m = bySeq[msSeq];
  if(!c || !m) return;
  let what;
  if(c.kind === 'tool_result')
    what = `<code>${esc(c.name)}</code> returned <em>&ldquo;${esc((c.result||'').slice(0,180))}&rdquo;</em>`;
  else if(c.kind === 'plan')
    what = `Dad committed to <code>${(c.steps||[]).length} steps</code>: <em>${esc((c.steps||[]).join(' / '))}</em>`;
  else if(c.kind === 'controller')
    what = `Mom returned <code>${esc(c.action)}</code> on <code>${esc(c.name)}</code>. <em>${esc(c.reason||'')}</em>`;
  else if(c.kind === 'clarify')
    what = `Dad replied with no plan and no tool call, and asked: <em>&ldquo;${esc((c.text||'').slice(0,180))}&rdquo;</em>`;
  else if(c.kind === 'final')
    what = `<em>&ldquo;${esc((c.text||'').slice(0,180))}&rdquo;</em>`;
  else what = `<code>${esc(c.kind)}</code>`;
  $('cause').innerHTML = `<div class="lbl">Why it says that</div><div class="body">
    <strong>${esc(m.milestone.replace(/_/g,' ').toLowerCase())}</strong> was derived from
    event <code>seq ${c.seq}</code>. ${what}</div>`;
}
$('mlist').addEventListener('click', e => {
  const row = e.target.closest('.ms'); if(!row) return;
  document.querySelectorAll('.ms').forEach(r => r.classList.remove('sel'));
  row.classList.add('sel');
  showCause(+row.dataset.cause, +row.dataset.seq);
});
$('mlist').addEventListener('keydown', e => {
  if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); e.target.closest('.ms')?.click(); }
});

// ------------------------------------------------------------------- dock
function drawDock(toolState){
  $('dock').innerHTML = DOCK.map(([tool, label]) => {
    const st = toolState[tool];
    const cls = st === 'bad' ? 'bad' : st === 'gov' ? 'gov'
              : st === 'on' ? 'on' : st === 'run' ? 'run' : '';
    const word = st === 'bad' ? 'problem' : st === 'gov' ? 'held'
               : st === 'on' ? 'done' : st === 'run' ? 'running' : 'idle';
    // A running tool gets the spinner; everything else keeps its own glyph, so
    // a slot is recognisable before you read the word under it.
    const gl = st === 'run'
      ? icon('loader-circle', { size:13, cls:'spin' })
      : icon(TOOL_ICON[tool] || 'package-open', { size:13 });
    return `<div class="slot ${cls}">
      <div class="nm">${gl}<span>${esc(label)}</span></div>
      <div class="st">${word}</div><div class="bar"><i></i></div></div>`;
  }).join('');
}

// ----------------------------------------------------------------- render
/* The fold. Walk events[0, idx) and derive every panel from scratch.
 *
 * Two kinds of state live here and they reset at different times:
 *  - The HOUSE accumulates across the whole session. A propane tank found
 *    empty in turn two is still empty in turn four; that is true of the world.
 *  - The STAGE RAIL resets on every turn_start, because each turn is its own
 *    state machine in the harness (a fresh StageMachine per turn()). Without
 *    the reset, "delivered" from turn one would already show as done while
 *    turn two is still at "received".
 */
function render(){
  const st = blankState();
  const toolState = {};
  let stage = 'RECEIVED', seen = new Set(['RECEIVED']);
  const cons = [];
  let outcome = null, turnNo = 0, goalSet = false;
  // Real time and real weather, both taken from the journal, never assumed.
  st.hour = 12; st.when = ''; st.weather = null;

  EVENTS.slice(0, idx).forEach(e => {
    if(e.kind === 'turn_start'){
      turnNo++;
      if(e.ts){
        const d = new Date(e.ts * 1000);
        st.hour = d.getHours();
        st.when = d.toLocaleString(undefined, { weekday:'short', hour:'2-digit', minute:'2-digit' });
      }
      // The session's goal is the FIRST ask. Later turn_starts are the person
      // answering Dad's questions ("this weekend", "3 boys") — not new goals.
      if(!goalSet){
        $('goaltext').textContent = (e.user ? e.user + ': ' : '') + '\u201c' + (e.prompt||'') + '\u201d';
        goalSet = true;
      }
      stage = 'RECEIVED'; seen = new Set(['RECEIVED']); outcome = null;
      st.momRoom = null;
      st.dadSays = turnNo === 1 ? 'hmm, let me think' : 'okay...';
    }
    if(e.stage){ stage = e.stage; seen.add(e.stage); }

    if(e.kind === 'tool_call'){
      const room = ROOM_OF[e.name];
      if(room){ st.dadRoom = room; st.dadOut = false; }
      st.dadSays = DOING[e.name] || e.name;
      if(toolState[e.name] !== 'gov') toolState[e.name] = 'run';   // in flight

      if(e.name === 'load_skill'){
        const skill = (e.args && e.args.name) || '';
        const room2 = SKILL_ROOM[skill];
        if(room2){
          st.dadRoom = room2; st.dadOut = false;
          st.dadSays = SKILL_DOING[skill] || `pulling '${skill}'`;
          const key = '__' + skill;
          if(toolState[key] !== 'gov') toolState[key] = 'run';
        }
      }
      if(SENDS_DAD_OUT.has(e.name)) st.dadOut = true;   // gone until the result lands
    }

    if(e.kind === 'tool_result'){
      const room = ROOM_OF[e.name];
      if(e.name === 'check_weather'){
        const w = weatherFrom(e.result);
        if(w) st.weather = w;   // the sky answers only if Dad actually looked
      }
      // A held call still returns a result; don't let that erase the hold.
      if(toolState[e.name] !== 'gov') toolState[e.name] = e.problem ? 'bad' : 'on';
      if(room){
        st.roomStates[room] = e.problem ? 'trouble' : 'lit';
        st.details[room] = caption(e.result);
        st.dadRoom = room;
      }
      if(SENDS_DAD_OUT.has(e.name)) st.dadOut = false;   // he's back
      if(e.name === 'load_skill'){
        const skill = (e.args && e.args.name) || '';
        const room2 = SKILL_ROOM[skill];
        if(room2){
          st.roomStates[room2] = e.problem ? 'trouble' : 'lit';
          st.details[room2] = caption(e.result);
          st.dadRoom = room2;
          const key = '__' + skill;
          if(toolState[key] !== 'gov') toolState[key] = e.problem ? 'bad' : 'on';
        }
      }
      if(e.problem){
        const label = e.name.replace('check_','').replace(/_/g,' ');
        if(!cons.includes(label)) cons.push(label);
        st.dadSays = 'uh oh';
      }
    }

    if(e.kind === 'controller' && e.action !== 'allow'){
      const room = ROOM_OF[e.name];
      toolState[e.name] = 'gov';
      if(room){ st.roomStates[room] = 'governed'; st.momRoom = room; st.dadRoom = room; }
      st.momSays = e.action === 'deny' ? 'No.' : 'Rewriting that.';
      seen.add('GOVERNED');
    }

    // Dad handing the turn back with a question. He says it out loud in the
    // house, so a session that is all questions still visibly does something.
    if(e.kind === 'clarify'){
      st.dadSays = bubbleText(e.text);
      st.momRoom = null;
      seen.add('AWAITING_INPUT');
    }
    if(e.kind === 'final'){ st.dadSays = 'here is the plan'; st.momRoom = null; }
    if(e.kind === 'turn_end'){ outcome = e; (e.stage_history||[]).forEach(s => seen.add(s)); }
  });

  // Which rooms turned red on THIS frame? Those get the shake.
  const nowTrouble = new Set(Object.entries(st.roomStates).filter(([,v]) => v === 'trouble').map(([k]) => k));
  st.justBroke = [...nowTrouble].filter(r => !prevTrouble.has(r));
  prevTrouble = nowTrouble;

  $('houseWorld').innerHTML = drawWorld(st);
  placeDad(st);
  aimCamera(st);
  $('subtitle').textContent = st.dadOut ? 'out at the hardware store…' : (st.dadSays || '');
  drawDock(toolState);

  const totalTurns = EVENTS.filter(e => e.kind === 'turn_start').length;
  $('stagenow').textContent = (totalTurns > 1 && turnNo ? `turn ${turnNo} of ${totalTurns} \u00b7 ` : '')
                            + stage.toLowerCase().replace('_',' ');
  document.querySelectorAll('.stg').forEach(el => {
    const s = el.dataset.s; el.className = 'stg';
    if(seen.has(s)) el.classList.add('done');
    if(s === stage) el.classList.add('now');
    else if(s === 'BLOCKED' && seen.has(s)) el.classList.add('warn');
    else if(s === 'GOVERNED' && seen.has(s)) el.classList.add('gov');
    else if(s === 'AWAITING_INPUT' && seen.has(s)) el.classList.add('ask');
  });

  const lastSeq = idx > 0 ? EVENTS[idx-1].seq : 0;
  document.querySelectorAll('.ms').forEach(r =>
    r.classList.toggle('shown', +r.dataset.seq <= lastSeq));
  revealThread(lastSeq);

  $('constraints').innerHTML = cons.length
    ? 'constraints found &nbsp;' + cons.map(c => `<b>${esc(c)}</b>`).join(' &middot; ') : '';

  // Outcome pill. AWAITING gets its own look: a question is not a failure and
  // must never wear the red "blocked" style, which it did before this branch.
  const p = $('outcome');
  if(outcome){
    const o = outcome.outcome;
    p.textContent = o.replace(/_/g,' ').toLowerCase() + (outcome.governed_down ? ' · governed' : '');
    p.className = 'pill ' + (o === 'ACHIEVED' ? 'achieved' : o === 'PARTIAL' ? 'partial'
                           : o === 'AWAITING' ? 'awaiting' : 'blocked');
  } else { p.textContent = idx ? 'in progress' : 'not started'; p.className = 'pill'; }

  $('scrub').value = idx;
  $('count').textContent = idx + ' / ' + EVENTS.length;
}

/* Theater camera. In theater mode the house scales toward whichever room Dad
 * is in, and eases back out when he leaves for the store. Plain mode: no zoom. */
function aimCamera(st){
  const svg = $('house');
  if(!document.body.classList.contains('theater') || st.dadOut){
    svg.style.transform = ''; return;
  }
  const r = ROOM_BY_ID[st.dadRoom] || ROOM_BY_ID.hall;
  // At scale S the visible window is 1/S of the canvas, so the origin must
  // stay within [50/S, 100-50/S] percent or a room near the edge (the
  // driveway) zooms half off screen and cuts Dad in two.
  const S = 1.55, lo = 50 / S, hi = 100 - lo;
  const cl = v => Math.min(hi, Math.max(lo, v)).toFixed(1);
  const ox = cl((r.x + r.w/2) / W * 100), oy = cl((r.y + r.h/2) / H * 100);
  svg.style.transformOrigin = `${ox}% ${oy}%`;
  svg.style.transform = `scale(${S})`;
}

// ---------------------------------------------------------------- theater
/* Same events, same fold — just a bigger stage and a subtitle. Escape leaves. */
$('theater').onclick = () => { document.body.classList.toggle('theater'); render(); };
document.addEventListener('keydown', e => {
  if(e.key === 'Escape'){ document.body.classList.remove('theater'); render(); }
});

// -------------------------------------------------------------- transport
function stop(){ clearInterval(timer); timer = null; $('play').textContent = 'Play'; }
$('play').onclick = () => {
  if(timer){ stop(); return; }
  if(idx >= EVENTS.length) idx = 0;          // at the end: play from the top
  $('play').textContent = 'Pause';
  timer = setInterval(() => { idx++; render(); if(idx >= EVENTS.length) stop(); }, TICK_MS);
};
$('step').onclick  = () => { stop(); if(idx < EVENTS.length){ idx++; render(); } };
$('reset').onclick = () => { stop(); idx = 0; render(); };
$('scrub').oninput = e => { stop(); idx = +e.target.value; render(); };

// ------------------------------------------------------------------- live
/* Tail the journal. Reconnects with backoff, because `dadloop --console` gets
 * restarted and a dead socket would otherwise mean "live" silently stopped
 * being live. A turn beginning or ending is when the picture changes: a new
 * prompt in the thread, or an outcome to show. Refresh in place either way. */
let liveEverConnected = false;
function connectLive(delay = 1000){
  let ws;
  try{
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  }catch(_){ return; }
  ws.onopen = () => {
    delay = 1000;
    // A RE-connect means the server was restarted under an open tab: the page
    // may be showing a stale "could not reach" banner. Boot again so it heals
    // itself instead of waiting for someone to notice and hit refresh.
    if(liveEverConnected) boot({ keepCursor: true });
    liveEverConnected = true;
  };
  ws.onmessage = ev => {
    const e = JSON.parse(ev.data);
    if(e.kind === 'turn_start' || e.kind === 'turn_end') boot({ keepCursor: true });
  };
  ws.onclose = () => setTimeout(() => connectLive(Math.min(delay * 2, 15000)), delay);
}
connectLive();

boot();
