"""Author: Mike Bell
Last Modified: 2026-09-19
Purpose: Evaluate the selector alone, no Claude, against a truth set of loaded skills.

    python -m bench.selector_eval --truth bench/results/ladder-sonnet/baseline-claude-sonnet-5.jsonl \\
                                  --truth bench/results/stress-sonnet/baseline-claude-sonnet-5.jsonl

Runs Jev once per prompt (it is deterministic) under four configurations and
prints Jaccard against the majority loaded set per case, at several thresholds.
Costs a fraction of a cent. This is where description wording gets tuned,
before any full arm is rerun."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from dadloop.core import skills as skill_lib
from dadloop.core.agent import _load_dotenv

from .jev_arm import DEFAULT_QUESTION, Preselector, expand
from .prompts import LADDER, STRESS
from .triggers import TRIGGERS, composes_from_bodies

ABOUT_QUESTION = "Is this request about: {about}?"


def truth_from(paths: list[str]) -> dict[str, set[str]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                by[r["case_id"]].append(r)
    out = {}
    for cid, rs in by.items():
        c = Counter(s for r in rs for s in r.get("loaded_skills", []))
        out[cid] = {s for s, k in c.items() if k * 2 > len(rs)}
    return out


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


CONFIGS = {
    "A description + 'require'": dict(question=DEFAULT_QUESTION, triggers=None, composes=None),
    "B description + 'about'": dict(question=ABOUT_QUESTION, triggers=None, composes=None),
    "C triggers + criteria": dict(question=ABOUT_QUESTION, triggers=TRIGGERS, composes=None),
    "D triggers + composition": dict(question=ABOUT_QUESTION, triggers=TRIGGERS, composes="bodies"),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", action="append", required=True, help="baseline rows file(s); majority loaded set is truth")
    ap.add_argument("--thresholds", default="0.4,0.5,0.6")
    ap.add_argument("--out", default=None, help="write raw probabilities per config here (jsonl)")
    args = ap.parse_args(argv)
    _load_dotenv()
    from typesafe_sdk import TypeSafeClient
    client = TypeSafeClient()
    truth = truth_from(args.truth)
    cases = [c for c in LADDER + STRESS if c["id"] in truth]
    names = list(skill_lib.SKILLS)
    descs = {n: s.description for n, s in skill_lib.SKILLS.items()}
    composes = composes_from_bodies(skill_lib.SKILLS)
    thresholds = [float(t) for t in args.thresholds.split(",")]
    raw = open(args.out, "a", encoding="utf-8") if args.out else None

    print(f"truth: {len(cases)} cases from {len(args.truth)} file(s); composition map: {composes}\n")
    for label, cfg in CONFIGS.items():
        comp = composes if cfg["composes"] == "bodies" else None
        sel = Preselector(client, threshold=0.0, question=cfg["question"], triggers=cfg["triggers"], composes=None)
        probs_by_case, ms_total, tok_total = {}, 0.0, 0
        for c in cases:
            r = sel.select(c["prompt"], names, descs)
            probs_by_case[c["id"]] = r["probs"]; ms_total += r["ms"]; tok_total += r["tokens_in"]
            if raw:
                raw.write(json.dumps({"config": label, "case_id": c["id"], "probs": r["probs"], "ms": r["ms"]}) + "\n")
        print(f"== {label}   ({ms_total/len(cases):.0f} ms/prompt, {tok_total/len(cases):.0f} Jev tokens in/prompt)")
        for t in thresholds:
            js, sizes = [], []
            for c in cases:
                entry = [n for n, p in sorted(probs_by_case[c["id"]].items(), key=lambda kv: -kv[1]) if p >= t]
                chosen = expand(entry, comp)
                js.append(jaccard(chosen, truth[c["id"]])); sizes.append(len(chosen))
            print(f"   t={t:.1f}  jaccard={statistics.fmean(js):.2f}  skills/prompt={statistics.fmean(sizes):.1f}")
        # per-case detail at 0.5 for reading
        for c in cases:
            entry = [n for n, p in sorted(probs_by_case[c["id"]].items(), key=lambda kv: -kv[1]) if p >= 0.5]
            chosen = expand(entry, comp)
            miss = sorted(truth[c["id"]] - set(chosen)); extra = sorted(set(chosen) - truth[c["id"]])
            flag = "" if not miss and not extra else f"  miss={miss} extra={extra}"
            print(f"      {c['id']:<14} J={jaccard(chosen, truth[c['id']]):.2f}{flag}")
        print()
    if raw:
        raw.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
