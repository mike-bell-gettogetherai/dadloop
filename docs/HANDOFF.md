# Handoff brief

Author: Swami Chandrasekaran
Written: 2026-09-05, updated the same day after the Dadloop 3 session.
For: the next working session on dadloop, starting cold.

This document exists because the session that produced the current codebase ran
long enough that its own context was compacted several times. A fresh session
should start from this file plus the code, not from anyone's memory of what was
done. Everything below was checked against the working tree on the date above.

---

## 0. How to use this in a new session

Do these in order. Each step is one message or one action.

1. **Get the code in front of the assistant.** Upload `dadloop.zip` (the one
   delivered at the end of the previous session) or point it at the repo IF you
   have pushed. See section 1 on why that matters. Do not assume GitHub is
   current.

2. **First message, verbatim or close to it:**
   > Read `docs/HANDOFF.md` first, then `docs/observability-spec.md`. Run the
   > test suite and tell me the count. Then summarise what you think the next
   > initiative is, in your own words, before writing any code.

   The last clause is deliberate. It makes the assistant prove it understood
   section 7 before it touches anything.

3. **Confirm the baseline.** The assistant should report `19 test files,
   72 tests, all passing, pyflakes clean`, and that `pyproject.toml` and
   `dadloop/__init__.py` agree on the version in `CHANGELOG.md`'s latest
   entry. A version that hasn't moved despite real changes shipping is the
   same class of bug as a stale test count in this file: caught in review,
   caught nowhere else. If it reports anything else, stop and
   find out why before going further. Something was lost in transfer. (A fresh
   environment needs `pip install -e ".[console]"` first; that is not a
   regression.)

4. **Read `docs/collaboration-spec.md`.** Section 7 below is done; the spec
   says what was built and section 9 of it says what was left. Pick the next
   thing from there or from section 7b.

5. **Ask for a spec before implementation** for anything bigger than a fix.
   Same shape as `observability-spec.md` and `collaboration-spec.md`. That
   pattern has now worked twice: spec, react, build in the order the spec lists.

6. **Keep the working rules in section 4 in force.** Repeat them if the
   assistant drifts. It will, eventually.

---

## 1. Where the code actually is

The local working tree has **41 uncommitted files** relative to its last git
commit (`2acebb1 Create .env.example`). In other words: the entire body of work
described in section 3 (self-improvement, journal, stages, Mom's Console,
sessions, themes, the scene) exists only in the working copy and in the zips
delivered during the session. **If you clone GitHub, you get a repo from before
any of that.**

Before the next session, either:

- push the working tree (`git add -A && git commit && git push`), or
- treat the final `dadloop.zip` as the source of truth and upload it.

The brief assumes the second. Fix it whenever convenient.

---

## 2. Snapshot of the codebase

95 files in the package. 7,550 lines across the Python and JavaScript that
matter. 72 tests in 19 standalone files under `tests/`, all passing. `pyflakes`
clean across `dadloop/` and `console/`. All four JS files pass `node --check`.

### The harness (`dadloop/`)

| file | job |
|---|---|
| `core/agent.py` | `AgentLoop`. The loop. `turn(user_text, on_event=...)`. Emits nine event kinds (see below). Owns `session_id`, `journal`, `_messages`. |
| `core/controller.py` | Mom. `review()` is authority over tool calls (allow / deny / modify). `enforce_voice()` trims long replies quietly and raises no event. Keep those two separate. |
| `core/tools.py` | Twelve tools. A blocking result starts with `PROBLEM:` or `CONFLICT:`. Both prefixes matter. |
| `core/skills.py` + `skills/*.md` | Fifteen Markdown playbooks, loaded on demand. `hosting` composes three others. |
| `core/memory.py` | `SemanticMemory`. Append-only JSONL per category beside `~/.dadloop/memory/`. Categories: grievances, lessons, people, rulings, usage, outcomes. |
| `core/trace.py` | OpenTelemetry-style spans, tokens, cost, model vs tool latency. |
| `core/plan.py` | `parse_plan()` reads a numbered list into a checklist. Numbered lines only, by design. |
| `core/improve.py` | RSI scoring. `record_gate_outcome()`, `held_streak()`. Grounded signals only. |
| `core/improve_loop.py` | Propose, replay, gate. Replay agents have `journal = None` set for them. Do not remove that. |
| `core/journal.py` | Append-only turn journal beside memory. `seq` continues from the last event on disk. |
| `core/stages.py` | Derives stages and milestones from events. Pure functions. Never asks the model anything. |
| `theme.py` | Three palettes chosen by the clock (sunrise, workshop, porchlight). Same token names in all three. `DADLOOP_THEME=` pins one. |
| `scene.py` | The ASCII house for the launch page and the rail's live mini-house. Shares the room mapping with the console. |
| `tui.py` | The Textual TUI. Roughly 1,800 lines. F4 admin, F6 self-improvement. Draws the other person's turns when joined to a house. |
| `launch.py` | Landing page with a live prompt and the house scene. |
| `house.py` | The shared house. `House` runs one AgentLoop behind a TCP socket and fans events out; `HouseClient` is what a joined TUI holds. Stdlib only. Not core; single-process dadloop never imports it. |

### Event kinds `AgentLoop.turn()` emits

`thinking`, `plan`, `plan_step_done`, `tool_call`, `tool_result`, `controller`,
`clarify`, `final`, `trace`. Every journaled event also carries `session_id`,
`turn_id`, `seq`, `tier` (1 mechanical, 2 derived) and, for tier 2,
`caused_by_seq`. `turn_start` carries `user`: who asked.

`clarify` vs `final`: a text-only reply is `clarify` when the turn did no
observable work (no plan parsed, no tool called) AND the reply ends in `?`.
Otherwise it is `final`. Both conditions are read off the output. Neither asks
the model what it meant.

### Mom's Console (`console/`)

FastAPI backend, zero-build front end. Reads the journal and memory files;
imports nothing that can run a turn; exposes no write verbs (a test asserts
this).

Routes: `/api/meta`, `/api/turns`, `/api/turn/{id}`, `/api/sessions`,
`/api/session/{id}`, `/api/household`, `/ws` (live tail), `/`.

Front end, five files: `index.html`, `console.js` (the fold), `world.js` (the
pixel house), `sprites.js` (editable pixel maps), `icons.js` (inlined Lucide).
The whole view is a fold over an append-only log: given events and a cursor,
`render()` derives every panel. Live and replay are one code path.

Launch with `dadloop --console`. Optional dependency: `pip install -e ".[console]"`.

---

## 3. What was built, in the order it happened

Each of these is documented in the code and, where it matters, in a test.

1. **Self-improvement (RSI)**, `dadloop --improve` and F6. Scores skills on
   plan completion, tool errors, vetoes, cost. Waits for 4 turns before judging.
   Replays a rewrite against frozen cases; recommends promotion only past an
   ±8% margin. A human presses the key. Walls (constitution, policies, tools,
   loop, promotion) enforced in code. Held streak tracked; the loop tells you
   when it is stuck.
2. **Governance split.** Voice trimming stopped raising a governance event.
   Only real policy hits show as Mom acting.
3. **Turn journal** (`journal.py`) and **derived business state** (`stages.py`).
   Spec in `docs/observability-spec.md`.
4. **Mom's Console.** The house, the dock, milestones with "why it says that",
   the household ledger. Later: real-time sky from timestamps, weather from
   `check_weather`, walking Dad, grill smoke, room shake on a constraint,
   theater mode with a camera.
5. **Sessions and clarifying questions.** `session_id` per `AgentLoop`
   instance, `clarify` event kind, `AWAITING_INPUT` stage, `AWAITING` outcome.
   The console groups turns into sessions and shows the conversation thread.
   Play replays the whole session.
6. **Three TUI themes by the clock**, plus the launch scene and the rail's live
   mini-house.
7. **Console robustness.** Clean Ctrl-C, websocket reconnect with backoff,
   in-place live refresh that keeps the cursor, honest error banners.
8. **Two people, one Dad** (Dadloop 3 session). `dadloop --serve` and
   `dadloop --join --as <name>`. `user` on every turn; Dad told who is
   speaking when the house is shared; the other person's turns draw live in
   your TUI; a late joiner sees the record as milestones by name; the console
   shows names. Spec: `docs/collaboration-spec.md`.

---

## 4. Working rules that held up

These are not preferences. Each one prevented a real bug or a real regression
during the session.

- **Derive, never ask.** Business-level state comes from observable facts. The
  model is never asked how it is doing. Applies to RSI, stages, clarify.
- **Tests are standalone scripts.** `python3 tests/test_x.py`, each with an
  `if __name__ == "__main__"` runner. No pytest. Run all with a for loop.
- **Run the whole suite after every change**, and pyflakes on `dadloop/` and
  `console/`, and `node --check` on every JS file.
- **Test against real data, not the logic on paper.** Two of the worst bugs
  (the missed `CONFLICT:` prefix, the replay agents polluting the journal) were
  only visible when the console rendered a real journal.
- **Screenshot before declaring UI done.** Playwright for the console,
  `app.save_screenshot()` plus cairosvg for the TUI. Look at the picture.
- **File headers**: line 1 `Author: Swami Chandrasekaran`, line 2
  `Last Modified: YYYY-MM-DD`, line 3 `Purpose:`. Bump the date on touched files.
- **No em dashes in anything published**: README, docs, commit messages,
  LinkedIn copy. Code comments are exempt but avoid them anyway.
- **Do not overcomplicate dadloop.** Its main virtue is that a reader can get
  the whole harness from six files. Every addition is weighed against that.
  Mom's Console is a separate subsystem for exactly this reason.
- **Tests must not write to the real journal or memory.** Use a temp
  `SemanticMemory(root)`. The journal lives beside memory, so a temp memory
  gives a temp journal for free. `SemanticMemory` wants a `Path`, not a str.
- **Single-user mode is the default and stays untouched.** Anything for the
  shared house lives in `house.py` and behind `dad.shared`; the core loop must
  read exactly as before when that flag is off.

---

## 5. Gotchas learned the hard way

Each one cost real time. Read this list before debugging anything.

- **Textual reserves `self._running`** on every message pump. Naming your own
  flag that way silently makes every action a no-op after mount. Use another
  name.
- **A worker started from inside a pushed Screen does not schedule under
  `run_test`**, and `call_from_thread` from a bare thread does not marshal
  there either. The RSI screen runs its loop inline for this reason.
- **`docs/architecture.md` and the README both stated stale counts** more than
  once. Grep the code for the number before writing it in prose.
- **`Journal._seq` used to restart at 0 per process.** Fixed to continue from
  disk. Two concurrent writers would still collide; see section 7.
- **RSI replay agents built with a bare `AgentLoop()` inherit the default
  memory and therefore the real journal.** `_score_body_on_cases` now sets
  `agent.journal = None`. A test pins it.
- **In the sandbox, a background server dies when the tool call that started
  it returns.** Start the server and run the browser test in the same shell
  invocation. And never `pkill -f` a pattern that appears in your own command
  line; it kills the shell running the test.
- **The tool harness has a hard wall-clock cap around 30 seconds.** Keep
  Playwright waits short.
- **`min-width: 0` on grid items.** The dock's slots have a `min-width`, and
  grid items default to `min-width: auto`, so the column stretched the page
  instead of scrolling. That was the "had to zoom to 67%" report.
- **`CancelledError` is a `BaseException`.** `except Exception` does not catch
  it. That was the Ctrl-C traceback.
- **`call_from_thread` from a bare thread does work in a running app**, and it
  worked under `run_test` too for the house client's reader thread in
  `tests/test_house.py`. The earlier note about workers inside pushed Screens
  still stands; that is a different case.
- **`StatusLine` has a fixed widget id**, so two cannot be mounted at once.
  The shared house reuses the one line and changes its label.
- **The TUI never rendered `clarify` events** from the day they were added
  (initiative 5) until 2026-09-05. Any reply where Dad did no tool work and
  ended with a question mark vanished from the canvas, in single-user mode
  too. Found by the first real Windows run: three asks about a winter trip,
  three traces, no replies. Every screenshot until then had used tool calls.
  When you add an event kind, grep every consumer for the old kind it most
  resembles and add the new one there too; and screenshot a turn that uses
  no tools.

---

## 6. Known gaps, deliberately left

- `TRADEOFF_MADE` is the weakest derivation rule (fires only when a stated plan
  was partly done). Documented as such in the spec.
- The clarify heuristic will misclassify a genuine question that does not end
  in `?`. Accepted; the alternative was asking the model.
- No OpenTelemetry exporter. Decided against; not what dadloop is for.
- No auth. The house binds loopback by default; `--serve 0.0.0.0:8760` opens
  it to the network, with no login. Named in the spec, not built.
- Multi-turn goals are not modelled across sessions.
- A joined TUI does not reconnect if the house goes away; it says so.

---

## 7. Two people, one Dad: done

Built in the Dadloop 3 session. Read `docs/collaboration-spec.md`; it
supersedes the rest of this section, which is kept as the record of how the
problem looked before it was solved. The one thing that changed in the
analysis: the hub is Dad (`dadloop --serve`), not the console. The console
stayed a reader and only learned who asked.

Two decisions taken during the build, in case they need revisiting:

- The two people are equals. Either may answer a clarify; either may ask
  anything. Mom does not distinguish them yet. `user` is on every turn so she
  can later.
- Duplicate-ask handling is derived: `stages.session_ledger` builds the
  session record from the journal every turn and it goes into Dad's system
  prompt with the instruction. The model reads a list; it does not have to
  remember a transcript.
- Mom's Console's Household Ledger now reads all six memory categories, not
  four: `usage` and `outcomes` (the harness's own telemetry) get a translated
  `friendly` line per row (`console/server.py:_friendly`), and a raw toggle on
  the card shows any category exactly as written to disk, reusing the same
  `/api/household` fetch rather than a second endpoint.
- A second person can hand Dad a fact while he's mid-turn (not just take
  turns): `AgentLoop.inject_fact()`, `{"note": ...}` over the wire, renders as
  `↳ name added: ...` inline in whoever is watching. See
  `collaboration-spec.md` section 9a. Proven with a scripted model that only
  changes its answer when the fact is actually present in what it's shown --
  not asserted from a mock that always says yes.
- The session is the unit, not the machine: joined clients get memory as a
  snapshot (`MemoryView`), and plain `dadloop` opens a house if none is
  running or joins the one that is (`house.open_or_join`, via `house.json`
  beside memory). A second house on one memory is refused. First real-use
  report was exactly this: `dadloop` then `dadloop --as userX` produced two
  Dads; that is why plain `dadloop` is now itself the house.

## 7a. The original framing, for the record

The stated direction: **multi-user collaboration in dadloop.** Two people using
and collaborating in the same household. This is not about importing any other
product's design. It is about what it means for two humans to direct and
observe one agent under one governance layer.

### Why this is a core change, not a feature

Every assumption below is baked into the code today:

- **One process is one conversation.** `_messages` (the model's context) lives
  inside one `AgentLoop` in one process. Two people need one shared context,
  which means one agent process serving two clients.
- **`session_id` is minted per instance.** There is no way to join a session.
- **Journal `seq` is safe for one writer.** Two TUIs on one journal will
  collide. Either a single writer owns the file, or writes are serialised.
- **There is no identity anywhere.** The thread says "You".
- **Governance is single-party.** Mom holds a call; today one person answers.
  With two: who may approve? Only the asker? Either? What if the two people
  give Dad conflicting instructions? This is the genuinely new question, and it
  fits the household metaphor exactly. It is probably the most interesting part
  and should get its own section in the spec.

### The likely architecture

The console server becomes the hub. It already owns the journal, runs FastAPI,
and speaks websockets. The TUI becomes a client of it. That inverts the current
relationship (TUI is primary, console reads), and should be named as such in
the spec.

What already helps: the journal is append-only and multi-reader; the console is
already a second surface over the same data; sessions exist; the stage machine
is per turn and does not care who asked.

### The one open question

**Who are the two people?** Two parents with equal standing? A parent and a
child with different permissions? The answer decides whether identity is
symmetric and whether governance is per-person. Decide this before the spec.

### Suggested first steps, in order (all done)

1. Write `docs/collaboration-spec.md`. Done, rewritten to what shipped.
2. Add `user` to `turn_start` and to the thread rendering. Done.
3. Move `AgentLoop` behind the hub for the shared-context case, keeping the
   single-process path working. Done: `house.py`, Dad as the hub.
4. Concurrency and journal ownership. Done: turns serialise in the house, one
   writer, tested.

## 7b. What is left, and what might come next

From `collaboration-spec.md` section 9: auth, Mom telling the two people
apart, session lifetime across restarts of the house, reconnect. None is
urgent. If the shared house gets real use, the first thing to learn is whether
the derived session record in the prompt is enough for Dad to catch a repeated
ask every time; if not, the next step is an explicit closest-match flag on the
record, which is already built each turn.

---

## 8. Verification commands

```bash
# baseline (expect 19 files, 0 failed)
for t in tests/test_*.py; do python3 "$t" >/dev/null 2>&1 && echo "ok  $t" || echo "FAIL $t"; done

# lint
python3 -m pyflakes dadloop/ console/
for j in console/static/*.js; do node --check "$j"; done

# see it
dadloop                 # TUI; DADLOOP_THEME=porchlight dadloop to pin a theme
dadloop --console       # Mom's Console at http://127.0.0.1:8765
dadloop --improve       # the self-improvement loop from the command line
dadloop --as swami      # first terminal opens the house
dadloop --as priya      # any other terminal on this machine joins it
dadloop --serve         # a house with no terminal of its own
dadloop --solo          # single-user, no house
```

## 9. Screenshots on disk

`docs/tui-themes.png`, `docs/tui-launch-scenes.png`, `docs/tui-rail-house.png`,
`docs/console-night-rain.png`, `docs/console-dusk-storm.png`,
`docs/console-theater.png`, `docs/moms-console.png`. Regenerate any of them
before publishing; several predate the final round of changes. New and current
as of 2026-09-05: `docs/console-shared-house.png`, `docs/tui-shared-house.png`,
`docs/tui-shared-house-live.png`.
