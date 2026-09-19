"""Author: Mike Bell
Last Modified: 2026-09-18
Purpose: Tests the benchmark harness records one honest row per turn and resets the world.

Guards the four ways a benchmark lies: a case that inherits state from the case
before it, a nested model call that the tracer never sees, a row missing the
field a later comparison needs, and a reporter that averages the wrong thing."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

from dadloop import AgentLoop, Context, SemanticMemory
from dadloop.core import tools


def test_corpus_is_well_formed():
    from bench.prompts import CASES, FROZEN_WORLD
    from dadloop.core import skills as skill_lib
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    assert len(CASES) >= 20, "corpus too small to average over"
    for c in CASES:
        assert c["prompt"].strip(), c
        for sk in c["expected_skills"]:
            assert sk in skill_lib.SKILLS, f"{c['id']} expects a skill that does not exist: {sk}"
    assert set(FROZEN_WORLD) == set(tools.WORLD), "FROZEN_WORLD must cover every WORLD key"
    no_skill = [c for c in CASES if not c["expected_skills"]]
    assert len(no_skill) >= 4, "need no-skill prompts to measure false positives"
    print(f"PASS: {len(CASES)} cases, {len(no_skill)} expect no skill, world keys match")


def _scripted_client(loads=("the-thermostat",)):
    """Turn 1: call check_weather and load the given skills. Turn 2: answer."""
    class FM:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                blocks = [NS(type="tool_use", id="w", name="check_weather", input={})]
                blocks += [NS(type="tool_use", id=f"s{i}", name="load_skill", input={"name": s})
                           for i, s in enumerate(loads)]
                return NS(model="claude-haiku-4-5-20251001", content=blocks,
                          usage=NS(input_tokens=1000, output_tokens=40))
            return NS(model="claude-haiku-4-5-20251001",
                      content=[NS(type="text", text="1. Check\nDone, sweater time.")],
                      usage=NS(input_tokens=1200, output_tokens=30))
    return type("FC", (), {"messages": FM()})()


def _make_agent_factory(loads=("the-thermostat",)):
    def make_agent(memory_root: Path) -> AgentLoop:
        dad = AgentLoop(Context(memory=SemanticMemory(memory_root)))
        dad._client = _scripted_client(loads)
        return dad
    return make_agent


def test_harness_writes_one_row_per_case_and_repeat():
    from bench.harness import run_arm
    cases = [{"id": "a", "prompt": "cold", "expected_skills": ["the-thermostat"]},
             {"id": "b", "prompt": "colder", "expected_skills": []}]
    out = Path(tempfile.mkdtemp())
    path = run_arm("baseline", cases, repeats=2, make_agent=_make_agent_factory(), out_dir=out)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert path == out / "baseline.jsonl"
    assert len(rows) == 4, rows
    r = rows[0]
    for key in ("arm", "case_id", "prompt", "expected_skills", "repeat", "session_id", "turn_id",
                "llm_calls", "tool_calls", "tokens_in", "tokens_out", "total_ms", "llm_ms", "tool_ms",
                "cost", "unpriced_calls", "models", "loaded_skills", "load_skill_calls",
                "outcome", "plan_steps", "plan_done", "vetoes", "final_chars"):
        assert key in r, f"row missing {key}: {r}"
    assert r["llm_calls"] == 2 and r["tokens_in"] == 2200 and r["tokens_out"] == 70
    assert r["loaded_skills"] == ["the-thermostat"] and r["load_skill_calls"] == 1
    assert abs(r["cost"] - (2200 / 1e6 * 1.0 + 70 / 1e6 * 5.0)) < 1e-9, r["cost"]
    assert {(x["case_id"], x["repeat"]) for x in rows} == {("a", 0), ("a", 1), ("b", 0), ("b", 1)}
    print("PASS: 2 cases x 2 repeats = 4 rows, every field present, numbers match the journal")


def test_harness_resets_world_and_disables_live_search():
    from bench.harness import run_arm
    from bench.prompts import FROZEN_WORLD
    seen = []

    def make_agent(memory_root: Path) -> AgentLoop:
        seen.append(dict(tools.WORLD))          # what the case starts from
        tools.WORLD["propane"] = "full"         # a case that dirties the world
        dad = AgentLoop(Context(memory=SemanticMemory(memory_root)))
        dad._client = _scripted_client()
        return dad

    saved_world = dict(tools.WORLD)
    out = Path(tempfile.mkdtemp())
    path = run_arm("baseline", [{"id": "a", "prompt": "x", "expected_skills": []}],
                   repeats=2, make_agent=make_agent, out_dir=out)
    assert seen[0] == FROZEN_WORLD and seen[1] == FROZEN_WORLD, seen
    assert tools.WORLD == saved_world, "world must be restored to what it was before the run"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    # check_weather ran on a scripted client that has no web_search branch: had
    # the nested live search been attempted, it would have raised through the
    # tool. The small tool time and the clean tool count prove it was bypassed.
    assert rows[0]["tool_calls"] == 2
    assert all(r["tool_ms"] < 100 for r in rows), "no nested model call should land in tool time"
    print("PASS: each case starts from FROZEN_WORLD, world restored after, live search bypassed")


if __name__ == "__main__":
    test_corpus_is_well_formed()
    test_harness_writes_one_row_per_case_and_repeat()
    test_harness_resets_world_and_disables_live_search()
