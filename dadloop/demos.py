"""Author: Swami Chandrasekaran
Last Modified: 2026-09-05
Purpose: Scripted demo scenarios showcasing harness capabilities.

Demo scenarios — the hard parts of a harness, made visible.

Six scripted moments. Each stages the mocked WORLD, asks Dad one question, and
lets the model work. The sixth puts two people in one house. Needs ANTHROPIC_API_KEY; the tests/ mirror the mechanics
with a fake model so they run offline.

    python -m dadloop.demos

Narration line: model decides · harness executes · results feed back · loop continues
"""

from __future__ import annotations

from .core.agent import AgentLoop
from .core import tools


def _banner(title: str, point: str) -> None:
    print("\n" + "=" * 66)
    print(f"  {title}")
    print(f"  what to watch: {point}")
    print("=" * 66)


def _trace(kind, payload):
    if kind == "tool_call":
        name, args = payload[0], payload[1]
        if name == "load_skill":
            print(f"    skill  load: {args.get('name')}")
        else:
            a = ", ".join(f"{k}={v}" for k, v in (args or {}).items())
            print(f"    tool   {name}({a})")
    elif kind == "tool_result":
        print(f"       -> {payload[1][:80]}")
    elif kind == "controller":
        name, action, reason = payload
        print(f"    MOM [{action}] {name}: {reason}")
    elif kind == "thinking":
        print(f"    ... {payload}")


# --- Demo 1: FAILURE + CONFLICT → the model must route around a dead end ---
def demo_conflict(dad: AgentLoop) -> None:
    _banner(
        "DEMO 1 · Failure & conflict",
        "grill is broken AND the fix is blocked — does Dad notice and adapt?",
    )
    tools.WORLD.update(propane="empty", hardware_store_open=False)
    print("  world: propane EMPTY, hardware store CLOSED\n")
    print("  Dad ›", dad.turn(
        "Can we grill for the cookout this Saturday?", on_event=_trace))


# --- Demo 2: MULTI-HOP DEPENDENCY → step 3 depends on step 1's result -----
def demo_multihop(dad: AgentLoop) -> None:
    _banner(
        "DEMO 2 · Multi-hop dependent reasoning",
        "empty pantry → must shop → must check budget → must find a cheaper plan. "
        "Each hop depends on the last; a single call can't do this.",
    )
    tools.WORLD.update(pantry_has_veggies=False, budget=40, propane="full")
    print("  world: pantry EMPTY, budget $40, propane full\n")
    print("  Dad ›", dad.turn(
        "What do I need to buy to feed 8 people veggie skewers, and can we afford it? "
        "Look up a cheap recipe if money's tight.", on_event=_trace))


# --- Demo 3: MEMORY COGNITION → persistence changes behavior next session --
def demo_memory(dad: AgentLoop) -> None:
    _banner(
        "DEMO 3 · Memory as cognition (not logging)",
        "touch the thermostat now; in a FRESH session Dad brings it up unprompted, "
        "because the grievance is injected into his system prompt.",
    )
    tools.WORLD.update()
    print("  session 1: someone messes with the thermostat\n")
    print("  Dad ›", dad.turn("Set the thermostat to 74, I'm cold.", on_event=_trace))

    print("\n  --- new session, SAME memory on disk ---\n")
    fresh = AgentLoop(dad.ctx.__class__(memory=dad.ctx.memory))
    print("  session 2 (unrelated question):")
    print("  Dad ›", fresh.turn("Morning. What's the weather for my run?", on_event=_trace))
    print("\n  ↑ if Dad references the thermostat unprompted, memory is cognition.")


# --- Demo 4: THE CONTROLLER → Mom governs the agent -----------------------
def demo_controller(dad: AgentLoop) -> None:
    _banner(
        "DEMO 4 · The controller (Mom)",
        "Dad proposes; Mom disposes. She reviews every tool call and can veto it "
        "before it runs — the policy layer every real harness has above it.",
    )
    print("  Dad tries to crank the heat; Mom's house rule caps it at 70.\n")
    print("  Dad ›", dad.turn(
        "I'm freezing, set the thermostat to 76.", on_event=_trace))


def demo_skills(dad: AgentLoop) -> None:
    _banner(
        "DEMO 5 · Skills — assemble & orchestrate",
        "one request loads several skills (grilling + budget + lawn) and weaves "
        "them: the grill plan constrained by budget, timed around the lawn.",
    )
    print("  Watch the skill loads stack up, then get reconciled.\n")
    print("  Dad ›", dad.turn(
        "I'm hosting a cookout Saturday. What do I do?", on_event=_trace))


def demo_shared_house(dad: AgentLoop) -> None:
    _banner(
        "DEMO 6 · Two people, one Dad",
        "swami asks about the cookout; priya, in the same house, asks the same "
        "thing later. Dad is the one who notices, names who handled it, and "
        "points back instead of redoing the work.",
    )
    import time
    from .house import House, HouseClient

    tools.WORLD.update(propane="empty", budget=40)
    house = House(dad, port=0).start()      # port 0: any free port, this demo only
    try:
        swami = HouseClient(port=house.port, user="swami").connect()
        priya = HouseClient(port=house.port, user="priya").connect()
        seen = []
        priya.on_other = lambda f: seen.append(f.get("kind"))
        time.sleep(0.2)
        print(f"  In the house: {', '.join(swami.people)}\n")
        print("  swami ›", swami.turn("Twelve people Saturday, forty bucks. Are we set?",
                                      on_event=_trace))
        time.sleep(0.3)
        print(f"\n  (priya's terminal drew swami's turn as it ran: "
              f"{sum(1 for k in seen if k == 'tool_call')} tool calls, then the reply)\n")
        print("  priya ›", priya.turn("Can you plan the cookout for Saturday?",
                                      on_event=_trace))
        swami.close(); priya.close()
    finally:
        house.stop()


def main() -> None:
    dad = AgentLoop()
    if not dad.online:
        print("These demos need a live model. Set ANTHROPIC_API_KEY in .env and "
              "`pip install anthropic`, then rerun.")
        return
    demo_conflict(dad)
    demo_multihop(AgentLoop())   # fresh transcript per demo
    demo_memory(AgentLoop())
    demo_controller(AgentLoop())
    demo_skills(AgentLoop())
    demo_shared_house(AgentLoop())


if __name__ == "__main__":
    main()
