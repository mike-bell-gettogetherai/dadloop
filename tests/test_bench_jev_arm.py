"""Author: Mike Bell
Last Modified: 2026-09-19
Purpose: Tests the Jev pre-selection arm injects chosen skills and records what it did.

Guards the three ways a pre-selection arm could look better than it is: bodies
that never actually reach the model's system prompt, a selection step whose
cost and latency vanish from the row, and a threshold that quietly admits
everything. Uses a fake selector; the live one is only wired in bench/run.py."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

from dadloop import AgentLoop, Context, SemanticMemory
from dadloop.core import skills as skill_lib


class _Capture:
    """A Claude client that records the system prompt it was given and answers."""
    def __init__(self):
        self.systems = []
        class FM:
            def create(inner, **kw):
                self.systems.append(kw.get("system", ""))
                return NS(model="claude-haiku-4-5-20251001",
                          content=[NS(type="text", text="Done.")],
                          usage=NS(input_tokens=500, output_tokens=10))
        self.messages = FM()


def _fake_selector(probs: dict, ms: float = 12.5):
    from bench.jev_arm import Preselector
    class FakeTS:
        def system_one(self, *, state, questions, **kw):
            answers = {k: NS(noul=probs.get(k, 0.01)) for k in questions}
            return NS(model="jev-fake", usage=NS(input_tokens=100, output_tokens=15), answers=answers)
    return Preselector(FakeTS(), threshold=0.5, clock=lambda: 0.0)


def test_chosen_bodies_reach_the_system_prompt_and_baseline_stays_clean():
    from bench.jev_arm import JevAgent
    sel = _fake_selector({"the-thermostat": 0.93, "grilling": 0.12})
    cap = _Capture()
    dad = JevAgent(Context(memory=SemanticMemory(Path(tempfile.mkdtemp()) / "m")), preselector=sel)
    dad._client = cap
    dad.turn("I'm cold")
    body = skill_lib.SKILLS["the-thermostat"].body.splitlines()[0]
    assert cap.systems and body in cap.systems[0], "the chosen skill body must be in the system prompt"
    assert "pre-loaded" in cap.systems[0].lower()
    assert skill_lib.SKILLS["grilling"].body.splitlines()[0] not in cap.systems[0], "unchosen skill leaked in"

    base_cap = _Capture()
    base = AgentLoop(Context(memory=SemanticMemory(Path(tempfile.mkdtemp()) / "m")))
    base._client = base_cap
    base.turn("I'm cold")
    assert body not in base_cap.systems[0], "baseline must not carry a pre-loaded body"
    print("PASS: chosen body is in the Jev system prompt, absent from baseline's")


def test_preselect_is_journaled_and_lands_on_the_row():
    from bench.harness import run_arm
    from bench.jev_arm import JevAgent
    def make_agent(root: Path) -> AgentLoop:
        dad = JevAgent(Context(memory=SemanticMemory(root)),
                       preselector=_fake_selector({"the-thermostat": 0.9, "bedtime": 0.55, "grilling": 0.2}))
        dad._client = _Capture()
        return dad
    out = Path(tempfile.mkdtemp())
    path = run_arm("jev", [{"id": "a", "prompt": "cold", "expected_skills": ["the-thermostat"]}],
                   repeats=1, make_agent=make_agent, out_dir=out)
    r = json.loads(path.read_text().splitlines()[0])
    assert r["preselected"] == ["the-thermostat", "bedtime"], r      # ranked by probability
    assert r["preselect_calls"] == 1 and r["preselect_ms"] >= 0
    assert r["preselect_tokens_in"] == 100 and r["preselect_tokens_out"] == 15
    assert r["preselect_model"] == "jev-fake"
    assert abs(r["preselect_probs"]["grilling"] - 0.2) < 1e-9
    print("PASS: preselect event is journaled with the turn and folded onto the row")


def test_threshold_is_inclusive_at_half_and_excludes_below():
    sel = _fake_selector({"a-skill": 0.5, "b-skill": 0.49})
    out = sel.select("x", ["a-skill", "b-skill"], {"a-skill": "A", "b-skill": "B"})
    assert out["chosen"] == ["a-skill"], out
    print("PASS: threshold admits 0.50 and excludes 0.49")


if __name__ == "__main__":
    test_chosen_bodies_reach_the_system_prompt_and_baseline_stays_clean()
    test_preselect_is_journaled_and_lands_on_the_row()
    test_threshold_is_inclusive_at_half_and_excludes_below()
