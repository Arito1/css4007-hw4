"""Turn outputs/<run>/results.json into the markdown tables for SUBMISSION.md.

    python analyze.py run1 run2            # summary table, per-question table, S3 rounds
    python analyze.py --c1 run1 c1_vague   # C1 comparison table
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "outputs"
LABELS = {"s1": "S1 direct", "s2": "S2 think and vote (k = 5)", "s3": "S3 tools"}


def load(name: str) -> dict:
    return json.loads((OUT / name / "results.json").read_text(encoding="utf-8"))


def summary(runs: list[str]):
    print("| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, name in enumerate(runs, 1):
        for s in load(name)["summary"]:
            print(f"| {i} | {LABELS[s['strategy']]} | {s['correct']} | {s['unanswered']} | {s['input_tokens']:,} | "
                  f"{s['output_tokens']:,} | {s['median_seconds']:.2f} | {s['total_seconds']:.1f} | {s['cost']:.4f} |")


def per_question(runs: list[str]):
    data = [{(r["strategy"], r["id"]): r for r in load(name)["rows"]} for name in runs]
    ids = sorted({qid for _, qid in data[0]})
    head = " | ".join(f"{s.upper()} r{i}" for s in ("s1", "s2", "s3") for i in range(1, len(runs) + 1))
    print(f"| Question | {head} | S3 rounds r1 | S3 tool calls r1 |")
    print("|---|" + ":---:|" * (3 * len(runs)) + "---:|---:|")
    for qid in ids:
        marks = []
        for s in ("s1", "s2", "s3"):
            for d in data:
                r = d.get((s, qid))
                marks.append("—" if r is None else ("✓" if r["correct"] else ("∅" if r["unanswered"] else "✗")))
        s3 = data[0].get(("s3", qid), {})
        print(f"| {qid} | {' | '.join(marks)} | {s3.get('rounds', '')} | {s3.get('tool_calls', '')} |")


def wrong(runs: list[str]):
    for i, name in enumerate(runs, 1):
        for r in load(name)["rows"]:
            if not r["correct"] and r["strategy"] != "s1":
                print(f"run{i} {r['strategy']} {r['id']}: pred={r['pred']} expected={r['expected']}")


def c1(base: str, vague: str):
    b = {r["id"]: r for r in load(base)["rows"] if r["strategy"] == "s3"}
    v = {r["id"]: r for r in load(vague)["rows"] if r["strategy"] == "s3"}
    print("| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |")
    print("|---|---:|---:|---|---|")
    for qid in sorted(v):
        fmt = lambda r: (f"{r['pred'][0]} {r['pred'][1]:g}" if r["pred"] else "unanswered") + (" ✓" if r["correct"] else " ✗")
        print(f"| {qid} | {b[qid]['tool_calls']} ({b[qid]['rounds']} rounds) | {v[qid]['tool_calls']} ({v[qid]['rounds']} rounds) | "
              f"{fmt(b[qid])} | {fmt(v[qid])} |")


def tolerant_vote(samples: list, rel_tol: float = 0.0005):
    """Offline re-vote for C2: numbers within 0.05% of each other (same name) count as one answer."""
    clusters = []  # [name, [numbers], first_index]
    for i, s in enumerate(samples):
        if not s:
            continue
        name, x = s[0].lower(), s[1]
        for c in clusters:
            if c[0] == name and abs(x - c[1][0]) <= rel_tol * max(abs(c[1][0]), 1e-9):
                c[1].append(x)
                break
        else:
            clusters.append([name, [x], i])
    if not clusters:
        return None
    names = [c[0] for c in clusters for _ in c[1]]
    best = max(clusters, key=lambda c: (len(c[1]), names.count(c[0]), -c[2]))
    return best[0], sorted(best[1])[len(best[1]) // 2]


def revote(runs: list[str]):
    sys.path.insert(0, str(Path(__file__).parent))
    from run import QUESTIONS, is_correct
    qs = {q["id"]: q for q in QUESTIONS}
    print("| Run | Single sample correct (of 100) | Exact-match vote (reported) | Tolerant vote (offline) | Any sample correct |")
    print("|---|---:|---:|---:|---:|")
    for i, name in enumerate(runs, 1):
        single = exact = tolerant = oracle = 0
        for qid, q in qs.items():
            log = json.loads((OUT / name / "s2" / f"{qid}.json").read_text(encoding="utf-8"))["log"]
            samples = [tuple(c["parsed"]) if c["parsed"] else None for c in log["calls"]]
            oks = [is_correct(s, q) for s in samples]
            single += sum(oks)
            oracle += any(oks)
            exact += is_correct(tuple(log["vote"]) if log["vote"] else None, q)
            tolerant += is_correct(tolerant_vote(samples), q)
        print(f"| {i} | {single} | {exact}/20 | {tolerant}/20 | {oracle}/20 |")


if __name__ == "__main__":
    if sys.argv[1] == "--c1":
        c1(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--revote":
        revote(sys.argv[2:])
    else:
        summary(sys.argv[1:])
        print()
        per_question(sys.argv[1:])
        print()
        wrong(sys.argv[1:])
