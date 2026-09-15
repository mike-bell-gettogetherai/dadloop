# Business observability for dadloop

Status: draft spec, not yet implemented.
Author: Swami Chandrasekaran

## 1. What already exists

Worth being precise, because dadloop is not starting from zero here.

**Tracing.** `core/trace.py` is an OpenTelemetry-style tracer. Spans nest, and a
root span closes with tokens in and out, estimated cost, and the split between
model latency and tool latency. `SessionTotals` aggregates across turns.

**An event stream.** `AgentLoop.turn()` emits eight kinds of event through an
`on_event` callback: `plan`, `plan_step_done`, `thinking`, `tool_call`,
`tool_result`, `controller`, `trace`, `final`. The TUI is one consumer.

**Per-turn outcome records.** `improve.OutcomeRecord` persists one row per turn
that loaded a skill: plan steps committed and completed, tool call count, tool
error count, veto count, tokens, cost, and the originating prompt.

**Durable memory.** Six append-only JSONL files: grievances, lessons, people,
rulings, usage, outcomes.

## 2. What is missing

**The stream is ephemeral.** `on_event` is an in-process callback. The TUI
renders each event and drops it. Nothing about the sequence of a turn survives
the process. `OutcomeRecord` keeps counts, not sequence: it records that four
tools ran, never which four, in what order, with what arguments, or what came
back.

**The events are mechanical, not business-level.** "Tool called" and "step done"
describe machinery. They do not describe work. Nothing in dadloop currently
expresses:

- what goal a turn is pursuing
- what stage that goal is in
- what constraints have been discovered
- what tradeoff was made and what lost
- whether the goal was achieved, partially met, blocked, or refused

There is no goal object and no state machine anywhere in the codebase. `Plan` is
the closest thing and it is a flat checklist of steps.

## 3. Design principles

**Derive, do not ask.** Business-level state is computed deterministically from
mechanical events. The model is never asked "what stage are you in" or "did that
go well." This is the same principle the RSI scorer already enforces: the moment
the model rates its own work, the measurement is gameable. Every stage
transition in section 5 is triggered by an observable fact.

**Append-only, never mutate.** The journal is a log, not a state file. Current
state is a fold over the log. This gives replay for free and makes the format
safe for multiple readers.

**One writer, many readers.** dadloop writes the journal. It knows nothing about
who reads it. The console imports no dadloop code.

**Additive to core.** No existing event kind changes shape. No existing consumer
breaks. The TUI keeps working untouched.

## 4. The two tiers

Tier 1 is the mechanical stream that exists today, now persisted rather than
dropped.

Tier 2 is derived business state, computed from tier 1 by a rules module. Both
tiers land in the same journal so a reader can drill from a milestone down to the
tool call that caused it.

## 5. The turn state machine

A turn is a goal-directed episode. Stages, with the observable fact that
triggers each transition:

| stage | meaning | entered when |
|---|---|---|
| `RECEIVED` | user intent has arrived, nothing done yet | `turn()` called |
| `FRAMING` | Dad has committed to an approach | `plan` event with a non-empty plan |
| `GATHERING` | establishing world state | first `tool_call` |
| `BLOCKED` | a discovered fact closes the obvious path | `tool_result` flagged as a problem |
| `REPLANNING` | adapting after a block | a `tool_call` that was not in the stated plan, while `BLOCKED` |
| `GOVERNED` | Mom intervened on an action | `controller` event with action `deny` or `modify` |
| `RESOLVING` | committing to an answer | model returns text with no tool calls |
| `DELIVERED` | answer handed to the user | `final` event |

`BLOCKED`, `REPLANNING` and `GOVERNED` are passes through, not terminals. A turn
can enter and leave `BLOCKED` several times. The journal records every entry, so
"how many times did this turn hit a wall" is answerable.

Terminal outcome is classified at `DELIVERED`, again from facts already on hand:

| outcome | rule |
|---|---|
| `ACHIEVED` | every stated plan step completed, no unresolved block |
| `PARTIAL` | some steps completed, at least one block never resolved |
| `BLOCKED_OUT` | zero plan steps completed |
| `GOVERNED_DOWN` | delivered, but a governance veto changed what shipped |

Note `GOVERNED_DOWN` can co-occur with `ACHIEVED`; outcome carries a flag rather
than being mutually exclusive.

## 6. Milestones

A milestone is a business-meaningful moment worth showing on a timeline. Derived,
never asked for.

| milestone | derived from |
|---|---|
| `GOAL_FRAMED` | the plan Dad stated, with step count |
| `WORLD_CHECKED` | a tool reported a fact about the world |
| `CONSTRAINT_FOUND` | a tool result that closes an option (empty propane, store closed, budget short) |
| `CONSTRAINT_CLEARED` | a later successful call on the same subject |
| `SKILL_ASSEMBLED` | `load_skill`, including skills a skill pulls in |
| `AUTHORITY_APPLIED` | Mom denied or rewrote a call |
| `TRADEOFF_MADE` | a plan step abandoned while another completed |
| `GOAL_SETTLED` | the final answer |

`CONSTRAINT_FOUND` is the load-bearing one. It is what turns a tool log into a
story: the propane was empty, then the store was closed, and those two facts
together are why the answer looks the way it does.

Detection is a small classifier on tool results, in code, driven by the tool
contract rather than by prose sniffing. Tools already distinguish reporting a
fact from reporting a problem, so the rule reads that signal rather than guessing
from text.

## 7. Journal format

One file, append-only JSONL, at `~/.dadloop/journal.jsonl` (configurable). One
event per line.

```json
{
  "ts": 1755301234.812,
  "turn_id": "2026-08-15T17:04:11Z-a91c",
  "seq": 7,
  "tier": 1,
  "kind": "tool_result",
  "name": "check_grill",
  "args": {},
  "result": "propane empty",
  "problem": true,
  "ms": 210
}
```

```json
{
  "ts": 1755301234.9,
  "turn_id": "2026-08-15T17:04:11Z-a91c",
  "seq": 8,
  "tier": 2,
  "kind": "milestone",
  "milestone": "CONSTRAINT_FOUND",
  "subject": "propane",
  "detail": "tank empty",
  "caused_by_seq": 7
}
```

Every tier 2 event carries `caused_by_seq`, so the console can always answer "why
does it say that" by pointing at the mechanical event underneath. Nothing in tier
2 is unfalsifiable.

Turn boundaries are their own events (`turn_start`, `turn_end`) carrying the user
prompt, final outcome, totals, and stage history.

Rotation: size-capped with numbered rollover. The console reads the newest file
and can walk back.

## 8. Changes to core

Deliberately small. Three new things, no changes to existing behavior.

1. `core/journal.py`. A `Journal` class with `write(event)` and rotation. Roughly
   60 lines.
2. `core/stages.py`. The derivation rules from sections 5 and 6. Pure functions
   over events, no I/O, so it is directly unit-testable. Roughly 150 lines.
3. A wiring change in `AgentLoop.turn()`. The existing `emit()` gains a second
   consumer: every event goes to the journal, and to the stage machine, which may
   emit tier 2 events back into the journal. The `on_event` callback signature
   does not change, so the TUI is unaffected.

Optionally, the TUI gains a stage indicator in the title bar, since it now has
the data. Not required.

**Explicitly out of scope for core:** aggregation, querying, retention policy,
serving. The core writes a log and stops. Everything else belongs to the reader.

## 9. The console

A standalone app in its own repo. Python backend, rich front end. Reads the
journal and the memory JSONL files. Imports nothing from dadloop.

Framing: this is **Mom's console**. She governs the home and this is where she
watches it. That framing is not decoration, it decides the information
architecture: the primary question is "what is happening in this house and what
has Dad done," not "what is the agent's token count."

### 9.1 Backend

FastAPI. Tails the journal, folds events into current state, serves a websocket
for live and a REST endpoint for history and replay. Replay is a first-class
mode: given a `turn_id`, stream its events at original pacing or scrubbable.

### 9.2 Screens

**Live floor.** The house view. Rooms map to tools: kitchen is `check_pantry`,
backyard is `check_grill`, garage is `find_tool`, thermostat is the hallway,
front door is `check_hardware_store` and `web_search`. A room lights when its
tool fires, holds the result, and turns to the trouble color on
`CONSTRAINT_FOUND`. Mom stands at the doorway of any room a policy has blocked.

Critically, this view is driven entirely by the journal, so it replays.

**Timeline.** The turn as a horizontal band of stages, with milestone markers
pinned to it. Click a milestone, see the mechanical event that caused it. This is
where `caused_by_seq` pays off.

**Household ledger.** The memory files given real space, which the TUI rail
cannot afford: grievances accumulating over months, which rulings keep firing,
people, lessons. This is the part that stays useful after the novelty of the
house view fades. All six memory categories are readable here, not just the
four prose ones -- `usage` and `outcomes` are the harness's own telemetry
(skill loads, RSI gate results, per-turn grounded outcomes) rather than
something written in plain language, so the console translates each into a
`friendly` line while leaving the record itself untouched. A raw toggle on the
card switches any tab to exactly what is on disk -- the same fetch, no second
endpoint, nothing hidden by the translation.

**Skill health.** Grounded scores over time, RSI gate history including held
streaks, which playbooks are drifting.

### 9.3 Wireframe, live floor

```
+--------------------------------------------------------------+
|  MOM'S CONSOLE          turn 14  ·  GATHERING  ·  live        |
+---------------------------+----------------------------------+
|                           |  STAGE                           |
|      [ house floor ]      |  received > framing > gathering   |
|                           |                                   |
|   kitchen    backyard     |  MILESTONES                      |
|   [lit]      [trouble]    |  goal framed      4 steps        |
|                           |  world checked    pantry         |
|   garage     hallway      |  constraint found propane empty  |
|                           |                                   |
|   front door [Mom]        |  NOW                             |
|                           |  check_hardware_store  210ms     |
+---------------------------+----------------------------------+
|  goal: twelve people saturday, forty bucks                    |
|  constraints: budget $40 · propane empty · store closed       |
+--------------------------------------------------------------+
```

## 10. Open questions

1. Room mapping for the four tools with no physical location (`remember`,
   `recall`, `load_skill`, `tell_joke`). Options: a study for memory tools, or
   keep them off the map and show them only on the timeline.
2. Whether `TRADEOFF_MADE` is reliably derivable or needs a tool-level signal.
   Currently the weakest rule in section 6.
3. Multi-turn goals. The state machine above is per turn. A cookout planned
   across three sessions is a real dadloop scenario and this spec does not model
   it yet.

## 11. Build order

1. `journal.py` plus wiring, with a test that a full turn round-trips to disk.
2. `stages.py` with unit tests over recorded event fixtures. No UI yet.
3. Verify by replaying a real cookout turn from the journal in the terminal.
4. Console backend, tailing and folding.
5. Console front end, timeline first, house view second.

Steps 1 to 3 are worth doing regardless of whether the console ever ships. A
persisted, replayable turn journal makes dadloop easier to debug on its own.
