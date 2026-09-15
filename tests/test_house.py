"""Author: Swami Chandrasekaran
Last Modified: 2026-09-05
Purpose: Tests the shared house: attribution, fan-out, one writer, and the joined TUI.

Two people, one Dad. The properties that matter:

1. Every turn says who asked. On the journal, so the console and a late joiner
   can read it; in Dad's own context, so he can tell the two apart. Single-user
   mode is untouched: no name in the model's transcript, no prompt change.
2. The house fans every event out to everyone and still has exactly one
   journal writer. Two people asking at once is serialised, not interleaved,
   and the one who waits is told so.
3. A TUI that joined draws the other person's turn with the same code it uses
   for its own, and shows what happened before it arrived.
"""
import asyncio
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dadloop import AgentLoop, Context, SemanticMemory          # noqa: E402
from dadloop.core.agent import default_user                     # noqa: E402
from dadloop.house import House, HouseClient, parse_address     # noqa: E402


def _dad_on(root):
    from dadloop.core.context import Context as _C
    return AgentLoop(_C(memory=SemanticMemory(root)))


def _dad(client=None):
    dad = AgentLoop(Context(memory=SemanticMemory(Path(tempfile.mkdtemp()) / "m")))
    if client is not None:
        dad._client = client
    return dad


class _FakeMessages:
    """One tool call, then a short conclusion. Records the system prompt and
    the transcript it was shown, so tests can assert what Dad saw."""

    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.seen_system = []
        self.seen_messages = []
        self.delay = delay

    def create(self, **kw):
        self.calls += 1
        self.seen_system.append(kw.get("system", ""))
        self.seen_messages.append([dict(m) for m in kw.get("messages", [])])
        if self.delay:
            time.sleep(self.delay)
        last = kw["messages"][-1]
        if isinstance(last.get("content"), str):
            return NS(content=[NS(type="tool_use", id=f"c{self.calls}",
                                  name="check_grill", input={})],
                      usage=NS(input_tokens=10, output_tokens=5))
        return NS(content=[NS(type="text", text="Propane's fine. We're good.")],
                  usage=NS(input_tokens=10, output_tokens=5))


def _fake_client(delay: float = 0.0):
    fm = _FakeMessages(delay)
    return type("FC", (), {"messages": fm})(), fm


class _GrillThenPantry:
    """A turn that checks the grill, then would check the pantry next — unless
    a fact arrives on the tool-results message first, in which case it stops
    and says so. Real proof, not a mock of the behaviour: the second model
    call either does or doesn't contain the injected text, and that alone
    decides which branch runs."""
    def __init__(self, model_delay: float = 0.12):
        self.calls = []
        self.model_delay = model_delay

    def create(self, **kw):
        import time as _t
        msgs = kw["messages"]
        self.calls.append([dict(m) for m in msgs])
        _t.sleep(self.model_delay)
        n = len(self.calls)
        # A fact rides along on whichever tool-results message it made it onto
        # in time for -- that could be the first one back or a later one,
        # depending on real thread and socket timing, and both are correct.
        # The mock has to check every call for it, not just one hardcoded
        # step, or it's testing a timing assumption instead of the guarantee.
        last = self.calls[-1][-1]["content"]
        fact = next((b["text"] for b in last if isinstance(b, dict) and b.get("type") == "text"
                    and "told you this" in b.get("text", "")), None) if isinstance(last, list) else None
        if fact:
            return NS(content=[NS(type="text", text=f"Changing plans: {fact.split(': ', 1)[1]}")],
                      usage=NS(input_tokens=10, output_tokens=5))
        if n == 1:
            return NS(content=[NS(type="text", text="1. Check the grill\n2. Check the pantry"),
                               NS(type="tool_use", id="a", name="check_grill", input={})],
                      usage=NS(input_tokens=10, output_tokens=5))
        if n == 2:
            return NS(content=[NS(type="tool_use", id="b", name="check_pantry", input={})],
                      usage=NS(input_tokens=10, output_tokens=5))
        return NS(content=[NS(type="text", text="Pantry's fine too.")],
                  usage=NS(input_tokens=5, output_tokens=5))


# ------------------------------------------------------------------ 1. who
def test_turn_start_carries_user_and_single_user_is_unchanged():
    client, fm = _fake_client()
    dad = _dad(client)
    dad.turn("are we ready?", user="swami")
    dad.turn("and the grill?")                    # nobody said: default_user()

    starts = [e for e in dad.journal.read_all() if e["kind"] == "turn_start"]
    assert [e["user"] for e in starts] == ["swami", default_user()], starts
    assert dad.people == ["swami", default_user()]

    # Single-user mode: the model sees the text as typed, and no household note.
    first_user_msg = fm.seen_messages[0][0]["content"]
    assert first_user_msg == "are we ready?", first_user_msg
    assert "This house is shared" not in fm.seen_system[0]


def test_shared_house_tells_dad_who_is_speaking():
    client, fm = _fake_client()
    dad = _dad(client)
    dad.shared = True
    dad.turn("are we ready?", user="swami")
    dad.turn("what about the grill?", user="priya")

    # Every user message is prefixed with its speaker, and the system prompt
    # names the people and the job: catch the second ask for the same thing.
    msgs = [m["content"] for m in fm.seen_messages[-1] if isinstance(m["content"], str)]
    assert msgs[0] == "swami: are we ready?", msgs
    assert msgs[-1] == "priya: what about the grill?", msgs
    sysm = fm.seen_system[-1]
    assert "swami, priya" in sysm
    assert "do not redo the work" in sysm
    # The derived session record is in the prompt: who asked, how it ended,
    # what was found, what Dad said. Built from the journal, not recalled.
    assert "WHAT HAS HAPPENED IN THIS HOUSE THIS SESSION" in sysm
    assert 'swami asked: "are we ready?"' in sysm, sysm
    assert "Dad said:" in sysm
    # The turn being answered is not in its own record.
    assert 'priya asked: "what about the grill?"' not in sysm
    # And the very first shared turn had nothing to report yet.
    assert "WHAT HAS HAPPENED" not in fm.seen_system[0]


def test_session_ledger_is_derived_and_scoped_to_the_session():
    from dadloop.core import stages
    evs = [
        {"turn_id": "t1", "session_id": "s1", "kind": "turn_start", "user": "swami", "prompt": "ready?"},
        {"turn_id": "t1", "session_id": "s1", "kind": "milestone", "milestone": stages.CONSTRAINT_FOUND,
         "subject": "propane", "detail": "tank empty"},
        {"turn_id": "t1", "session_id": "s1", "kind": "final", "text": "Borrow a tank."},
        {"turn_id": "t1", "session_id": "s1", "kind": "turn_end", "outcome": stages.PARTIAL},
        {"turn_id": "t9", "session_id": "OTHER", "kind": "turn_start", "user": "x", "prompt": "no"},
        {"turn_id": "t2", "session_id": "s1", "kind": "turn_start", "user": "priya", "prompt": "grill?"},
    ]
    rows = stages.session_ledger(evs, "s1")
    assert [r["user"] for r in rows] == ["swami", "priya"]
    assert rows[0]["outcome"] == stages.PARTIAL and rows[0]["constraints"] == ["tank empty"]
    assert rows[0]["reply"] == "Borrow a tank." and rows[1]["outcome"] is None
    note = stages.ledger_note(rows)
    assert 'swami asked: "ready?" -> partial; found: tank empty; Dad said: "Borrow a tank."' in note
    assert 'priya asked: "grill?" -> in progress' in note
    assert stages.ledger_note([]) == ""


# -------------------------------------------------------------- 2. house
def test_house_fans_out_keeps_one_writer_and_briefs_late_joiners():
    client, _ = _fake_client()
    dad = _dad(client)
    house = House(dad, port=0).start()
    try:
        seen_by_b = []
        a = HouseClient(port=house.port, user="swami").connect()
        b = HouseClient(port=house.port, user="priya").connect()
        b.on_other = seen_by_b.append
        time.sleep(0.2)
        assert a.people == ["swami", "priya"], a.people
        assert dad.shared is True

        own = []
        reply = a.turn("are we ready?", on_event=lambda k, p: own.append(k))
        assert "good" in reply
        assert own[:3] == ["tool_call", "plan_step_done", "tool_result"] and "final" in own, own
        time.sleep(0.3)

        kinds = [(f["kind"], f.get("user")) for f in seen_by_b if f.get("turn_id")]
        assert kinds[0] == ("turn_start", "swami"), kinds
        assert kinds[-1] == ("turn_end", "swami"), kinds
        assert ("tool_call", "swami") in kinds, kinds

        b.turn("and the grill?", on_event=lambda *_: None)
        time.sleep(0.2)

        # One writer: seq strictly increasing, both turns attributed.
        events = dad.journal.read_all()
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        assert [e["user"] for e in events if e["kind"] == "turn_start"] == ["swami", "priya"]

        # A late joiner is handed the record, not a summary.
        c = HouseClient(port=house.port, user="late").connect()
        hist = [(f["kind"], f.get("user")) for f in c.history]
        assert hist[0] == ("turn_start", "swami") and ("turn_start", "priya") in hist, hist
        assert c.tracer.totals.turns == 2, c.tracer.totals

        # A joined client sees the house's memory, not its own machine's. The
        # view answers every read the rail and admin screen make, from a
        # snapshot, so it does not matter where the client runs.
        assert c.memory.ledger() == dad.ctx.memory.ledger(), (c.memory.ledger(), dad.ctx.memory.ledger())
        assert c.memory.top_skills() == dad.ctx.memory.top_skills()
        assert [n for n, _ in c.memory.files()] == [n for n, _ in dad.ctx.memory.files()]
        assert c.memory.root == dad.ctx.memory.root
        assert len(c.memory.recall("usage")) == len(dad.ctx.memory.recall("usage"))
        try:
            c.memory.remember("lessons", "nope")
            assert False, "a client must not write memory"
        except PermissionError:
            pass
        # And it refreshes: a turn that files something shows up on the client.
        before = c.memory.ledger()["rulings"] + c.memory.ledger()["grievances"]
        b.turn("what about the budget?", on_event=lambda *_: None)
        time.sleep(0.3)
        after = c.memory.ledger()["rulings"] + c.memory.ledger()["grievances"]
        assert after >= before and c.memory.ledger() == dad.ctx.memory.ledger()
        c.close()
        a.close(); b.close()
    finally:
        house.stop()


def test_two_people_at_once_are_serialised_and_the_second_is_told():
    client, _ = _fake_client(delay=0.15)
    dad = _dad(client)
    house = House(dad, port=0).start()
    try:
        a = HouseClient(port=house.port, user="swami").connect()
        b = HouseClient(port=house.port, user="priya").connect()
        time.sleep(0.1)
        a_events, b_events = [], []
        ta = threading.Thread(target=a.turn, args=("ready?",),
                              kwargs={"on_event": lambda k, p: a_events.append((k, p))})
        tb = threading.Thread(target=b.turn, args=("grill?",),
                              kwargs={"on_event": lambda k, p: b_events.append((k, p))})
        ta.start(); time.sleep(0.05); tb.start()
        ta.join(5); tb.join(5)
        time.sleep(0.2)

        waited = [p for k, p in b_events if k == "waiting"]
        assert waited and "swami" in waited[0], b_events

        # No interleaving: each turn's events are contiguous in the journal.
        events = dad.journal.read_all()
        order = [e["turn_id"] for e in events]
        runs = [order[0]]
        for t in order[1:]:
            if t != runs[-1]:
                runs.append(t)
        assert len(runs) == 2, runs
        a.close(); b.close()
    finally:
        house.stop()


def test_house_is_discoverable_by_session_beside_its_memory():
    from dadloop.house import find_house, house_file
    client, _ = _fake_client()
    dad = _dad(client)
    root = dad.ctx.memory.root
    assert find_house(root) is None
    house = House(dad, port=0).start()
    try:
        info = find_house(root)
        assert info and info["port"] == house.port and info["session_id"] == dad.session_id, info
        assert house_file(root).exists()
    finally:
        house.stop()
    # Gone when the house closes, and a stale file is cleaned up on probe.
    assert not house_file(root).exists()
    # Two houses on one memory would be two journal writers: refused.
    house = House(dad, port=0).start()
    try:
        try:
            House(_dad_on(root), port=0).start()
            assert False, "a second house on the same memory must be refused"
        except RuntimeError as e:
            assert "already running" in str(e)
    finally:
        house.stop()
    house_file(root).write_text('{"host": "127.0.0.1", "port": 1, "session_id": "stale"}')
    assert find_house(root) is None and not house_file(root).exists()


def test_first_dadloop_is_the_house_and_the_second_joins_it():
    """The scenario that motivated this: `dadloop`, then `dadloop --as userX`
    in another terminal. Neither ran --serve. They must be in one session."""
    import os
    from textual.widgets import Markdown
    from dadloop.house import open_or_join, find_house
    from dadloop.tui import DadApp

    home = tempfile.mkdtemp()
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = home                  # Path.home() for memory and house.json
    try:
        assert find_house() is None
        first, house = open_or_join(user="swami")     # plain `dadloop`
        assert house is not None and first.house is house
        assert find_house()["session_id"] == first.session_id
        # Offline Dad here; wire the fake so turns do something.
        client, _ = _fake_client()
        house.dad._client = client

        app = DadApp(first)

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert "with" not in app.sub_title           # alone so far
                # The second person: `dadloop --as userX`, no --serve anywhere.
                second, owned = open_or_join(user="userX")
                assert owned is None and second.session_id == first.session_id
                seen = []
                second.on_other = seen.append
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if "userX" in app.sub_title:
                        break
                assert "userX" in app.sub_title, app.sub_title   # first sees the new user

                # userX asks; the first terminal draws it, attributed.
                threading.Thread(target=second.turn, args=("are we ready?",),
                                 kwargs={"on_event": lambda *_: None}, daemon=True).start()
                for _ in range(80):
                    await asyncio.sleep(0.05)
                    if app._other is None and any("them" in w.classes for w in app.query(Markdown)):
                        break
                await pilot.pause()
                them = [w for w in app.query(Markdown) if "them" in w.classes]
                assert len(them) == 1, len(them)

                # And the first person's ask reaches userX, by name.
                await pilot.click("#input")
                await pilot.press(*"and the grill?")
                await pilot.press("enter")
                for _ in range(80):
                    await asyncio.sleep(0.05)
                    if any(f.get("kind") == "turn_end" and f.get("user") == "swami" for f in seen):
                        break
                assert any(f.get("kind") == "turn_start" and f.get("user") == "swami" for f in seen), \
                    [(f.get("kind"), f.get("user")) for f in seen]
                second.close()

        asyncio.run(scenario())
        # Both turns, both names, one journal.
        users = [e["user"] for e in house.dad.journal.read_all() if e["kind"] == "turn_start"]
        assert users == ["userX", "swami"], users
        first.close(); house.stop()
        assert find_house() is None
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home


def test_a_failing_turn_does_not_take_the_house_down():
    class Boom:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise ConnectionError("proxy said no")
            return NS(content=[NS(type="text", text="Back. We're good.")],
                      usage=NS(input_tokens=5, output_tokens=5))
    dad = _dad(type("FC", (), {"messages": Boom()})())
    house = House(dad, port=0).start()
    try:
        seen = []
        a = HouseClient(port=house.port, user="swami").connect()
        b = HouseClient(port=house.port, user="priya").connect()
        b.on_other = seen.append
        time.sleep(0.1)
        got = []
        reply = a.turn("ready?", on_event=lambda k, p: got.append((k, p)))
        assert "hit an error" in reply and "proxy said no" in reply, reply
        assert any(k == "final" and "hit an error" in p for k, p in got), got
        time.sleep(0.2)
        assert any(f.get("kind") == "turn_end" for f in seen), "the room was told the turn ended"
        # The worker is alive: the next turn runs normally.
        assert "good" in b.turn("still there?", on_event=lambda *_: None)
        log = dad.ctx.memory.root / "house.log"
        assert log.exists() and "proxy said no" in log.read_text()
        a.close(); b.close()
    finally:
        house.stop()


def test_a_clarifying_reply_is_shown_in_the_tui():
    """Dad answered with a question and no tool work: that is a `clarify`
    event, and it must land on the canvas. It never did before 2026-09-05."""
    from textual.widgets import Markdown
    from dadloop.tui import DadApp

    class Asks:
        def create(self, **kw):
            return NS(content=[NS(type="text", text="Where were you thinking of going?")],
                      usage=NS(input_tokens=10, output_tokens=8))

    # Single-user.
    dad = _dad(type("FC", (), {"messages": Asks()})())
    app = DadApp(dad)

    async def solo():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#input")
            await pilot.press(*"plan the winter break")
            await pilot.press("enter")
            for _ in range(60):
                await asyncio.sleep(0.05)
                if any("dad" in w.classes for w in app.query(Markdown)):
                    break
            await pilot.pause()
            dads = [w for w in app.query(Markdown) if "dad" in w.classes]
            assert len(dads) == 1 and "asks" in dads[0].classes, [w.classes for w in app.query(Markdown)]
    asyncio.run(solo())
    assert [e["kind"] for e in dad.journal.read_all() if e["kind"] in ("final", "clarify")] == ["clarify"]

    # Joined: the same reply, over the wire, in the other person's terminal.
    dad2 = _dad(type("FC", (), {"messages": Asks()})())
    house = House(dad2, port=0).start()
    try:
        other = HouseClient(port=house.port, user="priya").connect()
        me = HouseClient(port=house.port, user="swami").connect()
        app2 = DadApp(me)

        async def joined():
            async with app2.run_test() as pilot:
                await pilot.pause()
                threading.Thread(target=other.turn, args=("plan the winter break",),
                                 kwargs={"on_event": lambda *_: None}, daemon=True).start()
                for _ in range(80):
                    await asyncio.sleep(0.05)
                    if app2._other is None and any("dad" in w.classes for w in app2.query(Markdown)):
                        break
                await pilot.pause()
                dads = [w for w in app2.query(Markdown) if "dad" in w.classes]
                assert len(dads) == 1 and "asks" in dads[0].classes
        asyncio.run(joined())
        me.close(); other.close()
    finally:
        house.stop()


def test_a_fact_added_mid_turn_changes_that_turns_own_outcome():
    """The actual claim: a second person hands Dad something while he's still
    working, and it changes what he does before he answers — not after."""
    fm = _GrillThenPantry()
    dad = _dad(type("FC", (), {"messages": fm})())
    house = House(dad, port=0).start()
    try:
        swami = HouseClient(port=house.port, user="swami").connect()
        priya = HouseClient(port=house.port, user="priya").connect()
        seen_by_priya = []
        priya.on_other = seen_by_priya.append
        time.sleep(0.1)

        result = {}
        def ask():
            result["reply"] = swami.turn("is the grill ready for saturday?",
                                         on_event=lambda *_: None)
        t = threading.Thread(target=ask); t.start()
        time.sleep(0.06)                     # after the grill call is dispatched, before it returns
        priya.add_note("Dave's out of propane too, don't bother with the grill")
        t.join(5)

        # Real threads, real sockets: the fact lands on whichever tool-results
        # message it makes it onto in time, not necessarily the very next one.
        # What has to be true is that it lands before the turn concludes, and
        # that the answer reflects it -- not a specific call count.
        assert len(fm.calls) <= 3, fm.calls
        assert "Dave's out of propane too" in result["reply"], result["reply"]
        time.sleep(0.2)

        fact_frames = [f for f in seen_by_priya if f.get("kind") == "fact_added"]
        assert fact_frames and fact_frames[0]["payload"]["from"] == "priya"
        assert fact_frames[0]["user"] == "swami"    # tagged to the turn it landed in

        journaled = [e for e in dad.journal.read_all() if e["kind"] == "fact_added"]
        assert journaled and journaled[0]["user"] == "priya"
        assert journaled[0]["turn_id"] == fact_frames[0]["turn_id"]
        swami.close(); priya.close()
    finally:
        house.stop()


def test_a_note_with_no_turn_running_becomes_an_ordinary_ask():
    client, fm = _fake_client()
    dad = _dad(client)
    house = House(dad, port=0).start()
    try:
        priya = HouseClient(port=house.port, user="priya").connect()
        time.sleep(0.1)
        priya.add_note("just checking in on the cookout")
        time.sleep(0.3)
        starts = [e for e in dad.journal.read_all() if e["kind"] == "turn_start"]
        assert len(starts) == 1 and starts[0]["user"] == "priya" and             starts[0]["prompt"] == "just checking in on the cookout"
        priya.close()
    finally:
        house.stop()


def test_parse_address_is_forgiving():
    assert parse_address(None) == ("127.0.0.1", 8760)
    assert parse_address("192.168.1.9:9000") == ("192.168.1.9", 9000)
    assert parse_address(":9000") == ("127.0.0.1", 9000)
    assert parse_address("laptop") == ("laptop", 8760)


# ---------------------------------------------------------------- 3. TUI
def test_joined_tui_shows_the_other_persons_turn_and_the_catch_up():
    from textual.widgets import Markdown, Collapsible
    from dadloop.tui import DadApp

    client, _ = _fake_client()
    dad = _dad(client)
    house = House(dad, port=0).start()
    try:
        other = HouseClient(port=house.port, user="priya").connect()
        # Something happened before we sat down.
        other.turn("are we ready for the cookout?", on_event=lambda *_: None)
        time.sleep(0.2)

        me = HouseClient(port=house.port, user="swami").connect()
        app = DadApp(me)

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Catch-up: her earlier ask, by name, and Dad's answer.
                mds = [w for w in app.query(Markdown)]
                assert any("them" in w.classes for w in mds), [w.classes for w in mds]
                assert any("dad" in w.classes for w in mds)
                assert not app.query_one("#input").disabled

                # Now she asks again while we watch.
                threading.Thread(target=other.turn, args=("and the grill?",),
                                 kwargs={"on_event": lambda *_: None}, daemon=True).start()
                for _ in range(60):
                    await asyncio.sleep(0.05)
                    if len(list(app.query(Collapsible))) >= 1 and app._other is None:
                        break
                await pilot.pause()
                steps = list(app.query(Collapsible))
                assert len(steps) == 1, f"expected her tool call as a step, got {len(steps)}"
                them = [w for w in app.query(Markdown) if "them" in w.classes]
                assert len(them) == 2, len(them)
                # Watching never locks your own prompt.
                assert not app.query_one("#input").disabled
                assert "priya" in app.sub_title, app.sub_title

        asyncio.run(scenario())
        me.close(); other.close()
    finally:
        house.stop()


def test_a_note_is_shown_live_in_the_watching_tui():
    """One real TUI, watching a real turn in progress; a second person (a
    plain client, not a second full Textual app -- two Textual apps racing to
    render on one event loop is a test-harness artifact, not anything a real
    terminal does) adds a fact partway through. Proves what actually renders:
    the note appears inline, attributed, while the turn is still running, and
    the reply that follows reflects it -- all on the one canvas a person
    would actually be looking at."""
    from textual.widgets import Static, Markdown
    from dadloop.tui import DadApp

    fm = _GrillThenPantry(model_delay=0.25)
    dad = _dad(type("FC", (), {"messages": fm})())
    house = House(dad, port=0).start()
    try:
        swami = HouseClient(port=house.port, user="swami").connect()
        priya = HouseClient(port=house.port, user="priya").connect()
        app = DadApp(swami)

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#input")
                for ch in "is the grill ready for saturday?":
                    await pilot.press(ch)
                await pilot.press("enter")

                # priya adds her fact from an ordinary thread, timed to land
                # after the grill check is dispatched and before the turn
                # concludes -- exactly the window inject_fact() opens.
                def add_it():
                    time.sleep(0.15)
                    priya.add_note("Dave's out of propane too, don't bother with the grill")
                threading.Thread(target=add_it, daemon=True).start()

                for _ in range(150):
                    await asyncio.sleep(0.05)
                    if app._status is None:
                        break
                await pilot.pause()

                facts = [w for w in app.query(Static) if "fact-added" in w.classes]
                assert facts, "the note never rendered"
                assert "priya added" in str(facts[0].render()), str(facts[0].render())

                dads = [w for w in app.query(Markdown) if "dad" in w.classes]
                assert dads, "no reply shown"
                assert "Dave's out of propane too" in dads[-1].source, dads[-1].source

        asyncio.run(scenario())
        assert len(fm.calls) <= 3, fm.calls
        swami.close(); priya.close()
    finally:
        house.stop()


if __name__ == "__main__":
    test_turn_start_carries_user_and_single_user_is_unchanged()
    test_shared_house_tells_dad_who_is_speaking()
    test_house_fans_out_keeps_one_writer_and_briefs_late_joiners()
    test_session_ledger_is_derived_and_scoped_to_the_session()
    test_two_people_at_once_are_serialised_and_the_second_is_told()
    test_house_is_discoverable_by_session_beside_its_memory()
    test_first_dadloop_is_the_house_and_the_second_joins_it()
    test_a_failing_turn_does_not_take_the_house_down()
    test_a_clarifying_reply_is_shown_in_the_tui()
    test_a_fact_added_mid_turn_changes_that_turns_own_outcome()
    test_a_note_with_no_turn_running_becomes_an_ordinary_ask()
    test_a_note_is_shown_live_in_the_watching_tui()
    test_parse_address_is_forgiving()
    test_joined_tui_shows_the_other_persons_turn_and_the_catch_up()
    print("ok")
