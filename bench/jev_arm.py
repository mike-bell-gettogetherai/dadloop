"""Author: Mike Bell
Last Modified: 2026-09-19
Purpose: The Jev arm: pre-select skills with one TypeSafe call, inject the bodies, then run Dad.

Baseline Dad learns which skills a request needs by calling load_skill, one
round trip per body (or a batch, if the model batches). This arm asks Jev
(TypeSafe's System One model) fifteen yes/no questions in ONE call before the
first Claude call, "does this request need the <skill> playbook", and puts the
bodies that clear the threshold into the system prompt. load_skill stays
available, so any later load is leakage the row records.

Everything the selector does is recorded on the turn: which skills, every
probability, its latency, its token usage, and the model that answered. The
core loop is not modified. The one seam is `_system_prompt`, wrapped at import
so a Context carrying `_preloaded_skill_text` gets it appended; a baseline
agent carries nothing and is untouched."""
from __future__ import annotations

import time
from typing import Callable

from dadloop import AgentLoop
from dadloop.core import agent as agent_module
from dadloop.core import skills as skill_lib

_PRELOAD_ATTR = "_preloaded_skill_text"


def _patch_system_prompt() -> None:
    original = agent_module._system_prompt
    if getattr(original, "_jev_patched", False):
        return

    def with_preloaded(ctx, people=None, ledger=""):
        text = original(ctx, people, ledger)
        extra = getattr(ctx, _PRELOAD_ATTR, "")
        return text + extra if extra else text

    with_preloaded._jev_patched = True                    # type: ignore[attr-defined]
    agent_module._system_prompt = with_preloaded


_patch_system_prompt()


DEFAULT_QUESTION = "Does handling this request require Dad's '{name}' playbook? Playbook: {description}"


def expand(chosen: list[str], composes: dict[str, list[str]] | None) -> list[str]:
    """Transitive closure over the composition map, in discovery order. The
    selector finds entry points; this is the structural part it cannot see."""
    if not composes:
        return list(chosen)
    out: list[str] = []
    stack = list(chosen)
    while stack:
        n = stack.pop(0)
        if n in out:
            continue
        out.append(n)
        stack.extend(x for x in composes.get(n, []) if x not in out)
    return out


class Preselector:
    """One system_one call with a Noul per skill; skills at or above `threshold`
    are chosen, then expanded through `composes` (skill -> skills it loads).

    `question` is the instruction template; it may use {name}, {description},
    and, when `triggers` are given, {about}. `triggers` maps a skill to
    selector-facing text: "about" (what the request is about), "true" and
    "false" (Noul criteria: what counts and what does not). The Claude-facing
    description is untouched either way."""

    def __init__(self, client, *, threshold: float = 0.5, model: str | None = None,
                 clock: Callable[[], float] = time.perf_counter,
                 question: str = DEFAULT_QUESTION, triggers: dict[str, dict] | None = None,
                 composes: dict[str, list[str]] | None = None):
        self.client = client
        self.threshold = threshold
        self.model = model
        self.clock = clock
        self.question = question
        self.triggers = triggers or {}
        self.composes = composes or {}

    def _question(self, name: str, description: str):
        from typesafe_sdk import Noul
        trig = self.triggers.get(name, {})
        text = self.question.format(name=name, description=description, about=trig.get("about", description))
        criteria = None
        if trig.get("true") or trig.get("false"):
            criteria = {"true": trig.get("true"), "false": trig.get("false")}
        return Noul(instructions=text, criteria=criteria)

    def select(self, prompt: str, names: list[str], descriptions: dict[str, str]) -> dict:
        questions = {n: self._question(n, descriptions.get(n, "")) for n in names}
        t0 = self.clock()
        kwargs = {"model": self.model} if self.model else {}
        resp = self.client.system_one(state={"request": prompt}, questions=questions, **kwargs)
        ms = (self.clock() - t0) * 1000
        probs = {n: float(getattr(resp.answers[n], "noul", 0.0)) for n in names}
        entry = [n for n, p in sorted(probs.items(), key=lambda kv: -kv[1]) if p >= self.threshold]
        usage = getattr(resp, "usage", None)
        return {
            "chosen_entry": entry, "chosen": expand(entry, self.composes),
            "probs": probs, "threshold": self.threshold, "ms": round(ms, 1),
            "calls": 1, "model": getattr(resp, "model", None),
            "tokens_in": int(getattr(usage, "input_tokens", 0) or 0),
            "tokens_out": int(getattr(usage, "output_tokens", 0) or 0),
        }


def preload_text(chosen: list[str]) -> str:
    bodies = [f"## {n}\n{skill_lib.SKILLS[n].body}" for n in chosen if n in skill_lib.SKILLS]
    if not bodies:
        return ""
    return ("\n\nThese playbooks were pre-loaded for this request; you do not need to call "
            "load_skill for them. You may still load others.\n\n" + "\n\n".join(bodies))


class JevAgent(AgentLoop):
    """AgentLoop with a selection step before each turn and a journaled record of it."""

    def __init__(self, *args, preselector: Preselector, **kwargs):
        super().__init__(*args, **kwargs)
        self.preselector = preselector
        self.last_preselect: dict | None = None

    def turn(self, user_text: str, *, on_event=None, user: str | None = None) -> str:
        names = list(skill_lib.SKILLS)
        sel = self.preselector.select(user_text, names, {n: s.description for n, s in skill_lib.SKILLS.items()})
        self.last_preselect = sel
        setattr(self.ctx, _PRELOAD_ATTR, preload_text(sel["chosen"]))
        try:
            reply = super().turn(user_text, on_event=on_event, user=user)
        finally:
            setattr(self.ctx, _PRELOAD_ATTR, "")
        if self.journal is not None:
            self.journal.write({"session_id": self.session_id, "turn_id": self._turn_id, "tier": 1,
                                "kind": "preselect", **sel})
        return reply
