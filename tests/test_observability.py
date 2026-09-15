"""Author: Swami Chandrasekaran
Last Modified: 2026-09-02
Purpose: Tests the observability layer — durable journal and derived business state.

Two properties matter here and neither is about pretty output.

First, a turn must leave a complete, replayable record. If the journal drops
events, replay lies, and a console built on it lies with it.

Second, every business-level claim must be derived from an observable fact and
must point at that fact. The stage machine is never allowed to ask the model how
it is doing, for the same reason the RSI scorer refuses to grade on "did that
read well." So these tests drive the machine with mechanical events only and
assert the derived output, including the causal pointer.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dadloop import AgentLoop, Context, SemanticMemory
from dadloop.core import journal as jrnl
from dadloop.core import stages


def _cookout_client():
    """A turn that states a 3-step plan, hits an empty propane tank, then tries
    a $400 spend Mom has to cap. One turn, one block, one veto."""
    class FM:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return NS(content=[
                    NS(type="text", text="1. Check the grill\n2. Check the budget\n3. Light it"),
                    NS(type="tool_use", id="a", name="check_grill", input={}),
                ], usage=NS(input_tokens=900, output_tokens=60))
            if self.n == 2:
                return NS(content=[
                    NS(type="tool_use", id="b", name="check_wallet",
                       input={"amount": 400, "reason": "nice grill"}),
                ], usage=NS(input_tokens=300, output_tokens=30))
            return NS(content=[NS(type="text", text="Borrow a tank before six.")],
                      usage=NS(input_tokens=200, output_tokens=20))
    return type("FC", (), {"messages": FM()})()


def _run_turn():
    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem))
    dad._client = _cookout_client()
    reply = dad.turn("twelve people saturday, forty bucks")
    return dad, reply


def test_journal_is_written_beside_memory_and_replays():
    """A turn leaves a complete record in the household's own directory."""
    dad, _ = _run_turn()
    assert dad.journal.path.parent == dad.ctx.memory.root, \
        "journal must live beside the memory it describes, not in a global path"

    events = dad.journal.read_all()
    kinds = [e["kind"] for e in events]
    assert "turn_start" in kinds, "a turn must open the record with its prompt"
    assert "tool_call" in kinds and "tool_result" in kinds, "mechanical events must persist"
    assert "final" in kinds, "the closing reply must be on record"

    # every line is valid json and every event carries a monotonic seq
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), \
        "seq must be unique and monotonic so caused_by_seq resolves"

    # and one turn's events are retrievable on their own, which is what replay needs
    turn_id = events[0]["turn_id"]
    assert dad.journal.read_turn(turn_id) == [e for e in events if e["turn_id"] == turn_id]
    print(f"PASS: turn journaled beside memory, {len(events)} events, replayable")


def test_business_state_is_derived_and_traceable():
    """Stages and milestones come from facts, and each names the fact."""
    dad, _ = _run_turn()
    events = dad.journal.read_all()
    tier2 = [e for e in events if e.get("tier") == 2]
    milestones = {e["milestone"]: e for e in tier2 if e["kind"] == "milestone"}

    assert "GOAL_FRAMED" in milestones, "a stated plan is a framed goal"
    assert "CONSTRAINT_FOUND" in milestones, "empty propane closes a door"
    assert milestones["CONSTRAINT_FOUND"]["subject"] == "grill"
    assert "AUTHORITY_APPLIED" in milestones, "Mom capping a $400 spend is authority"

    # the causal pointer must resolve to a real mechanical event
    by_seq = {e["seq"]: e for e in events}
    for m in milestones.values():
        cause = by_seq.get(m["caused_by_seq"])
        assert cause is not None and cause.get("tier") == 1, \
            f"{m['milestone']} must point at the tier 1 event that caused it"

    end = [e for e in tier2 if e["kind"] == "turn_end"][0]
    assert end["outcome"] == "PARTIAL", "a plan left unfinished is not ACHIEVED"
    assert end["governed_down"] is True, "a veto that changed the call must be flagged"
    assert "BLOCKED" in end["stage_history"] and "GOVERNED" in end["stage_history"]
    assert end["constraints_open"] == ["grill"], "the unresolved block must be named"
    print(f"PASS: derived {sorted(milestones)} — each traceable to its cause")


def test_stage_machine_is_pure_and_never_asks_the_model():
    """Driven by mechanical events alone, with no client and no I/O."""
    m = stages.StageMachine()
    assert m.stage == stages.RECEIVED

    m.observe("plan", ["check the grill", "light it"])
    assert m.stage == stages.FRAMING

    m.observe("tool_call", ("check_grill", {}, "a"))
    assert m.stage == stages.GATHERING

    out = m.observe("tool_result", ("check_grill", "PROBLEM: propane tank is EMPTY.", "a", 12))
    assert m.stage == stages.BLOCKED
    assert any(e["milestone"] == stages.CONSTRAINT_FOUND for e in out)

    # Tools use two prefixes for a door-closing fact, not one. A closed hardware
    # store reports CONFLICT, and missing it silently drops a real constraint.
    assert stages.is_problem("CONFLICT: hardware store is CLOSED today."), \
        "CONFLICT must count as a constraint, same as PROBLEM"
    assert not stages.is_problem("Pantry stocked: corn, peppers, halloumi.")

    # a later clean read on the same subject reopens the door
    out = m.observe("tool_result", ("check_grill", "Grill's ready. Propane full.", "b", 9))
    assert any(e["milestone"] == stages.CONSTRAINT_CLEARED for e in out)
    assert m.stage == stages.GATHERING

    m.observe("plan_step_done", (0, "check the grill", True))   # 1 of 2 stated steps

    end = m.finish(final_text="ready")
    outcome = [e for e in end if e["kind"] == "turn_end"][0]
    assert outcome["outcome"] == stages.PARTIAL, \
        "one of two stated steps done is partial, not achieved"
    assert any(e.get("milestone") == stages.TRADEOFF_MADE for e in end), \
        "a stated step left undone while the turn still delivered is a tradeoff"
    print("PASS: stage machine derives from facts alone, no model consulted")


def test_journal_failure_never_breaks_a_turn():
    """Observability that can take down what it observes is worse than none."""
    j = jrnl.Journal(Path("/proc/nonexistent-dir/journal.jsonl"))
    assert j.write({"kind": "x"}) is None, "an unwritable journal returns None, not an exception"

    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem), journal=j)
    dad._client = _cookout_client()
    reply = dad.turn("twelve people saturday")
    assert reply, "the turn must still produce a reply with a dead journal"
    print("PASS: a broken journal degrades silently, the turn still completes")


def test_journal_can_be_disabled():
    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem), journal=False)
    dad._client = _cookout_client()
    assert dad.journal is None
    assert dad.turn("twelve people saturday"), "journal=False must not affect the turn"
    print("PASS: journalling is opt-out and the harness runs without it")


def test_seq_stays_unique_across_a_restart():
    """Restarting the harness (a fresh AgentLoop on the same memory) must keep
    writing into the same journal with seqs that continue, never restart. If
    they restarted, caused_by_seq pointers from the second session would
    resolve to events from the first — the console would confidently name the
    wrong cause. Found in review; it is the kind of bug a single-process test
    suite never sees."""
    root = Path(tempfile.mkdtemp()) / "m"

    first = AgentLoop(Context(memory=SemanticMemory(root)))
    first._client = _cookout_client()
    first.turn("twelve people saturday")
    seqs_before = [e["seq"] for e in first.journal.read_all()]
    assert seqs_before, "first session must have written something"

    # "restart": brand-new AgentLoop and Journal objects, same file on disk
    second = AgentLoop(Context(memory=SemanticMemory(root)))
    second._client = _cookout_client()
    second.turn("twelve people saturday, again")
    all_seqs = [e["seq"] for e in second.journal.read_all()]

    assert len(all_seqs) == len(set(all_seqs)), \
        f"seq collided across restart: {sorted(s for s in all_seqs if all_seqs.count(s) > 1)}"
    assert all_seqs == sorted(all_seqs), "seq must stay monotonic across the file"
    assert min(all_seqs[len(seqs_before):]) > max(seqs_before), \
        "the second session must continue from where the first left off"

    # and the causal pointers from the SECOND session resolve inside it
    by_seq = {e["seq"]: e for e in second.journal.read_all()}
    second_id = second.session_id
    for e in second.journal.read_all():
        if e.get("tier") == 2 and e.get("session_id") == second_id:
            cause = by_seq[e["caused_by_seq"]]
            assert cause.get("session_id") == second_id, \
                "a derived event must point at a cause from its own session"
    print("PASS: seq continues across restarts; causal pointers never cross sessions")


def _sleepover_client(reply):
    """Every call returns the same canned reply — enough for a single-turn probe
    of the clarify/final distinction."""
    class FM:
        def create(self, **kw): return reply
    return type("FC", (), {"messages": FM()})()

def _text_only(text):
    return NS(content=[NS(type="text", text=text)],
              usage=NS(input_tokens=200, output_tokens=30))


def test_clarifying_questions_share_a_session_and_are_never_mistaken_for_done():
    """The exact shape a user actually hit: 'plan the sleepover', then three short
    answers to Dad's follow-up questions, then the real plan. Four turn() calls
    on one AgentLoop. Before session_id and the clarify/final split, the journal
    had no way to say these four belonged together, and a clarifying question
    ('when is it?') was indistinguishable from a completed answer."""
    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem))
    started_session = dad.session_id

    dad._client = _sleepover_client(_text_only(
        "I need to understand the scope. When is this sleepover happening?"))
    dad.turn("can you plan and setup the kids room for their all boys sleepover")

    dad._client = _sleepover_client(_text_only(
        "Got it, this weekend. How many kids total are sleeping over?"))
    dad.turn("this weekend")

    dad._client = _sleepover_client(_text_only("3 boys — what ages?"))
    dad.turn("3 boys")

    dad._client = _sleepover_client(_text_only(
        "1. Clear floor space\n2. Lay out sleeping bags\n"
        "Here's the plan for the boys' sleepover: clear the floor, lay out "
        "sleeping bags. Three 8-10 year olds can share one room."))
    dad.turn("8-10")

    assert dad.session_id == started_session, \
        "session_id must not change across turns on the same AgentLoop instance"

    events = dad.journal.read_all()
    session_ids = {e.get("session_id") for e in events}
    assert session_ids == {started_session}, \
        "every event from every turn must carry the same session_id"

    turn_ids = {e["turn_id"] for e in events if e.get("kind") == "turn_start"}
    assert len(turn_ids) == 4, "four turn() calls must still be four distinct turns"

    kinds = [e["kind"] for e in events if e["kind"] in ("clarify", "final")]
    assert kinds == ["clarify", "clarify", "clarify", "final"], \
        "the first three turns asked something back; only the fourth concluded"

    outcomes = [e["outcome"] for e in events if e["kind"] == "turn_end"]
    assert outcomes == [stages.AWAITING, stages.AWAITING, stages.AWAITING,
                        stages.ACHIEVED], \
        "a clarifying question must never be reported as ACHIEVED"

    milestones = [e["milestone"] for e in events if e["kind"] == "milestone"]
    assert milestones.count(stages.CLARIFICATION_ASKED) == 3
    assert milestones[-1] == stages.GOAL_SETTLED, \
        "only the turn that actually concluded gets GOAL_SETTLED"
    print("PASS: four turns, one session, three clarifications correctly never "
          "reported as done")


def test_a_single_shot_plan_with_no_tool_call_still_counts_as_work():
    """A fully-answerable request can state a plan and settle it in one response
    with no tool call at all. That must still land as `final`, not `clarify` —
    the bug this exact case caught during review: the no-tool-uses branch
    returns before the later plan-detection code ever runs, so the check has to
    happen on this path too."""
    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem))
    dad._client = _sleepover_client(_text_only(
        "1. Say hi\n2. Wish them luck\nHere's the plan: say hi and wish them luck."))
    events_seen = []
    dad.turn("write a quick note", on_event=lambda k, p: events_seen.append(k))
    assert "clarify" not in events_seen and "final" in events_seen, \
        "a stated plan with zero tool calls is still real work, not a question"
    print("PASS: a single-shot stated plan is not mistaken for a clarifying question")


def test_a_short_prose_conclusion_with_no_plan_or_tool_is_not_a_clarification():
    """The real bug found while testing the console against live data: a short,
    complete answer that states no numbered plan and calls no tool ('sure, corn
    and peppers work') has no plan and no tool call, exactly like a genuine
    clarifying question does. no-plan-no-tool alone is not enough to tell them
    apart. The second, cheap, still-derived signal is whether the reply actually
    asks something — ends in '?'. A conclusion that happens to be short prose
    must never be classified as a question just because it skipped the numbered
    list."""
    mem = SemanticMemory(Path(tempfile.mkdtemp()) / "m")
    dad = AgentLoop(Context(memory=mem))
    dad._client = _sleepover_client(_text_only(
        "Here's the plan for the boys' sleepover: clear the floor space and lay "
        "out sleeping bags. Three 8-10 year olds can share one room."))
    events_seen = []
    dad.turn("8-10", on_event=lambda k, p: events_seen.append(k))
    assert "clarify" not in events_seen and "final" in events_seen, \
        "a prose conclusion with no plan and no tool call must not be mistaken " \
        "for a clarifying question just because it never called parse_plan"
    print("PASS: a short prose conclusion (no plan, no tool, no question mark) "
          "is correctly classified as final, not a clarification")


if __name__ == "__main__":
    test_journal_is_written_beside_memory_and_replays()
    test_business_state_is_derived_and_traceable()
    test_stage_machine_is_pure_and_never_asks_the_model()
    test_journal_failure_never_breaks_a_turn()
    test_journal_can_be_disabled()
    test_seq_stays_unique_across_a_restart()
    test_clarifying_questions_share_a_session_and_are_never_mistaken_for_done()
    test_a_single_shot_plan_with_no_tool_call_still_counts_as_work()
    test_a_short_prose_conclusion_with_no_plan_or_tool_is_not_a_clarification()
