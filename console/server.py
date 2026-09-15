"""Author: Swami Chandrasekaran
Last Modified: 2026-09-13
Purpose: Mom's Console backend — serves the household's journal to a browser.

This is the reader half of the observability contract. dadloop writes an
append-only journal beside each household's memory; this reads it and nothing
else. It imports `journal` and `stages` for their formats, never the agent, so
the console can never affect a turn it is watching.

Two modes matter and they are the same code path. Live tails the file and pushes
new events over a websocket. Replay serves a finished turn from the top so you
can scrub it. Because the journal is append-only, current state is just a fold
over events, which is what makes both modes fall out of one implementation.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dadloop.core import journal as jrnl
from dadloop.core import memory
from dadloop.core import stages

_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Mom's Console")

# Set by main() so the websocket poller can see a shutdown coming and leave on
# its own, instead of being force-cancelled by uvicorn and logged as an error.
_SERVER = None


def _journal_path() -> Path:
    return jrnl.default_path()


def _events() -> list[dict]:
    return jrnl.Journal(_journal_path()).read_all()


def _turn_index(events: list[dict]) -> list[dict]:
    """One summary row per turn, newest first.

    Built by folding the log rather than kept as state, so a console started
    halfway through a session sees the same history as one that watched it all.
    """
    turns: dict[str, dict] = {}
    for e in events:
        tid = e.get("turn_id")
        if not tid:
            continue
        t = turns.setdefault(tid, {
            "turn_id": tid, "prompt": "", "user": None, "ts": e.get("ts"),
            "outcome": None, "governed_down": False, "stages": [],
            "constraints": [], "events": 0,
        })
        t["events"] += 1
        if e.get("kind") == "turn_start":
            t["prompt"] = e.get("prompt", "")
            t["user"] = e.get("user")      # who asked; absent on pre-attribution data
            t["ts"] = e.get("ts")
        elif e.get("kind") == "turn_end":
            t["outcome"] = e.get("outcome")
            t["governed_down"] = e.get("governed_down", False)
            t["stages"] = e.get("stage_history", [])
            t["constraints"] = e.get("constraints_open", [])
    return sorted(turns.values(), key=lambda t: t.get("ts") or 0, reverse=True)


def _friendly(cat: str, row: dict) -> str:
    """A readable line for a category whose stored `text` is not itself prose.

    `usage` and `outcomes` are the harness's own telemetry (skill loads, RSI
    gate results, per-turn grounded outcomes) rather than something Dad wrote
    in plain language, so they need translating before a person should read
    them. Every other category's `text` is already what a person would want
    to see, so this only runs for these two. `row["text"]` is left exactly as
    written either way -- this is a display value, never a rewrite of the
    record.
    """
    text = row.get("text", "")
    if cat == "usage":
        if text.startswith("rsi-gate:"):
            rest = text[len("rsi-gate:"):]
            skill, _, verdict = rest.rpartition(":")
            return f"{skill or rest} — self-improvement gate: {verdict or rest}"
        if text.startswith("skill:"):
            return f"Loaded skill: {text.split(':', 1)[1]}"
        return text
    if cat == "outcomes":
        try:
            rec = json.loads(text)
        except ValueError:
            return text
        bits = (f"{rec.get('skill', '?')} — {rec.get('plan_done', 0)}/{rec.get('plan_steps', 0)} steps",
               f"{rec.get('tool_calls', 0)} tools ({rec.get('tool_errors', 0)} errors)",
               f"{rec.get('vetoes', 0)} vetoes",
               f"${rec.get('cost', 0):.4f}")
        line = " · ".join(bits)
        prompt = (rec.get("prompt") or "").strip()
        if prompt:
            line += f'  — "{prompt[:60]}{"..." if len(prompt) > 60 else ""}"'
        return line
    return text


def _household() -> dict:
    """The memory files, read straight from disk -- all six categories.

    The house view is the part people notice; this is the part that stays
    useful once the novelty wears off. A month of grievances is a real record
    of what keeps going wrong. `usage` and `outcomes` are the harness's own
    telemetry rather than something written in plain language, so each row
    carries a `friendly` rendering (see `_friendly`) alongside the untouched
    `text`; the front end shows `friendly` and can fall back to the raw record
    on request, so nothing is hidden, just translated by default.
    """
    root = _journal_path().parent
    out: dict[str, list] = {}
    for cat in memory.CATEGORIES:
        path = root / f"{cat}.jsonl"
        rows = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if cat in ("usage", "outcomes"):
                    row["friendly"] = _friendly(cat, row)
                rows.append(row)
        out[cat] = rows[-40:]
    return out


def _session_index(events: list[dict]) -> list[dict]:
    """One row per session, newest first — the same fold _turn_index does, one
    level up. A session is what a user actually experiences as 'the exchange':
    the sleepover ask, three clarifying answers, and the eventual plan are one
    session and four turns, and this is what lets the console show it that way
    instead of as four unrelated rows.
    """
    turns = _turn_index(events)          # newest first already
    by_turn = {e["turn_id"]: e.get("session_id") for e in events if e.get("turn_id")}
    sessions: dict[str, dict] = {}
    for t in reversed(turns):            # oldest first, so turn_ids stay in order
        sid = by_turn.get(t["turn_id"]) or t["turn_id"]   # pre-session data: 1 turn = 1 session
        s = sessions.setdefault(sid, {
            "session_id": sid, "turn_ids": [], "prompt": t["prompt"],
            "ts": t["ts"], "turns": 0, "clarifying": 0,
            "final_outcome": None, "governed_down": False, "people": [],
        })
        s["turn_ids"].append(t["turn_id"])
        # Who took part, in order of first appearance. Two names here is what a
        # shared house looks like from Mom's chair.
        if t.get("user") and t["user"] not in s["people"]:
            s["people"].append(t["user"])
        s["turns"] += 1
        s["governed_down"] = s["governed_down"] or t["governed_down"]
        if t["outcome"] == stages.AWAITING:
            s["clarifying"] += 1
        else:
            s["final_outcome"] = t["outcome"]
    for s in sessions.values():
        # "waiting" means the last thing Dad did was ask a question and nobody
        # has answered yet — the console shows this differently from a session
        # that concluded, so it is worth naming here rather than inferring.
        s["status"] = "waiting" if s["final_outcome"] is None else "concluded"
    return sorted(sessions.values(), key=lambda s: s.get("ts") or 0, reverse=True)


@app.get("/api/turns")
def turns():
    return JSONResponse(_turn_index(_events()))


@app.get("/api/turn/{turn_id}")
def turn(turn_id: str):
    return JSONResponse([e for e in _events() if e.get("turn_id") == turn_id])


@app.get("/api/sessions")
def sessions():
    return JSONResponse(_session_index(_events()))


@app.get("/api/session/{session_id}")
def session(session_id: str):
    """Every event across every turn in this session, in original order — a
    full clarification exchange, question by question, ending at the plan."""
    evs = _events()
    by_turn = {e["turn_id"]: e.get("session_id") for e in evs if e.get("turn_id")}
    turn_ids = {tid for tid, sid in by_turn.items() if sid == session_id}
    if not turn_ids and session_id in by_turn:   # pre-session data fallback
        turn_ids = {session_id}
    return JSONResponse([e for e in evs if e.get("turn_id") in turn_ids])


@app.get("/api/household")
def household():
    return JSONResponse(_household())


@app.get("/api/meta")
def meta():
    return JSONResponse({
        "journal": str(_journal_path()),
        "exists": _journal_path().exists(),
        "stages": [stages.RECEIVED, stages.FRAMING, stages.GATHERING,
                   stages.BLOCKED, stages.REPLANNING, stages.GOVERNED,
                   stages.RESOLVING, stages.AWAITING_INPUT, stages.DELIVERED],
    })


@app.websocket("/ws")
async def live(ws: WebSocket):
    """Tail the journal and push new events as they land.

    Polls rather than using inotify: the journal is small, the poll is cheap, and
    it behaves the same on every platform. A console that misses an event is a
    nuisance; a console that needs platform-specific file watching to start is a
    liability.
    """
    await ws.accept()
    seen = len(_events())
    try:
        while True:
            await asyncio.sleep(0.6)
            if _SERVER is not None and _SERVER.should_exit:
                # Ctrl-C landed. Close politely and return before uvicorn's
                # graceful-shutdown timer has to cancel us.
                await ws.close()
                return
            evs = _events()
            if len(evs) > seen:
                for e in evs[seen:]:
                    await ws.send_json(e)
                seen = len(evs)
    except (WebSocketDisconnect, asyncio.CancelledError):
        # Two normal ways out: the browser tab closed, or the server is shutting
        # down and cancelled this task. CancelledError is a BaseException, not
        # an Exception, so the broad catch below never saw it — which is why a
        # Ctrl-C used to print "Exception in ASGI application" for every open
        # tab. Neither is an error and neither should log.
        return
    except Exception:
        return


def _asset_version() -> str:
    """A fingerprint of the static files, used as a cache-buster.

    Browsers cache /static/*.js aggressively. After an upgrade a tab could run
    last week's console.js against this week's world.js, throw on a function
    that no longer exists, and the user saw "could not reach the API" while the
    server was fine. Stamping every script URL with the newest mtime means an
    upgrade is a new URL, and the browser has to fetch it.
    """
    try:
        return str(int(max(f.stat().st_mtime for f in _STATIC.glob("*.js"))))
    except (ValueError, OSError):
        return "0"


@app.get("/")
def index():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("__V__", _asset_version())
    # The shell itself must never be cached either, or the stamped URLs inside it
    # would be stale.
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")


def main() -> None:
    import uvicorn
    print(f"Mom's Console  ·  reading {_journal_path()}")
    print("open http://127.0.0.1:8765   (Ctrl-C to close)")
    # lifespan="off": this app has no startup or shutdown hooks, and the lifespan
    # protocol's receive() is the other place a Ctrl-C used to surface as a
    # CancelledError traceback on Windows. Turning it off removes the noise
    # without removing anything the console uses.
    # timeout_graceful_shutdown: uvicorn otherwise waits indefinitely for open
    # connections, and a browser tab left on the console holds a live websocket
    # open forever. Two seconds is plenty to flush; after that, just leave.
    config = uvicorn.Config(app, host="127.0.0.1", port=8765,
                            log_level="warning", lifespan="off",
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    global _SERVER
    _SERVER = server
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    print("\nMom's Console closed.")


if __name__ == "__main__":
    main()
