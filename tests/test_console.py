"""Author: Swami Chandrasekaran
Last Modified: 2026-08-31
Purpose: Tests Mom's Console — that it reads the journal faithfully and stays read-only.

The console is a reader. Two properties matter.

It must fold the append-only log into the same turn history a live watcher saw,
because a console started halfway through a session should not disagree with one
that watched from the beginning.

And it must never be able to affect the harness it observes. The API is
read-only by construction: it imports the journal format and nothing that can
run a turn.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dadloop.core import memory
from dadloop import AgentLoop, Context, SemanticMemory


def _seed_journal(root: Path):
    """One cookout turn: a plan, a blocking fact, and a governance veto."""
    class FM:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return NS(content=[
                    NS(type="text", text="1. Check the grill\n2. Check the budget"),
                    NS(type="tool_use", id="a", name="check_grill", input={}),
                ], usage=NS(input_tokens=900, output_tokens=60))
            if self.n == 2:
                return NS(content=[NS(type="tool_use", id="b", name="check_wallet",
                                      input={"amount": 400, "reason": "grill"})],
                          usage=NS(input_tokens=300, output_tokens=25))
            return NS(content=[NS(type="text", text="Borrow a tank before six.")],
                      usage=NS(input_tokens=200, output_tokens=20))
    mem = SemanticMemory(root)
    dad = AgentLoop(Context(memory=mem))
    dad._client = type("FC", (), {"messages": FM()})()
    dad.turn("twelve guests saturday, fifty bucks")
    return dad


def test_console_serves_the_journal_it_is_pointed_at():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("SKIP: fastapi not installed")
        return

    root = Path(tempfile.mkdtemp()) / "m"
    dad = _seed_journal(root)

    import console.server as srv
    srv._journal_path = lambda: dad.journal.path      # point it at this household
    client = TestClient(srv.app)

    meta = client.get("/api/meta").json()
    assert meta["exists"] is True
    assert len(meta["stages"]) == 9, "nine stages, including AWAITING_INPUT, must be advertised"

    turns = client.get("/api/turns").json()
    assert len(turns) == 1, "one turn ran, one turn should be indexed"
    t = turns[0]
    assert t["prompt"].startswith("twelve guests")
    assert t["outcome"] in ("PARTIAL", "ACHIEVED", "BLOCKED_OUT")
    assert t["governed_down"] is True, "the $400 cap must show on the turn summary"
    assert "BLOCKED" in t["stages"] and "GOVERNED" in t["stages"]

    events = client.get(f"/api/turn/{t['turn_id']}").json()
    assert events == dad.journal.read_turn(t["turn_id"]), \
        "the API must serve the journal verbatim, not a reinterpretation"

    # every derived event still resolves to the mechanical event that caused it
    by_seq = {e["seq"]: e for e in events}
    derived = [e for e in events if e.get("tier") == 2 and e["kind"] == "milestone"]
    assert derived, "a cookout turn produces milestones"
    for m in derived:
        assert by_seq[m["caused_by_seq"]]["tier"] == 1
    print(f"PASS: console served {len(turns)} turn, {len(events)} events, all traceable")


def test_console_is_read_only():
    """The API surface exposes no way to write, and reading changes nothing."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("SKIP: fastapi not installed")
        return

    root = Path(tempfile.mkdtemp()) / "m"
    dad = _seed_journal(root)
    import console.server as srv
    srv._journal_path = lambda: dad.journal.path
    client = TestClient(srv.app)

    methods = {r.path: getattr(r, "methods", set()) for r in srv.app.routes}
    for path, verbs in methods.items():
        assert not (verbs & {"POST", "PUT", "PATCH", "DELETE"}), \
            f"{path} exposes a write verb; the console must stay read-only"

    before = dad.journal.path.read_bytes()
    client.get("/api/turns"); client.get("/api/household"); client.get("/api/meta")
    assert dad.journal.path.read_bytes() == before, "reading must not mutate the journal"
    print("PASS: console exposes no write verbs and leaves the journal untouched")


def test_household_ledger_reads_memory_files():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("SKIP: fastapi not installed")
        return

    root = Path(tempfile.mkdtemp()) / "m"
    dad = _seed_journal(root)
    import console.server as srv
    srv._journal_path = lambda: dad.journal.path
    client = TestClient(srv.app)

    # Write real usage and outcome telemetry through the actual harness calls,
    # not hand-crafted JSON -- record_use() and the outcomes writer are what a
    # real turn produces, and the ledger has to read exactly that shape.
    dad.ctx.memory.record_use("skill", "grilling")
    dad.ctx.memory.record_use("rsi-gate", "grilling:HOLD")
    from dadloop.core.improve import OutcomeRecord, record_outcome
    record_outcome(dad.ctx.memory, OutcomeRecord(
        skill="grilling", plan_steps=3, plan_done=2, tool_calls=4, tool_errors=1,
        vetoes=1, tokens=900, cost=0.0057, prompt="twelve people saturday, forty bucks"))

    led = client.get("/api/household").json()
    assert set(led) == set(memory.CATEGORIES), set(led)
    # the empty propane tank files a grievance during the turn above
    assert any("propane" in r.get("text", "").lower() for r in led["grievances"]), \
        "the ledger must surface what the turn actually filed"

    # usage and outcomes are telemetry, not prose -- the server must translate
    # them into a `friendly` line without disturbing the raw `text` a raw-mode
    # reader would want to see untouched.
    usage_rows = {r["text"]: r for r in led["usage"]}
    assert usage_rows["skill:grilling"]["friendly"] == "Loaded skill: grilling"
    assert "HOLD" in usage_rows["rsi-gate:grilling:HOLD"]["friendly"]

    outcome_row = led["outcomes"][-1]
    assert outcome_row["text"].startswith("{"), "raw outcome text must stay the untouched JSON"
    friendly = outcome_row["friendly"]
    assert "2/3 steps" in friendly and "4 tools (1 errors)" in friendly and "1 vetoes" in friendly
    assert "$0.0057" in friendly and "twelve people saturday" in friendly
    print("PASS: household ledger reads all six memory files, with usage and outcomes translated")


def _seed_sleepover(root: Path):
    """Four turns, one AgentLoop instance: three clarifying questions, then the
    plan. What the console must show as one exchange, not four rows."""
    def client(text):
        return type("FC", (), {"messages": type("FM", (), {
            "create": lambda self, **kw: NS(
                content=[NS(type="text", text=text)],
                usage=NS(input_tokens=200, output_tokens=30))
        })()})()
    mem = SemanticMemory(root)
    dad = AgentLoop(Context(memory=mem))
    dad._client = client("When is this sleepover happening?")
    dad.turn("plan the kids' sleepover")
    dad._client = client("How many kids total?")
    dad.turn("this weekend")
    dad._client = client("What ages?")
    dad.turn("3 boys")
    dad._client = client("1. Clear floor space\nHere's the plan: clear the floor space.")
    dad.turn("8-10")
    return dad


def test_console_groups_a_clarification_exchange_into_one_session():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("SKIP: fastapi not installed")
        return

    root = Path(tempfile.mkdtemp()) / "m"
    dad = _seed_sleepover(root)
    import console.server as srv
    srv._journal_path = lambda: dad.journal.path
    client = TestClient(srv.app)

    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 1, \
        "four turns on one AgentLoop must fold into exactly one session"
    s = sessions[0]
    assert s["turns"] == 4
    assert s["clarifying"] == 3, "three of the four turns asked something back"
    assert s["final_outcome"] == "ACHIEVED", \
        "the session's outcome is the turn that actually concluded"
    assert len(s["turn_ids"]) == 4

    full = client.get(f"/api/session/{s['session_id']}").json()
    kinds = [e["kind"] for e in full if e["kind"] in ("clarify", "final")]
    assert kinds == ["clarify", "clarify", "clarify", "final"], \
        "the session transcript must preserve the question-by-question order"
    print("PASS: console folds a multi-turn clarification into one session, "
          "in order, with the right outcome")


if __name__ == "__main__":
    test_console_serves_the_journal_it_is_pointed_at()
    test_console_is_read_only()
    test_household_ledger_reads_memory_files()
    test_console_groups_a_clarification_exchange_into_one_session()
