"""Author: Mike Bell
Last Modified: 2026-09-18
Purpose: Run a frozen corpus through Dad under one arm and record one row per turn.

Follows the repo's replay pattern (improve_loop._score_body_on_cases): a fresh
agent with fresh memory per case so nothing leaks between cases. Two extra
controls a benchmark needs and a replay does not:

  * tools.WORLD is reset to FROZEN_WORLD before every case and restored after
    the run, so a case cannot inherit a propane tank the previous case filled.
  * tools._live_search is replaced with a no-op for the run. That nested
    Claude call is invisible to the tracer and nondeterministic; with it off,
    check_weather returns the offline estimate, tool time is real tool time,
    and every model call the arm makes is one the trace counts.

Rows are read back out of the agent's own journal, not assembled from return
values, so the benchmark reports exactly what the harness recorded."""
from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from dadloop import AgentLoop
from dadloop.core import tools

from .prompts import FROZEN_WORLD

MakeAgent = Callable[[Path], AgentLoop]


@contextmanager
def _frozen_world():
    saved = dict(tools.WORLD)
    saved_search = tools._live_search
    tools._live_search = lambda ctx, prompt, **kw: None   # offline branch in every tool
    try:
        yield
    finally:
        tools._live_search = saved_search
        tools.WORLD.clear()
        tools.WORLD.update(saved)


def row_from_journal(events: list[dict], *, arm: str, case: dict, repeat: int) -> dict:
    """Fold one turn's journal events into a flat row."""
    trace = next((e for e in events if e.get("kind") == "trace"), {})
    end = next((e for e in events if e.get("kind") == "turn_end"), {})
    loads = [(e.get("args") or {}).get("name") for e in events
             if e.get("kind") == "tool_call" and e.get("name") == "load_skill"]
    final = next((e.get("text", "") for e in events if e.get("kind") in ("final", "clarify")), "")
    any_event = events[0] if events else {}
    pre = next((e for e in events if e.get("kind") == "preselect"), None)
    return {
        "arm": arm, "case_id": case["id"], "prompt": case["prompt"],
        "expected_skills": list(case.get("expected_skills", [])), "repeat": repeat,
        "tier": case.get("tier"),
        "session_id": any_event.get("session_id"), "turn_id": any_event.get("turn_id"),
        "llm_calls": trace.get("llm_calls"), "tool_calls": trace.get("tool_calls"),
        "tokens_in": trace.get("tokens_in"), "tokens_out": trace.get("tokens_out"),
        "cache_read": trace.get("cache_read", 0), "cache_write": trace.get("cache_write", 0),
        "total_ms": trace.get("total_ms"), "llm_ms": trace.get("llm_ms"), "tool_ms": trace.get("tool_ms"),
        "cost": trace.get("cost"), "unpriced_calls": trace.get("unpriced_calls"),
        "models": trace.get("models", []),
        "loaded_skills": list(dict.fromkeys(s for s in loads if s)),
        "load_skill_calls": len(loads),
        "outcome": end.get("outcome"), "plan_steps": end.get("plan_steps"),
        "plan_done": end.get("plan_done"), "vetoes": end.get("vetoes"),
        "final_chars": len(final or ""),
        # The loop's stuck path: it ran out of model calls while still asking
        # for tools, and returned the "wandered off" line instead of an answer.
        "hit_ceiling": (final or "").startswith("(Dad got distracted"),
        # Pre-selection arm only; baseline rows carry the empty defaults.
        "preselected": list(pre["chosen"]) if pre else [],
        "preselect_probs": dict(pre["probs"]) if pre else {},
        "preselect_calls": int(pre["calls"]) if pre else 0,
        "preselect_ms": float(pre["ms"]) if pre else 0.0,
        "preselect_tokens_in": int(pre.get("tokens_in", 0)) if pre else 0,
        "preselect_tokens_out": int(pre.get("tokens_out", 0)) if pre else 0,
        "preselect_model": pre.get("model") if pre else None,
    }


def run_arm(arm: str, cases: list[dict], *, repeats: int, make_agent: MakeAgent,
            out_dir: Path, on_row: Callable[[dict], None] | None = None) -> Path:
    """Run every case `repeats` times under `arm`; append rows to <out_dir>/<arm>.jsonl.

    Sequential on purpose: concurrent turns would share rate limits and skew
    wall clock. `make_agent(memory_root)` must return a fresh AgentLoop whose
    journal lives beside that memory root (the default when Context is built
    from SemanticMemory(memory_root)), because the row is read from it."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{arm}.jsonl"
    with _frozen_world(), path.open("a", encoding="utf-8") as fh:
        for case in cases:
            for repeat in range(repeats):
                tools.WORLD.clear()
                tools.WORLD.update(FROZEN_WORLD)
                root = Path(tempfile.mkdtemp(prefix="dadloop-bench-")) / "m"
                try:
                    agent = make_agent(root)
                    agent.turn(case["prompt"])
                    events = agent.journal.read_all() if agent.journal is not None else []
                    row = row_from_journal(events, arm=arm, case=case, repeat=repeat)
                finally:
                    shutil.rmtree(root.parent, ignore_errors=True)
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                if on_row:
                    on_row(row)
    return path
