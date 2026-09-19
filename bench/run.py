"""Author: Mike Bell
Last Modified: 2026-09-18
Purpose: Command line for running one benchmark arm over the frozen corpus.

    python -m bench.run --arm baseline --repeats 5
    python -m bench.run --arm baseline --repeats 1 --cases 3 --dry     # no key, no cost

Live runs read ANTHROPIC_API_KEY and DADLOOP_MODEL from .env exactly as
`dadloop` does. Each run gets its own directory under bench/results/ with a
run.json manifest, so two arms compared later were provably run the same way.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace as NS

from dadloop import AgentLoop, Context, SemanticMemory
from dadloop.core.agent import _load_dotenv

from .harness import run_arm
from .prompts import CASES, LADDER

CORPORA = {"ladder": LADDER, "wide": CASES}

ARMS: dict[str, object] = {}


def _live_baseline(memory_root: Path) -> AgentLoop:
    return AgentLoop(Context(memory=SemanticMemory(memory_root)))


def _with_model(make_agent, model: str | None):
    """Pin the model per run. AgentLoop reads DADLOOP_MODEL at construction;
    overriding the attribute after is the same knob without touching env."""
    if not model:
        return make_agent

    def make(memory_root: Path) -> AgentLoop:
        agent = make_agent(memory_root)
        agent.model = model
        return agent
    return make


def _dry_baseline(memory_root: Path) -> AgentLoop:
    class FM:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return NS(model="claude-haiku-4-5-20251001",
                          content=[NS(type="tool_use", id="w", name="check_weather", input={}),
                                   NS(type="tool_use", id="s", name="load_skill",
                                      input={"name": "the-thermostat"})],
                          usage=NS(input_tokens=1000, output_tokens=40))
            return NS(model="claude-haiku-4-5-20251001",
                      content=[NS(type="text", text="1. Check\nDone.")],
                      usage=NS(input_tokens=1200, output_tokens=30))
    dad = AgentLoop(Context(memory=SemanticMemory(memory_root)))
    dad._client = type("FC", (), {"messages": FM()})()
    return dad


ARMS["baseline"] = _live_baseline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--model", default=None, help="model id; default DADLOOP_MODEL from .env")
    ap.add_argument("--corpus", default="ladder", choices=sorted(CORPORA))
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--cases", type=int, default=None, help="only the first N cases")
    ap.add_argument("--out", default=None, help="results dir; default bench/results/<timestamp>-<arm>")
    ap.add_argument("--dry", action="store_true", help="scripted client, no key, no cost")
    args = ap.parse_args(argv)

    _load_dotenv()
    corpus = CORPORA[args.corpus]
    cases = corpus[: args.cases] if args.cases else corpus
    model = args.model or os.environ.get("DADLOOP_MODEL", "claude-sonnet-5")
    arm = f"{args.arm}-{model}"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = Path(args.out) if args.out else Path("bench/results") / f"{stamp}-{arm}"
    out.mkdir(parents=True, exist_ok=True)

    make_agent = _with_model(_dry_baseline if args.dry else ARMS[args.arm], model)
    if not args.dry and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("No ANTHROPIC_API_KEY; use --dry or put a key in .env.")
        return 2

    manifest = {"arm": arm, "base_arm": args.arm, "corpus": args.corpus, "repeats": args.repeats,
                "cases": len(cases), "dry": args.dry, "model": model, "started_at": stamp}
    (out / "run.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    def show(row: dict) -> None:
        print(f"{row['case_id']:<12} r{row['repeat']}  {row['llm_calls']} calls  "
              f"{row['llm_ms']:.0f}ms model  ${row['cost']:.4f}  "
              f"skills={row['loaded_skills']}  {row['outcome']}")

    path = run_arm(arm, cases, repeats=args.repeats, make_agent=make_agent, out_dir=out, on_row=show)
    print(f"\nwrote {path}")
    print(f"report: .venv/bin/python -m bench.report {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
