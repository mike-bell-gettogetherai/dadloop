"""Author: Swami Chandrasekaran
Last Modified: 2026-09-05
Purpose: Derive business-level stages and milestones from mechanical events.

The harness already says what it is doing mechanically: a tool was called, a plan
step finished, Mom denied something. That is machinery, not work. This module
turns it into work: what goal is being pursued, what stage it is in, what
constraint just closed a door, what got traded away, and how it ended.

Everything here is DERIVED, never asked. The model is never consulted about what
stage it is in or whether a turn went well, for the same reason the RSI scorer
refuses to grade on "did the answer read well": the moment the model narrates its
own progress, the narration is gameable and the console becomes theatre. Every
transition below fires on an observable fact — a tool returned a problem, a
policy denied a call, a stated step completed.

Consequently this module is pure. It holds no I/O and no clock beyond what it is
handed. Feed it events, get events back. That makes it directly testable against
recorded fixtures, which is the only way to trust a derivation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- stages
RECEIVED = "RECEIVED"
FRAMING = "FRAMING"
GATHERING = "GATHERING"
BLOCKED = "BLOCKED"
REPLANNING = "REPLANNING"
GOVERNED = "GOVERNED"
RESOLVING = "RESOLVING"
AWAITING_INPUT = "AWAITING_INPUT"
DELIVERED = "DELIVERED"

# ------------------------------------------------------------ milestones
GOAL_FRAMED = "GOAL_FRAMED"
WORLD_CHECKED = "WORLD_CHECKED"
CONSTRAINT_FOUND = "CONSTRAINT_FOUND"
CONSTRAINT_CLEARED = "CONSTRAINT_CLEARED"
SKILL_ASSEMBLED = "SKILL_ASSEMBLED"
AUTHORITY_APPLIED = "AUTHORITY_APPLIED"
TRADEOFF_MADE = "TRADEOFF_MADE"
CLARIFICATION_ASKED = "CLARIFICATION_ASKED"
GOAL_SETTLED = "GOAL_SETTLED"

# --------------------------------------------------------------- outcomes
ACHIEVED = "ACHIEVED"
PARTIAL = "PARTIAL"
BLOCKED_OUT = "BLOCKED_OUT"
# Not success or failure — the turn did no work because it correctly determined
# it did not yet have enough to work with. Kept distinct from ACHIEVED so a
# reader never mistakes "asked a question" for "finished the job", which is
# exactly the false signal that motivated adding this outcome at all.
AWAITING = "AWAITING"

# Tools that report on the world rather than acting on it. A result from one of
# these is a fact about the house, which is what WORLD_CHECKED marks.
_CHECK_TOOLS = {
    "check_weather", "check_grill", "check_pantry",
    "check_hardware_store", "check_wallet", "find_tool", "web_search",
}

# The subject a constraint is about, keyed by the tool that found it. Lets the
# console say "propane" instead of "check_grill", and lets CONSTRAINT_CLEARED
# match a later success against the same subject.
_SUBJECT = {
    "check_grill": "grill",
    "check_pantry": "pantry",
    "check_hardware_store": "hardware store",
    "check_wallet": "budget",
    "check_weather": "weather",
    "find_tool": "tools",
}


def is_problem(result) -> bool:
    """Did this tool result close a door?

    Reads the conventions already in the codebase rather than inventing a third.
    Tools mark a blocking fact with a PROBLEM or CONFLICT prefix (an empty
    propane tank, a closed store), and the agent loop already treats results
    starting with error / no skill / [blocked as failures when it counts
    tool_errors for RSI scoring.
    """
    if not isinstance(result, str):
        return False
    head = result.lstrip().lower()
    return (head.startswith(("problem", "conflict"))
            or head.startswith(("error", "no skill", "[blocked")))


@dataclass
class StageMachine:
    """Folds one turn's mechanical events into stages and milestones.

    Call `observe(kind, payload)` for each event as it happens; it returns a list
    of derived events to journal (usually empty). Call `finish()` at the end of
    the turn for the closing classification.

    Scope is exactly one turn. A fresh machine is built per `turn()` call, so a
    multi-turn exchange (question, short answer, question, plan) is several
    machines run in sequence, tied together by the session_id the harness stamps
    on every event. That is what lets a reader group them back into one
    conversation while still classifying each turn on its own evidence.

    Two terminal shapes matter and must never be confused. A turn that did work
    and concluded ends in RESOLVING → DELIVERED with an ACHIEVED / PARTIAL /
    BLOCKED_OUT outcome. A turn that did no work and handed a question back to
    the person ends in AWAITING_INPUT → DELIVERED with the AWAITING outcome and
    no GOAL_SETTLED milestone at all. Earlier, "when is this happening?" and
    "here is the plan" both landed as ACHIEVED, which is a lie the console then
    repeated.
    """

    stage: str = RECEIVED
    history: list[str] = field(default_factory=lambda: [RECEIVED])

    _plan: list[str] = field(default_factory=list)
    _steps_done: int = 0
    _tool_calls: int = 0
    _vetoes: int = 0
    _open_constraints: dict = field(default_factory=dict)   # subject -> detail
    _cleared: list = field(default_factory=list)
    _governed_down: bool = False
    _saw_unplanned_call: bool = False
    _clarifying: bool = False

    # -- internal --------------------------------------------------------
    def _to(self, stage: str) -> None:
        if stage != self.stage:
            self.stage = stage
            self.history.append(stage)

    def _ms(self, milestone: str, **extra) -> dict:
        return {"kind": "milestone", "milestone": milestone, "stage": self.stage,
                **extra}

    # -- the fold --------------------------------------------------------
    def observe(self, kind: str, payload) -> list[dict]:
        """One mechanical event in, zero or more derived events out."""
        out: list[dict] = []

        if kind == "plan":
            steps = list(payload or [])
            if steps:
                self._plan = steps
                self._to(FRAMING)
                out.append(self._ms(GOAL_FRAMED, steps=len(steps)))

        elif kind == "plan_step_done":
            self._steps_done += 1
            # A call that was never in the stated plan, made while a door is
            # shut, is the signature of adapting rather than executing.
            planned = payload[2] if len(payload) > 2 else True
            if not planned:
                self._saw_unplanned_call = True
                if self._open_constraints:
                    self._to(REPLANNING)

        elif kind == "tool_call":
            self._tool_calls += 1
            if self.stage in (RECEIVED, FRAMING):
                self._to(GATHERING)

        elif kind == "tool_result":
            name = payload[0] if payload else ""
            result = payload[1] if len(payload) > 1 else ""
            subject = _SUBJECT.get(name, name)

            if name == "load_skill" and not is_problem(result):
                out.append(self._ms(SKILL_ASSEMBLED, subject=subject,
                                    detail=str(result)[:120]))
            elif is_problem(result):
                self._open_constraints[subject] = str(result)[:160]
                self._to(BLOCKED)
                out.append(self._ms(CONSTRAINT_FOUND, subject=subject,
                                    detail=str(result)[:160]))
            elif name in _CHECK_TOOLS:
                out.append(self._ms(WORLD_CHECKED, subject=subject,
                                    detail=str(result)[:160]))
                # A clean read on a subject that was previously blocked means
                # the door reopened.
                if subject in self._open_constraints:
                    self._open_constraints.pop(subject)
                    self._cleared.append(subject)
                    out.append(self._ms(CONSTRAINT_CLEARED, subject=subject))
                    self._to(GATHERING if not self._open_constraints else BLOCKED)

        elif kind == "controller":
            name = payload[0] if payload else ""
            action = payload[1] if len(payload) > 1 else ""
            reason = payload[2] if len(payload) > 2 else ""
            if action in ("deny", "modify"):
                self._vetoes += 1
                self._governed_down = True
                self._to(GOVERNED)
                out.append(self._ms(AUTHORITY_APPLIED, subject=name,
                                    action=action, detail=str(reason)[:160]))

        elif kind == "final":
            self._to(RESOLVING)

        elif kind == "clarify":
            # No plan, no tool call yet, and the model handed the question back
            # to the person instead — a distinct shape, not a smaller version of
            # a completed turn.
            self._clarifying = True
            self._to(AWAITING_INPUT)
            out.append(self._ms(CLARIFICATION_ASKED, detail=str(payload)[:200]))

        return out

    def finish(self, *, final_text: str = "") -> list[dict]:
        """Close the turn: the settling milestone, any tradeoff, and the outcome."""
        out: list[dict] = []
        planned = len(self._plan)
        done = min(self._steps_done, planned) if planned else self._steps_done

        if self._clarifying:
            # No GOAL_SETTLED here — nothing settled. The turn's entire content
            # is already on record as the CLARIFICATION_ASKED milestone above.
            self._to(DELIVERED)
            out.append({
                "kind": "turn_end", "outcome": AWAITING,
                "governed_down": self._governed_down,
                "stage_history": list(self.history),
                "plan_steps": 0, "plan_done": 0,
                "tool_calls": self._tool_calls, "vetoes": self._vetoes,
                "constraints_open": list(self._open_constraints),
                "constraints_cleared": list(self._cleared),
            })
            return out

        # A tradeoff is a stated step abandoned while the turn still delivered.
        # This is the weakest rule in the set, so it is deliberately narrow: it
        # only fires when a plan existed, some of it shipped, and some did not.
        if planned and 0 < done < planned:
            out.append(self._ms(TRADEOFF_MADE, dropped=planned - done,
                                kept=done))

        out.append(self._ms(GOAL_SETTLED, detail=str(final_text)[:200]))
        self._to(DELIVERED)

        if not planned:
            outcome = ACHIEVED if not self._open_constraints else PARTIAL
        elif done == 0:
            outcome = BLOCKED_OUT
        elif done >= planned and not self._open_constraints:
            outcome = ACHIEVED
        else:
            outcome = PARTIAL

        out.append({
            "kind": "turn_end",
            "outcome": outcome,
            "governed_down": self._governed_down,
            "stage_history": list(self.history),
            "plan_steps": planned,
            "plan_done": done,
            "tool_calls": self._tool_calls,
            "vetoes": self._vetoes,
            "constraints_open": list(self._open_constraints),
            "constraints_cleared": list(self._cleared),
        })
        return out


# ------------------------------------------------------------- session ledger
def session_ledger(events: list[dict], session_id: str | None = None) -> list[dict]:
    """What has happened in this session, one row per turn, derived from the
    journal alone.

    This is the record Dad is shown when the house is shared, so that knowing
    what the other person already asked does not depend on him remembering a
    transcript. Each row: who asked, what they asked, how it ended, the
    constraints found, the milestones by name, and the reply. Pure function
    over events; nothing here consults the model.
    """
    rows: dict[str, dict] = {}
    order: list[str] = []
    for e in events:
        tid = e.get("turn_id")
        if not tid:
            continue
        if session_id is not None and e.get("session_id") != session_id:
            continue
        kind = e.get("kind")
        if tid not in rows:
            rows[tid] = {"turn_id": tid, "user": None, "prompt": "", "outcome": None,
                         "reply": "", "constraints": [], "milestones": []}
            order.append(tid)
        r = rows[tid]
        if kind == "turn_start":
            r["user"] = e.get("user")
            r["prompt"] = e.get("prompt", "")
        elif kind in ("final", "clarify"):
            r["reply"] = e.get("text", "") or ""
        elif kind == "milestone":
            name = e.get("milestone")
            if name and name not in (GOAL_FRAMED, GOAL_SETTLED):
                r["milestones"].append(name)
            if name == CONSTRAINT_FOUND:
                detail = str(e.get("detail") or e.get("subject") or "")
                if detail:
                    r["constraints"].append(detail)
        elif kind == "turn_end":
            r["outcome"] = e.get("outcome")
    return [rows[t] for t in order]


def ledger_note(rows: list[dict], *, max_rows: int = 12, max_chars: int = 160) -> str:
    """The session ledger as text for a system prompt. Newest last, capped so a
    long session does not crowd out the constitution."""
    if not rows:
        return ""
    lines = ["WHAT HAS HAPPENED IN THIS HOUSE THIS SESSION (derived from the record; "
             "this is the truth about who asked for what):"]
    for r in rows[-max_rows:]:
        who = r.get("user") or "someone"
        ask = (r.get("prompt") or "").strip().replace("\n", " ")[:max_chars]
        out = r.get("outcome") or "in progress"
        line = f'- {who} asked: "{ask}" -> {out.lower()}'
        cons = [c.replace("\n", " ")[:80] for c in r.get("constraints", [])][:3]
        if cons:
            line += "; found: " + "; ".join(cons)
        reply = (r.get("reply") or "").strip().replace("\n", " ")
        if reply:
            line += f'; Dad said: "{reply[:max_chars]}"'
        lines.append(line)
    return "\n".join(lines)
