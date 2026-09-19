"""Author: Mike Bell
Last Modified: 2026-09-18
Purpose: Aggregate benchmark rows per arm and compare two arms case by case.

Three numbers Mike asked for (round trips, wall clock, cost) plus the ones
that stop a cheaper arm from being a wrong arm: which skills loaded (Jaccard
against baseline on the same case), how many load_skill calls still happened
(leakage), and the turn outcome distribution. Means over repeats; p50 shown
because one slow API call can drag a mean.

    python -m bench.report bench/results/<run>/baseline.jsonl
    python -m bench.report bench/results/<run>/baseline.jsonl bench/results/<run>/jev.jsonl
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

METRICS = ("llm_calls", "llm_ms", "total_ms", "tool_ms", "tokens_in", "tokens_out",
           "cost", "load_skill_calls", "preselect_ms")


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _stat(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "p50": None, "sum": 0.0}
    return {"mean": statistics.fmean(vals), "p50": statistics.median(vals), "sum": sum(vals)}


def summarize(rows: list[dict]) -> dict:
    out = {"n": len(rows)}
    for m in METRICS:
        out[m] = _stat([r.get(m) for r in rows])
    out["unpriced_calls"] = sum(r.get("unpriced_calls") or 0 for r in rows)
    out["outcomes"] = dict(Counter(r.get("outcome") for r in rows))
    out["ceiling_rate"] = (sum(1 for r in rows if r.get("hit_ceiling")) / len(rows)) if rows else 0.0
    return out


def by_tier(rows: list[dict]) -> dict[int, dict]:
    """Summary per designed tier, plus what was OBSERVED at that rung: the share
    of turns that loaded any skill, and the mean number of distinct skills."""
    grouped: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("tier") is not None:
            grouped[r["tier"]].append(r)
    out = {}
    for tier, rs in sorted(grouped.items()):
        s = summarize(rs)
        s["skill_load_rate"] = sum(1 for r in rs if r.get("loaded_skills")) / len(rs)
        s["skills_per_turn"] = sum(len(r.get("loaded_skills", [])) for r in rs) / len(rs)
        out[tier] = s
    return out


def _by_case(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["case_id"]].append(r)
    return grouped


def _majority_skills(rows: list[dict]) -> set[str]:
    """The skills loaded on more than half the repeats of one case."""
    n = len(rows)
    counts = Counter(s for r in rows for s in r.get("loaded_skills", []))
    return {s for s, c in counts.items() if c * 2 > n}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def compare(base: list[dict], other: list[dict]) -> dict:
    b_cases, o_cases = _by_case(base), _by_case(other)
    per_case = {}
    for cid in sorted(set(b_cases) & set(o_cases)):
        b, o = b_cases[cid], o_cases[cid]
        entry = {}
        for m in METRICS:
            entry[m] = (_stat([r.get(m) for r in b])["mean"], _stat([r.get(m) for r in o])["mean"])
        entry["skill_jaccard"] = _jaccard(_majority_skills(b), _majority_skills(o))
        entry["base_skills"] = sorted(_majority_skills(b))
        entry["other_skills"] = sorted(_majority_skills(o))
        per_case[cid] = entry
    overall = {}
    sb, so = summarize(base), summarize(other)
    for m in METRICS:
        if sb[m]["mean"] is not None and so[m]["mean"] is not None:
            overall[f"{m}_delta"] = so[m]["mean"] - sb[m]["mean"]
    js = [e["skill_jaccard"] for e in per_case.values()]
    overall["skill_jaccard_mean"] = statistics.fmean(js) if js else None
    return {"per_case": per_case, "overall": overall, "base": sb, "other": so}


def _fmt(v, nd=1):
    if v is None:
        return "-"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def print_summary(name: str, s: dict) -> None:
    print(f"\n== {name}  (n={s['n']}, unpriced calls={s['unpriced_calls']}, "
          f"hit ceiling={s['ceiling_rate']:.0%}, outcomes={s['outcomes']})")
    print(f"{'metric':<18}{'mean':>12}{'p50':>12}")
    for m in METRICS:
        nd = 6 if m == "cost" else 1
        print(f"{m:<18}{_fmt(s[m]['mean'], nd):>12}{_fmt(s[m]['p50'], nd):>12}")
    print(f"{'cost total':<18}{_fmt(s['cost']['sum'], 4):>12}")


def print_tiers(name: str, rows: list[dict]) -> None:
    t = by_tier(rows)
    if not t:
        return
    print(f"\n== {name} by designed tier   (n | llm_calls | llm_ms | cost | loaded any skill | skills/turn)")
    for tier, s in t.items():
        print(f"tier {tier}   n={s['n']:<3} {_fmt(s['llm_calls']['mean']):>5} calls "
              f"{_fmt(s['llm_ms']['mean'], 0):>7}ms  ${_fmt(s['cost']['mean'], 4)}  "
              f"loaded={s['skill_load_rate']:.0%}  skills/turn={s['skills_per_turn']:.1f}"
              f"  ceiling={s['ceiling_rate']:.0%}")


def print_compare(c: dict) -> None:
    print("\n== per case: base -> other   (llm_calls | llm_ms | cost | skills jaccard)")
    for cid, e in c["per_case"].items():
        print(f"{cid:<12}{_fmt(e['llm_calls'][0]):>5} -> {_fmt(e['llm_calls'][1]):<5}"
              f"{_fmt(e['llm_ms'][0], 0):>7} -> {_fmt(e['llm_ms'][1], 0):<7}"
              f"{_fmt(e['cost'][0], 5):>9} -> {_fmt(e['cost'][1], 5):<9}"
              f"  J={e['skill_jaccard']:.2f}  {e['base_skills']} vs {e['other_skills']}")
    o = c["overall"]
    print("\n== overall deltas (other - base, means)")
    for k, v in o.items():
        print(f"{k:<24}{_fmt(v, 6 if 'cost' in k else 3)}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    base = load_rows(Path(argv[0]))
    print_summary(Path(argv[0]).stem, summarize(base))
    print_tiers(Path(argv[0]).stem, base)
    if len(argv) > 1:
        other = load_rows(Path(argv[1]))
        print_summary(Path(argv[1]).stem, summarize(other))
        print_tiers(Path(argv[1]).stem, other)
        print_compare(compare(base, other))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
