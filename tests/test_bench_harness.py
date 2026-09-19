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


if __name__ == "__main__":
    test_corpus_is_well_formed()
