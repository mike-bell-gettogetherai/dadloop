# Two people, one Dad: shared work in dadloop

Status: implemented 2026-09-05. Section 9 lists what was deliberately left.
Author: Swami Chandrasekaran

## 1. The problem

Two people in a family use dadloop. Not two Dads: Dad is the harness's
persona, and the people talking to him are whoever lives in the house. They
need to see each other's work so the second person does not redo what the
first already did, and Dad needs to know both of them asked. This has to hold
whether they use it at the same time or hours apart, and single-user dadloop
must keep working exactly as it did.

Watching each other type in real time is not the point. Knowing what has
happened in the house is. Live rendering falls out of the design as a side
effect and is kept because it costs nothing.

## 2. What the multiplayer pattern actually teaches

Six things, taken from the way developer harnesses have moved to shared
sessions, translated to a household. Each maps to something in dadloop.

1. **The agent is the one who knows what everyone is working on.** Not a
   dashboard. Dad. If one person asks for the cookout plan and the other asks
   the same tonight, Dad says so and points back. In code: one shared
   conversation, and every message carries its speaker's name.
2. **Waiting is the handoff point.** When Dad pauses to ask a question, either
   person may answer. dadloop already derives that state (`clarify`,
   `AWAITING_INPUT`). Both people see it; whoever knows the answer types it.
3. **The record is the handoff.** What a person normally reconstructs for the
   next person (what failed, what was decided, what the agent learned) is what
   dadloop already derives as milestones. So the catch-up view is milestones
   by name, not a transcript and not a model-written summary.
4. **Adding context is just a turn.** The other person says what they know to
   Dad, attributed to them. Nothing special was built for it, on purpose.
5. **Attribution covers Dad acting alone.** The field on `turn_start` is who
   initiated the turn. Today that is a person. When Dad someday acts on a
   schedule, the value is Dad and nothing else changes.
6. **Zero configuration identity.** `DADLOOP_USER`, then the login name,
   overridable with `--as`. No accounts, no login, no config file.

Left behind: chat platforms as a surface, and multi-agent teams. There is one
Dad. Two agents would be a second house.

## 3. The shape

One Dad, one process, one conversation, one memory, one journal, one Mom.
Everyone talks to that Dad. The TUI becomes a way of talking to him rather
than the thing that contains him.

```
   dadloop --serve                    the house: one AgentLoop, one journal writer
        |
        |  JSON lines over TCP, stdlib only
        |
   +----+-----------+-----------+
   |                |           |
 dadloop          dadloop         dadloop --console
 --as swami       --as priya      (unchanged: reads the journal)
 (or: the first `dadloop` is itself the house, and the rest join it)
```

This is the "hub inversion" the handoff brief anticipated, with one
correction: the hub is Dad, not the console. Making the console the hub would
have turned the observer into the product. Making Dad the hub leaves every
existing piece in its existing role, and the console did not need to learn
anything except who asked.

## 4. Design rules

**Still one writer.** Turns queue in the house and run one at a time on one
thread. The journal's `seq` never sees two writers. Mom never answers two
people at once.

**Everyone sees every turn.** Each event fans out to every connected client as
it happens, tagged with who caused it. The other person's work appears in your
TUI drawn by the same code that draws your own. There is no second render
path.

**Derive, never ask.** Who asked is a field on the record. On every shared
turn Dad's prompt carries a session record built from the journal by
`stages.session_ledger`: who asked what, how it ended, the constraints found,
what he said. Whether a new ask duplicates an earlier one is then a comparison
against a list in front of him, not a memory of a transcript. The catch-up
view in the TUI is the same record as milestones. Nobody is asked to
summarise anything.

**The session is the unit, not the machine.** A joined TUI never reads the
house's disk. Memory arrives as a snapshot in `welcome` and in every
`turn_end`, served through `MemoryView`, which answers every read the rail
and admin screen make. Two terminals on one machine and two machines on one
network are the same case. On one machine, plain `dadloop` finds the running
house through `house.json` beside the memory and joins it, so two people never
end up with two Dads on the same files. A second `--serve` on the same memory
is refused for the same reason.

**Core stays small.** `AgentLoop` gained `user` on `turn()` and a `shared`
flag. That is the whole footprint under `dadloop/core/`. The transport is one
file, `dadloop/house.py`, that the single-process path never imports.

**Single-user mode is untouched.** No house, no flag, no prefix in the model's
transcript, no household note in the prompt. The only visible change: the
journal's `turn_start` now says who asked, so the console shows a name where
it said "You".

## 5. What changed, by file

| file | change |
|---|---|
| `core/agent.py` | `turn(text, user=...)`; `user` on `turn_start`; `default_user()`; `people` and `shared` on the loop; when shared, each user message is `name: text` and the system prompt names the household, carries the derived session record, and states the job (check the record; do not redo what another person already got) |
| `core/stages.py` | `session_ledger(events, session_id)` and `ledger_note(rows)`: the session record, pure functions over the journal |
| `house.py` (new) | `House`: accept clients, queue turns, run them serially on one thread, fan every event out with `by`/`user`/`turn_id` through per-client writer threads, keep the session's frames for late joiners, tell a waiting person whose request Dad is on, write `house.json` beside memory while running, refuse to start over a live house. `HouseClient`: the AgentLoop-shaped object the TUI holds when joined; blocks in `turn()` like the real one; relays other people's frames to `on_other`; fills `tracer.totals`, thermostat state and a `MemoryView` from `turn_end` frames. `find_house()`: discovery with liveness probe and stale-file cleanup |
| `tui.py` | the per-turn event handler is a factory (`_make_on_event`) so the other person's turn uses it too; `_house_frame` routes frames; `them` style for their asks; "EARLIER IN THIS HOUSE" catch-up from history, milestones by name; presence in the title bar and subtitle; a `waiting` status when Dad is on someone else's request; F6 declines in a joined TUI |
| `__main__.py` | plain `dadloop` joins the running house or opens one and joins it (`house.open_or_join`); `--solo`; `--serve [host:port]`; `--join [host:port]`; `--as NAME` |
| `console/server.py` | `user` in the turn index; `people` per session |
| `console/static/console.js` | thread shows the name; session list and thread header say who took part; goal line attributed |
| `demos.py` | demo 6: two people, one Dad |
| `tests/test_house.py` (new) | fourteen tests, section 7 |

Nothing in `core/controller.py`, `core/journal.py`, `core/tools.py`,
`core/memory.py`, `core/trace.py`.

## 6. Wire protocol

One JSON object per line. Written so a person can read it with `nc`.

```
client -> house   {"hello": "priya"}
                  {"say": "are we ready for the cookout?"}

house  -> client  {"kind": "welcome", "you": 2, "user": "priya",
                   "session_id": "...", "online": true, "model": "...",
                   "memory": {"root": "...", "entries": {"grievances": [...], ...}},
                   "people": ["swami", "priya"], "busy_with": null,
                   "history": [ ...turn frames so far... ]}
                  {"kind": "presence", "people": ["swami", "priya"]}
                  {"kind": "queued", "by": 2, "user": "priya", "behind": "swami"}
                  {"kind": "turn_start", "payload": "<prompt>", "by": 1,
                   "user": "swami", "turn_id": "..."}
                  {"kind": "tool_call", "payload": [...], "by": 1, ...}
                  {"kind": "turn_end", "payload": {"text": "...",
                   "milestones": [...], "totals": {...}, "state": {...},
                   "memory": {...snapshot...}}, ...}
```

Beside the memory, while the house runs:

```
house.json   {"host": "127.0.0.1", "port": 8760, "pid": 4242,
              "session_id": "...", "started": 1788612611.7}
```

Turn frames carry the nine event kinds `AgentLoop.turn()` already emits with
their payloads unchanged, plus `turn_start` and `turn_end`. `by` is the client
id from `welcome`; a client tells its own turns from everyone else's by
comparing it. Presence and queue notices are about the room and are not kept
in history; turn frames are the record and are.

## 7. Verification

`tests/test_house.py`, fourteen tests, standalone like the rest:

1. `turn_start` carries `user`; single-user mode shows the model the text as
   typed with no household note.
2. In a shared house every user message is prefixed with its speaker; the
   system prompt names the people, carries the derived session record (the
   earlier ask, its outcome, what Dad said) and excludes the turn being
   answered; the first shared turn has no record yet.
3. `session_ledger` is pure, scoped to the session, and `ledger_note` renders
   it.
4. The house fans out to a second client with attribution, keeps `seq`
   strictly increasing with both turns attributed, hands a late joiner the
   record (including totals), and the joiner's `MemoryView` matches the
   house's memory on every read, refreshes after a turn, and refuses writes.
5. Two people asking at once are serialised: the second is told whose request
   Dad is finishing, and each turn's events are contiguous in the journal.
6. The house is discoverable beside its memory while it runs, the file goes
   when it stops, a stale file is cleaned on probe, and a second house on the
   same memory is refused.
7. `parse_address` is forgiving.
8. Plain `dadloop` then `dadloop --as userX`, no `--serve`: the first opens
   the house, the second finds and joins it, each sees the other's presence
   and asks, one journal carries both names, and the house file goes when
   the owner quits.
9. A turn that raises (network, SDK) does not kill the house: everyone gets a
   `final` saying so and a `turn_end`, the next turn runs, and the error is
   in `house.log` beside the memory.
10. A clarifying reply (Dad asks a question, no tool work) renders in the TUI
    as `Dad · asks`, single-user and joined. It never had before; the first
    real two-terminal run on Windows found it.
11. A joined TUI shows the earlier turn by name with Dad's answer, draws the
   other person's live turn as a reasoning step, never disables your prompt
   while you watch, and shows who is present.
12. A fact injected mid-turn, proven against a scripted model that only
   changes its answer when the fact is actually present in what it's shown:
   fewer model calls, an answer reflecting the fact, journaled correctly.
13. A note with no turn running becomes an ordinary ask instead of being lost.
14. The note renders live, inline, attributed, in the TUI that's watching --
   through the same rendering path every other event uses.

Checked with two real `dadloop` processes in pseudo-terminals as well: title
bars showed the other person, each drew the other's ask, cleanup on quit.

Also run, not filed as a test: six clients, eighteen simultaneous asks; every
client received every frame, `seq` stayed strictly increasing, every turn's
events were contiguous, a late joiner got all eighteen, and a person who asked
and then disconnected still had the turn run under their name.

Pictures, from a real two-person journal produced through the house:
`docs/console-shared-house.png` (Mom's Console, both names in the thread),
`docs/tui-shared-house.png` (a third person joins and sees the catch-up),
`docs/tui-shared-house-live.png` (one person's turn drawing live in another's
TUI, prompt still open).

## 8. Using it

```bash
dadloop --as swami                   # first terminal: opens the house, first person in
dadloop --as priya                   # another terminal: finds it, joins
dadloop --console                    # optional: Mom's Console, unchanged
dadloop --serve                      # optional: a house with no terminal of its own
```

`dadloop` with no flags joins the house running for this machine's memory if
there is one, and otherwise opens one in its own process and joins it as the
first person, so the next `dadloop` lands in the same session. When the
terminal that opened the house quits, the house closes and other joined TUIs
say so; `--serve` is the house that outlives its opener. `--solo` is the
single-user TUI with no house. `--serve` binds `127.0.0.1:8760`; `dadloop --serve 0.0.0.0:8760`
lets another machine join with `dadloop --join host:8760`. The joined TUI is
the same on either machine. There is no auth (section 9). Without `--as`, you
are your login name.

## 9. Deliberately left

- **Auth.** A household tool on a home network. Named, not built.
- **Who Mom listens to.** Standing between the two people is symmetric here:
  either may answer a clarify, either may ask anything. Per-person policy is
  a future Mom change. The record already has `user` on every turn so she can
  rule on it later without a schema change.
- **Watcher presence in the console.** Presence is a fact about the room, not
  about Dad's work, so it is not journaled and the console does not show it.
  The console shows who took part, from the record.
- **Session lifetime.** A session is the life of the running house. With plain
  `dadloop` that is the life of the terminal that opened it; with `--serve` it
  is the server's. Restart and you start a new session. Memory and the journal
  persist regardless.
- **Self-improvement from a joined TUI.** The loop rewrites Dad's playbooks and
  belongs to the process that owns Dad. F6 says so and points at
  `dadloop --improve` on the house's machine.
- **Reconnect.** If the house goes away, a joined TUI says so and its next ask
  gets a plain message. It does not retry. Start the house and start the TUI.
- **Discovery across machines.** `house.json` is local. A second machine
  joins by address.

## 9a. Mid-turn: handing Dad a fact while he's still working (2026-09-05)

Section 9 originally deferred anything beyond turn-taking. This closes part of
that gap: while someone's turn is running, a second person can hand Dad
something they know, and it changes what he does before he answers, not
after -- the "add it directly, no copying the conversation" behaviour.

**Mechanism.** `AgentLoop.inject_fact(text, who)` accepts a fact only while a
tool-calling loop is actually in flight (`_accepting_facts`, opened when the
multi-step part of a turn starts, closed the moment it concludes). Accepted
facts are folded into the next message reporting tool results back to the
model -- the one safe point, since a message with `tool_use` blocks must be
followed by one with matching `tool_result` blocks, so a fact can only ride
along on that message, not arrive as one of its own. If nothing is running,
or the turn concludes before the fact is picked up, `inject_fact` returns
`False` and the house queues it as an ordinary ask instead, so nothing is
lost -- it just stops being a mid-turn addition.

**Wire.** A new client message, `{"note": text}`. The house tries
`inject_fact` on whichever turn is currently running; on success it
broadcasts `{"kind": "fact_added", "payload": {"from": ..., "text": ...},
"by": <cid of the turn owner>, "user": <turn owner>, "turn_id": ...}` -- tagged
to the *turn*, not the note-sender, so it arrives inline in the turn owner's
own live view (`_own`) and in every other watcher's view (`on_other`),
including the sender's own. `HouseClient.add_note()` is fire-and-forget: there
is nothing to block on, since the feedback the sender needs is just seeing
their own note appear, the same way everyone else sees it.

**TUI.** Pressing Enter while watching someone else's turn (`self._other is
not None`) sends a note instead of queuing a question. It renders as
`↳ name added: text` inline in the running turn, for the turn owner and every
watcher alike, through the same `_make_on_event` closure that already renders
everything else in a turn -- no second rendering path.

**What this doesn't do.** A turn that never calls a tool has no results
message for a fact to ride on, so a fact arriving during a single-shot reply
just becomes the next ordinary turn. Real thread and socket timing means a
fact can land on any of the turn's remaining tool-result messages, not
necessarily the very next one -- tested for exactly that: the guarantee is
"before this turn concludes," not "before the next model call specifically."

**Proof, not a demo of a mock.** Tested with a scripted model that only
changes its answer if the fact is actually present in what it's shown: fewer
model calls, an answer that reflects what was added, journaled with
`turn_id` and `caused_by` intact. `tests/test_house.py`:
`test_a_fact_added_mid_turn_changes_that_turns_own_outcome`,
`test_a_note_with_no_turn_running_becomes_an_ordinary_ask`,
`test_a_note_is_shown_live_in_the_watching_tui`.

## 10. Notes for whoever touches this next

- `AgentLoop._turn_id` is set before the first event fires, which is what lets
  the house stamp every frame with a `turn_id`. Do not move that assignment.
- `HouseClient.turn()` returns on the `turn_end` frame, not on `final`, because
  `trace` arrives after `final` and the TUI wants it.
- The TUI's `StatusLine` has a fixed id, so there is only ever one. When your
  own turn is queued and someone else's runs, the one line is shared and its
  label changes; see `_begin_other_turn` and `_finish_other_turn`.
- Duplicate-ask handling is derived. The facts (who asked, outcome, what was
  found, what Dad said) come from the journal every turn via
  `stages.session_ledger` and are placed in the system prompt with the
  instruction. The model's part is to read a short list. If it still misses,
  the next step is a lexical or embedding match on the record that flags the
  closest earlier ask explicitly; the record is already there to match
  against.
- `House` uses one lock for the client table, the history and the busy state,
  and per-client writer threads. Do not send on a client socket from anywhere
  but its writer; two `sendall`s from two threads can tear a JSON line.
- A failed turn is logged, with traceback, to `house.log` beside the memory.
  The TUI has no useful stderr, so when "nothing comes back" that file is the
  first place to look, then `house.json` for whether a house is up at all.
- The house writes `house.json` beside memory and removes it on `stop()` and on
  SIGTERM. `find_house()` treats a file with nothing listening as stale and
  removes it, so a crash never wedges the next start.
