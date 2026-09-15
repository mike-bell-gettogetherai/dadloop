"""Author: Swami Chandrasekaran
Last Modified: 2026-09-02
Purpose: Append-only turn journal — the durable event log a turn leaves behind.

dadloop already emits a rich stream of what a turn is doing (plan, tool_call,
tool_result, controller, final). Until now that stream was in-process only: the
TUI rendered it and it was gone. This module writes it down.

Two things follow from persisting it. A turn becomes replayable, which makes
debugging a bad turn possible after the fact instead of only while it happens.
And a separate reader — an observability console, a script, anything — can watch
the harness without importing it. The journal is the contract: dadloop writes,
it does not care who reads.

The log is append-only on purpose. Current state is a fold over the events, not
a mutable record, so a reader that arrives late can reconstruct everything by
replaying from the top, and two readers can never disagree.

Nothing here is allowed to break a turn. Every write is best-effort: if the disk
is full or the path is unwritable, the turn continues and the journal silently
loses events. Observability that can take down the thing it observes is worse
than no observability.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Roll over at 8MB. Big enough that a heavy session stays in one file, small
# enough that a reader can hold one in memory without thinking about it.
_MAX_BYTES = 8 * 1024 * 1024
_KEEP_FILES = 5


def new_turn_id() -> str:
    """A turn id that sorts chronologically and never collides.

    ISO second-resolution prefix so a human scanning the file can find a turn by
    when it happened; a short random suffix because two turns can start inside
    the same second.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return f"{stamp}-{uuid.uuid4().hex[:4]}"


@dataclass
class Journal:
    """Append-only JSONL sink for turn events.

    `seq` is per-journal and monotonic, not per-turn, so a tier 2 event can point
    at the exact tier 1 event that caused it with `caused_by_seq` and a reader
    can resolve that pointer without scanning turn boundaries.
    """

    path: Path
    _seq: int = field(default=0, init=False)
    enabled: bool = True

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Can't even make the directory. Degrade to a no-op rather than
            # taking the harness down over a log file.
            self.enabled = False
            return
        # seq must be unique across the WHOLE file, not just this process. A
        # restarted harness opening an existing journal has to pick up where the
        # last one left off, otherwise it writes seq 1, 2, 3 into a file that
        # already has seq 1, 2, 3 — and every caused_by_seq pointer from that
        # point on can resolve to an event from a different session. That would
        # silently break the one guarantee the console rests on: that a derived
        # claim always names the real mechanical event underneath it.
        self._seq = self._last_seq_on_disk()

    def _last_seq_on_disk(self) -> int:
        """Highest seq already in the file, or 0 for a new journal.

        Reads from the tail rather than parsing the whole file, since a journal
        can be megabytes and this runs on every construction.
        """
        try:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return 0
            with self.path.open("rb") as f:
                # Walk back far enough to be sure of catching one complete line.
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", errors="ignore")
            for line in reversed(tail.strip().splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    return int(json.loads(line).get("seq", 0))
                except (ValueError, AttributeError):
                    continue        # a torn line; keep looking
            return 0
        except OSError:
            return 0

    # -- writing ---------------------------------------------------------
    def write(self, event: dict) -> int | None:
        """Append one event. Returns its seq, or None if the write was dropped.

        The returned seq is what a derived (tier 2) event stores in
        `caused_by_seq`, which is what makes every business-level claim on the
        console traceable back to the mechanical fact underneath it.
        """
        if not self.enabled:
            return None
        self._seq += 1
        event = {"seq": self._seq, "ts": event.pop("ts", time.time()), **event}
        try:
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            # Best effort. A turn must never fail because of its own logging.
            return None
        return self._seq

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.exists() or self.path.stat().st_size < _MAX_BYTES:
                return
        except OSError:
            return
        # journal.jsonl -> journal.1.jsonl, shifting older ones down and
        # dropping the oldest.
        for i in range(_KEEP_FILES - 1, 0, -1):
            src = self.path.with_suffix(f".{i}.jsonl")
            dst = self.path.with_suffix(f".{i + 1}.jsonl")
            if src.exists():
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.replace(self.path, self.path.with_suffix(".1.jsonl"))
        except OSError:
            pass

    # -- reading ---------------------------------------------------------
    def read_all(self) -> list[dict]:
        """Every event in the current file, oldest first.

        Convenience for tests and for replaying a turn in the terminal. A real
        console tails the file instead of loading it.
        """
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue        # a torn final line; skip it
        return out

    def read_turn(self, turn_id: str) -> list[dict]:
        """Just one turn's events, in order — what replay needs."""
        return [e for e in self.read_all() if e.get("turn_id") == turn_id]


def default_path(memory_root=None) -> Path:
    """Where the journal lives unless told otherwise.

    Beside the memory it describes, not in a global location. A household's
    events and a household's memory are the same story, so a console points at
    one directory to read an instance. It also means anything running against a
    temporary memory (tests, demos) gets a temporary journal for free, instead
    of writing into the real one.
    """
    env = os.environ.get("DADLOOP_JOURNAL")
    if env:
        return Path(env).expanduser()
    if memory_root is not None:
        return Path(memory_root) / "journal.jsonl"
    return Path.home() / ".dadloop" / "memory" / "journal.jsonl"
