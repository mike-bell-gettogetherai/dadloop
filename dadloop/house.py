"""Author: Swami Chandrasekaran
Last Modified: 2026-09-06
Purpose: One Dad, several people. The house server and the client the TUI uses to join it.

There is one Dad in a house. `dadloop --serve` runs him behind a plain TCP
socket; `dadloop --join` opens a TUI that talks to that Dad instead of owning
one. Two people at two terminals then share one conversation, one memory, one
journal and one Mom, and Dad is the one who knows what both of them asked for.

Design, in order of what it protects:

- Still one writer. Turns queue and run one at a time on one thread, so the
  journal's `seq` never sees two writers and Mom is never answering two people
  at once.
- Everyone sees every turn. Each event fans out to every connected client as it
  happens, tagged with who caused it. The other person's work appears in your
  TUI the same way your own does.
- Nothing new in core. `AgentLoop` gained `user` on turn() and a `shared`
  flag. That is the whole footprint under dadloop/core/. This file is a
  transport around it, and the single-process path (TUI, REPL, tests) never
  imports it.
- Stdlib only. JSON lines over a socket. No framework, nothing to install.

Wire protocol, one JSON object per line:

    client -> house   {"hello": "priya"}
                      {"say": "are we ready for the cookout?"}
    house  -> client  {"kind": "welcome", "you": 2, "user": "priya",
                       "session_id": ..., "online": true, "people": [...],
                       "history": [frames...]}
                      {"kind": "presence", "people": ["swami", "priya"]}
                      {"kind": "queued", "by": 2, "user": "priya", "behind": "swami"}
                      {"kind": <turn event>, "payload": ..., "by": 1,
                       "user": "swami", "turn_id": ...}

Turn events are the same nine kinds `AgentLoop.turn()` emits, with the same
payloads, plus `turn_start` (payload: the prompt) and `turn_end` (payload:
final text, milestones, totals, state, and a snapshot of memory). `by` is the
client id that caused the turn; a client compares it with its own id from
`welcome` to tell its turns from everyone else's.

A note is not a new turn. It only exists to be handed to whichever turn is
running right now, mid-flight, the way a person leans over and adds what they
know before the first person finishes: `AgentLoop.inject_fact()` folds it into
the next thing the model sees. If nobody's turn is running when a note
arrives, or it arrives too late to be picked up, the house queues it as an
ordinary ask instead so nothing is lost — it just stops being a mid-turn
addition and becomes the next turn.

A joined client never reads the house's disk. Memory arrives as a snapshot in
`welcome` and in every `turn_end`, and `MemoryView` serves it through the same
read methods `SemanticMemory` has. So the session is the unit, and it does not
matter which machine a terminal is on.

Finding the house: while it runs, the house writes `house.json` beside the
memory it uses (host, port, pid, session_id). `dadloop` with no flags looks
for that file, checks the house is alive, and joins it. If there is none, the
first `dadloop` opens a house itself, in its own process, and joins it as the
first client; the next `dadloop` on the machine finds that one. So nobody
needs `--serve` to share a Dad; `--serve` is for a house that should outlive
any one terminal. `dadloop --solo` is the old single-user TUI with no house.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Callable

from .core.agent import AgentLoop, default_user
from .core.context import Context
from .core.controller import Mom
from .core.memory import CATEGORIES, MemoryEntry
from .core.trace import SessionTotals, Tracer

DEFAULT_PORT = 8760
_HISTORY_MAX = 4000      # frames kept for late joiners; a session, not an archive
_TURN_KINDS = ("thinking", "plan", "plan_step_done", "tool_call", "tool_result",
               "controller", "clarify", "final", "trace", "fact_added")


# ---------------------------------------------------------------------- wire
def _send(sock: socket.socket, frame: dict) -> None:
    sock.sendall((json.dumps(frame, default=str) + "\n").encode("utf-8"))


def _lines(sock: socket.socket):
    """Yield one decoded JSON object per line until the peer goes away."""
    buf = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except ValueError:
                continue


# --------------------------------------------------------------- memory view
def memory_snapshot(memory) -> dict:
    """Everything a reader of memory needs, as plain data. Small: a household's
    memory is a few hundred lines of text at most."""
    out = {"root": str(getattr(memory, "root", "")), "entries": {}}
    for cat in CATEGORIES:
        try:
            out["entries"][cat] = [dataclasses.asdict(e) for e in memory.recall(cat)]
        except Exception:
            out["entries"][cat] = []
    return out


class MemoryView:
    """Read-only SemanticMemory shaped over a snapshot from the house.

    The rail, the admin screen and the skill-health panel read memory through
    `recall`, `ledger`, `top_skills`, `files` and `root`. All are served from
    the snapshot, so a joined TUI shows the house's memory wherever it runs.
    Writes are refused: a client never touches the record.
    """

    def __init__(self, snapshot: dict | None = None) -> None:
        self._entries: dict[str, list[MemoryEntry]] = {c: [] for c in CATEGORIES}
        self.root = Path("house")
        if snapshot:
            self.update(snapshot)

    def update(self, snapshot: dict) -> None:
        root = snapshot.get("root")
        if root:
            self.root = Path(root)
        for cat in CATEGORIES:
            rows = (snapshot.get("entries") or {}).get(cat) or []
            self._entries[cat] = [MemoryEntry(**{k: r.get(k) for k in ("text", "category", "tags", "ts")
                                                 if k in r}) for r in rows]

    def recall(self, category: str) -> list[MemoryEntry]:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown memory category: {category!r}")
        return list(self._entries[category])

    def search(self, query: str) -> list[MemoryEntry]:
        q = query.lower()
        return [e for cat in CATEGORIES for e in self._entries[cat]
                if q in e.text.lower() or any(q in t.lower() for t in e.tags)]

    def ledger(self) -> dict[str, int]:
        skip = {"usage", "outcomes"}
        return {cat: len(self._entries[cat]) for cat in CATEGORIES if cat not in skip}

    def top_skills(self, limit: int = 5) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for e in self._entries["usage"]:
            if e.text.startswith("skill:"):
                name = e.text.split(":", 1)[1]
                counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    def files(self) -> list[tuple[str, int]]:
        out = []
        for cat in CATEGORIES:
            size = sum(len(json.dumps(dataclasses.asdict(e))) + 1 for e in self._entries[cat])
            out.append((f"{cat}.jsonl", size))
        return out

    def remember(self, *a, **kw):
        raise PermissionError("a joined TUI does not write memory; the house does")

    record_use = remember


# ----------------------------------------------------------------- discovery
def house_file(memory_root: Path | None = None) -> Path:
    root = Path(memory_root) if memory_root is not None else Path.home() / ".dadloop" / "memory"
    return root / "house.json"


def find_house(memory_root: Path | None = None, timeout: float = 0.5) -> dict | None:
    """The running house for this memory, or None.

    Reads house.json and confirms something is listening. A stale file (the
    house died without cleaning up) is removed so the next start does not
    keep tripping over it.
    """
    path = house_file(memory_root)
    try:
        info = json.loads(path.read_text())
        host, port = info["host"], int(info["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    probe = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        with socket.create_connection((probe, port), timeout=timeout):
            pass
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    info["host"] = probe
    return info


# --------------------------------------------------------------------- house
class House:
    """Runs one AgentLoop for everyone who connects.

    `dad.shared` is set here, which is what makes every user message carry its
    speaker's name and tells Dad to catch a second person asking for what the
    first already got. The single-user AgentLoop never sees that flag.
    """

    def __init__(self, dad: AgentLoop, host: str = "127.0.0.1",
                 port: int = DEFAULT_PORT) -> None:
        self.dad = dad
        self.dad.shared = True
        self.host, self.port = host, port
        # cid -> (socket, name, outbound queue). One lock guards the client
        # table, the history and the busy state together, so a joiner's
        # welcome and the frames that follow it are never reordered or
        # duplicated. Each client has a writer thread draining its queue, so
        # the lock is never held during network I/O and one slow client cannot
        # stall the house.
        self._clients: dict[int, tuple[socket.socket, str, "queue.Queue[dict | None]"]] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._turns: "queue.Queue[tuple[int, str, str] | None]" = queue.Queue()
        self._history: list[dict] = []
        self._busy_with: str | None = None
        self._busy_cid: int | None = None
        self._waiting = 0                  # turns queued behind the running one
        self._srv: socket.socket | None = None
        self._stopping = threading.Event()
        self._file: Path | None = None

    # -- lifecycle -------------------------------------------------------
    def start(self) -> "House":
        """Bind, then run the accept loop and the turn worker on threads.
        Returns self so `House(dad).start()` reads naturally.

        Refuses if a house is already running for this memory: that would be
        two Dads writing one journal, which is the thing this file exists to
        prevent. The message says how to join the one that exists."""
        root = getattr(self.dad.ctx.memory, "root", None)
        existing = find_house(root) if root is not None else None
        if existing is not None:
            raise RuntimeError(
                f"A house is already running for {root} "
                f"(session {existing.get('session_id')}, port {existing.get('port')}). "
                "Join it with `dadloop` or `dadloop --join`; stop it before starting another.")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Reuse a just-closed port on POSIX. On Windows SO_REUSEADDR lets two
        # listeners share one port, which is the opposite of what a house
        # wants, so ask for exclusive use there instead.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen()
        self.port = srv.getsockname()[1]      # resolves port 0 for tests
        self._srv = srv
        self._write_house_file()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._turn_worker, daemon=True).start()
        return self

    def _write_house_file(self) -> None:
        """Beside the memory this Dad uses, so `dadloop` on this machine finds
        the session instead of starting a second Dad on the same files."""
        root = getattr(self.dad.ctx.memory, "root", None)
        if root is None:
            return
        self._file = house_file(root)
        try:
            self._file.write_text(json.dumps({
                "host": self.host, "port": self.port, "pid": os.getpid(),
                "session_id": self.dad.session_id, "started": time.time()}))
        except OSError:
            self._file = None

    def serve_forever(self) -> None:
        try:
            while not self._stopping.is_set():
                self._stopping.wait(0.5)      # a timed wait stays interruptible
        except KeyboardInterrupt:
            pass
        self.stop()

    def stop(self) -> None:
        self._stopping.set()
        self._turns.put(None)
        if self._file is not None:
            try:
                self._file.unlink()
            except OSError:
                pass
            self._file = None
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        with self._lock:
            entries = list(self._clients.values())
            self._clients.clear()
        for sock, _, q in entries:
            q.put(None)
            try:
                sock.close()
            except OSError:
                pass

    @property
    def people(self) -> list[str]:
        with self._lock:
            return self._people_locked()

    def _people_locked(self) -> list[str]:
        return list(dict.fromkeys(name for _, name, _ in self._clients.values()))

    # -- clients ---------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                sock, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._client_loop, args=(sock,), daemon=True).start()

    def _client_loop(self, sock: socket.socket) -> None:
        frames = _lines(sock)
        hello = next(frames, None)
        if not isinstance(hello, dict) or "hello" not in hello:
            sock.close()
            return
        name = str(hello.get("hello") or "").strip() or "someone"
        outbound: "queue.Queue[dict | None]" = queue.Queue()
        memory = memory_snapshot(self.dad.ctx.memory)
        with self._lock:
            cid = self._next_id
            self._next_id += 1
            self._clients[cid] = (sock, name, outbound)
            # Welcome goes on the queue inside the lock, with the history as it
            # stands right now; any broadcast after this point lands behind it.
            outbound.put({"kind": "welcome", "you": cid, "user": name,
                          "session_id": self.dad.session_id, "online": self.dad.online,
                          "model": self.dad.model, "people": self._people_locked(),
                          "memory": memory, "busy_with": self._busy_with,
                          "history": list(self._history)})
        threading.Thread(target=self._writer, args=(cid, sock, outbound), daemon=True).start()
        self._broadcast({"kind": "presence", "people": self.people})
        try:
            for frame in frames:
                if isinstance(frame, dict) and frame.get("note") is not None:
                    note = str(frame["note"]).strip()
                    if not note:
                        continue
                    with self._lock:
                        busy_with, busy_cid = self._busy_with, self._busy_cid
                    if busy_with is not None and busy_with != name and                             self.dad.inject_fact(note, name):
                        self._broadcast({"kind": "fact_added",
                                         "payload": {"from": name, "text": note},
                                         "by": busy_cid, "user": busy_with,
                                         "turn_id": getattr(self.dad, "_turn_id", None)})
                        continue
                    # Nobody's turn was running, or it wrapped up in the gap
                    # between the person hitting enter and this landing. Rather
                    # than drop what they said, it becomes a normal ask.
                    text = note
                else:
                    text = str(frame.get("say") or "").strip() if isinstance(frame, dict) else ""
                if not text:
                    continue
                with self._lock:
                    behind = self._busy_with if (self._busy_with or self._waiting) else None
                    self._waiting += 1
                if behind is not None:
                    self._broadcast({"kind": "queued", "by": cid, "user": name,
                                     "behind": behind})
                # The name travels with the request, so a person who asks and
                # then closes their terminal is still the one who asked.
                self._turns.put((cid, name, text))
        finally:
            self._drop(cid)

    def _writer(self, cid: int, sock: socket.socket, outbound: "queue.Queue[dict | None]") -> None:
        """One thread per client owns its socket for writing."""
        while True:
            frame = outbound.get()
            if frame is None:
                return
            try:
                _send(sock, frame)
            except OSError:
                self._drop(cid)
                return

    def _drop(self, cid: int) -> None:
        with self._lock:
            entry = self._clients.pop(cid, None)
        if entry is None:
            return
        sock, _, outbound = entry
        outbound.put(None)
        try:
            sock.close()
        except OSError:
            pass
        self._broadcast({"kind": "presence", "people": self.people})

    def _broadcast(self, frame: dict) -> None:
        # Presence and queue notices are about the room, not about Dad's work,
        # and are not kept for late joiners. Turn frames are the record.
        with self._lock:
            if frame.get("turn_id"):
                self._history.append(frame)
                del self._history[:-_HISTORY_MAX]
            for _, _, outbound in self._clients.values():
                outbound.put(frame)

    # -- the one thread that runs turns ----------------------------------
    def _turn_worker(self) -> None:
        while True:
            item = self._turns.get()
            if item is None:
                return
            cid, name, text = item
            with self._lock:
                self._busy_with = name
                self._busy_cid = cid
                self._waiting = max(0, self._waiting - 1)
            try:
                self._run_turn(cid, name, text)
            finally:
                with self._lock:
                    self._busy_with = None
                    self._busy_cid = None

    def _run_turn(self, cid: int, name: str, text: str) -> None:
        # turn_id is minted inside turn() and set on the agent before the first
        # event fires, so every frame can carry it.
        tag = {"by": cid, "user": name}
        started = threading.Event()

        def on_event(kind, payload):
            frame = {"kind": kind, "payload": payload, **tag}
            tid = getattr(self.dad, "_turn_id", None)
            if not started.is_set():
                started.set()
                # turn_start is written straight to the journal by turn(); the
                # room gets its own copy, ahead of the first event.
                self._broadcast({"kind": "turn_start", "payload": text, "turn_id": tid, **tag})
            frame["turn_id"] = tid
            self._broadcast(frame)

        try:
            final = self.dad.turn(text, on_event=on_event, user=name)
        except Exception as e:                       # noqa: BLE001
            # The turn worker must outlive any one turn. Say what happened to
            # everyone in the room, log it beside the memory, and carry on with
            # the next request instead of leaving every TUI on "Thinking".
            final = f"(Dad hit an error and stopped this turn: {type(e).__name__}: {e})"
            self._log(f"turn by {name} failed: {type(e).__name__}: {e}")
            tid = getattr(self.dad, "_turn_id", None)
            if not started.is_set():
                started.set()
                self._broadcast({"kind": "turn_start", "payload": text, "turn_id": tid, **tag})
            self._broadcast({"kind": "final", "payload": final, "turn_id": tid, **tag})
        tid = getattr(self.dad, "_turn_id", None)
        if not started.is_set():       # a turn that emitted nothing at all
            self._broadcast({"kind": "turn_start", "payload": text, "turn_id": tid, **tag})
        self._broadcast({"kind": "turn_end", "turn_id": tid, **tag,
                         "payload": {"text": final,
                                     "milestones": self._milestones(tid),
                                     "totals": dataclasses.asdict(self.dad.tracer.totals),
                                     "state": {"thermostat_setpoint": self.dad.ctx.state.thermostat_setpoint,
                                               "dad_jokes_told": self.dad.ctx.state.dad_jokes_told},
                                     "memory": memory_snapshot(self.dad.ctx.memory)}})

    def _log(self, line: str) -> None:
        """Append to house.log beside the memory. The TUI has no stderr worth
        reading, so this is where a failed turn leaves its trace."""
        root = getattr(self.dad.ctx.memory, "root", None)
        if root is None:
            return
        try:
            import traceback
            with (Path(root) / "house.log").open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass

    def _milestones(self, turn_id) -> list[dict]:
        """The derived, business-level record of the turn, for the catch-up view.
        Read back from the journal so it is the same list the console shows."""
        j = self.dad.journal
        if j is None or turn_id is None:
            return []
        try:
            return [{"milestone": e.get("milestone"), "subject": e.get("subject"),
                     "detail": e.get("detail")}
                    for e in j.read_turn(turn_id) if e.get("kind") == "milestone"]
        except Exception:
            return []


# -------------------------------------------------------------------- client
class HouseClient:
    """What the TUI holds when it has joined a house instead of owning a Dad.

    Offers the slice of AgentLoop the TUI actually uses: `turn()`, `online`,
    `model`, `session_id`, `ctx`, `mom`, `tracer`. `ctx.memory` is a MemoryView
    over the house's snapshot, refreshed on every turn_end, so nothing here
    depends on which machine this runs on. `tracer.totals` is filled from the
    house's turn_end frames rather than measured locally.

    Frames for turns this client did not start go to `on_other(frame)`, as do
    presence and queue notices. The TUI renders them like its own turns.
    """

    joined = True

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 user: str | None = None) -> None:
        self.host, self.port = host, port
        self.user = user or default_user()
        self.you: int | None = None
        self.session_id: str = ""
        self.online: bool = False
        self.model: str = ""
        self.people: list[str] = []
        self.busy_with: str | None = None
        self.history: list[dict] = []
        self.memory = MemoryView()
        self.ctx = Context(memory=self.memory)  # hydrates from the view, never from disk
        self.mom = Mom()
        self.tracer = Tracer()
        self._client = None                      # no direct model access here
        self.house: "House | None" = None         # set when this process owns the house
        self.on_other: Callable[[dict], None] | None = None
        self._sock: socket.socket | None = None
        self._own: "queue.Queue[dict]" = queue.Queue()
        self._alive = False

    # -- connection ------------------------------------------------------
    def connect(self, timeout: float = 5.0) -> "HouseClient":
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.settimeout(None)
        _send(sock, {"hello": self.user})
        frames = _lines(sock)
        welcome = next(frames, None)
        if not isinstance(welcome, dict) or welcome.get("kind") != "welcome":
            sock.close()
            raise ConnectionError("that is not a dadloop house")
        self._sock = sock
        self.you = welcome.get("you")
        self.session_id = welcome.get("session_id", "")
        self.online = bool(welcome.get("online"))
        self.model = welcome.get("model", "")
        self.people = list(welcome.get("people") or [])
        self.busy_with = welcome.get("busy_with")
        if isinstance(welcome.get("memory"), dict):
            self.memory.update(welcome["memory"])
        self.history = list(welcome.get("history") or [])
        self._apply_totals_from(self.history)
        self._alive = True
        threading.Thread(target=self._reader, args=(frames,), daemon=True).start()
        return self

    def close(self) -> None:
        self._alive = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def _reader(self, frames) -> None:
        for frame in frames:
            kind = frame.get("kind")
            if kind == "presence":
                self.people = list(frame.get("people") or [])
            elif kind == "turn_end":
                self._absorb_turn_end(frame)
            if frame.get("by") == self.you and kind != "presence":
                self._own.put(frame)
                continue
            if self.on_other is not None:
                try:
                    self.on_other(frame)
                except Exception:
                    pass
        # The house went away.
        self._alive = False
        self.online = False
        self._own.put({"kind": "turn_end", "payload": {
            "text": "(The house closed. Start it again with `dadloop --serve`.)"}})
        if self.on_other is not None:
            self.on_other({"kind": "presence", "people": []})

    def _absorb_turn_end(self, frame: dict) -> None:
        p = frame.get("payload") or {}
        totals = p.get("totals")
        if isinstance(totals, dict):
            t = SessionTotals()
            for k, v in totals.items():
                if hasattr(t, k):
                    setattr(t, k, v)
            self.tracer.totals = t
        state = p.get("state") or {}
        for k in ("thermostat_setpoint", "dad_jokes_told"):
            if k in state:
                setattr(self.ctx.state, k, state[k])
        if isinstance(p.get("memory"), dict):
            self.memory.update(p["memory"])

    def _apply_totals_from(self, frames: list[dict]) -> None:
        for f in frames:
            if f.get("kind") == "turn_end":
                self._absorb_turn_end(f)

    # -- the AgentLoop-shaped surface -------------------------------------
    def add_note(self, text: str) -> None:
        """Hand something to whoever's turn is running right now, without
        starting one of your own. Fire-and-forget: the note either lands
        inline in the running turn (you'll see it arrive as a `fact_added`
        event, same as everyone else watching) or, if there was nothing to
        land in, the house quietly runs it as an ordinary turn instead — so
        there's nothing to wait for here either way."""
        if not self._alive or self._sock is None:
            return
        try:
            _send(self._sock, {"note": text})
        except OSError:
            pass

    def turn(self, user_text: str, *, on_event=None, user: str | None = None) -> str:
        """Ask the house to run a turn and relay its events until it ends.

        Blocks like AgentLoop.turn() does, so the TUI's worker needs no change.
        A `queued` notice is relayed as ("waiting", text) so the status line can
        say whose request Dad is finishing first.
        """
        emit = on_event or (lambda *_: None)
        if not self._alive or self._sock is None:
            msg = "(Not connected to a house. `dadloop --serve` in another terminal.)"
            emit("final", msg)
            return msg
        try:
            _send(self._sock, {"say": user_text})
        except OSError:
            msg = "(Lost the house mid-sentence.)"
            emit("final", msg)
            return msg
        while True:
            frame = self._own.get()
            kind = frame.get("kind")
            if kind == "queued":
                emit("waiting", f"Dad is finishing {frame.get('behind')}'s request first")
            elif kind == "turn_end":
                return str((frame.get("payload") or {}).get("text", ""))
            elif kind in _TURN_KINDS:
                emit(kind, frame.get("payload"))
            # turn_start for our own turn: the TUI already drew the prompt.


# ---------------------------------------------------------------------- cli
def open_or_join(user: str | None = None, address: str | None = None):
    """What plain `dadloop` does. Returns (client, house_or_None).

    Join the house at `address`, or the one running for this machine's memory.
    If there is none, open one here on a free port (house.json carries the
    port, so the number does not matter) and join it. The returned house is
    not None only when this process owns it; the caller stops it on exit.
    """
    if address:
        host, port = parse_address(address)
        return HouseClient(host, port, user=user).connect(), None
    found = find_house()
    if found is not None:
        return HouseClient(found["host"], int(found["port"]), user=user).connect(), None
    dad = AgentLoop()
    house = House(dad, port=0).start()
    client = HouseClient("127.0.0.1", house.port, user=user).connect()
    client.house = house
    return client, house


def serve(dad: AgentLoop, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    """`dadloop --serve`. Prints where to join and runs until Ctrl-C."""
    try:
        house = House(dad, host, port).start()
    except RuntimeError as e:
        raise SystemExit(str(e))
    except OSError as e:
        raise SystemExit(f"Could not open the house on {host}:{port}: {e}")
    # A plain kill should still take the house file with it; a stale file is
    # tolerated by find_house, but not leaving one is better.
    import signal
    try:
        signal.signal(signal.SIGTERM, lambda *_: house.stop())
    except (ValueError, OSError):
        pass
    status = "online" if dad.online else "offline - no API key"
    print(f"dadloop house  ·  {status}  ·  session {dad.session_id}")
    print("anyone on this machine who runs `dadloop` now joins this session.")
    print(f"join from another terminal:  dadloop --join {host}:{house.port} --as <name>")
    print("Ctrl-C to close the house.\n")
    try:
        house.serve_forever()
    except KeyboardInterrupt:
        house.stop()
    print("\nHouse closed.")


def parse_address(text: str | None, default_host: str = "127.0.0.1",
                  default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    """'host:port', 'host', ':port' or None. Forgiving on purpose; this is typed
    by a person at a prompt."""
    if not text:
        return default_host, default_port
    host, _, port = text.rpartition(":")
    if not _:
        return (text or default_host), default_port
    return (host or default_host), int(port or default_port)
