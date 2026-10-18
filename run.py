"""Run strategies on the questions, score them, save everything to outputs/.

    python run.py --name run1                       # all 3 strategies, all 20 questions
    python run.py --name smoke --questions Q-01 Q-09
    python run.py --name c1_vague --strategies s3 --vague --questions Q-02 Q-03 Q-08 Q-09 Q-18
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import strategies
from strategies import STRATEGIES

ROOT = Path(__file__).parent
QUESTIONS = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))


def is_correct(answer, q: dict) -> bool:
    """Scoring rule (fixed before the first full run):
    - the name must equal `answer`, ignoring case and surrounding spaces/punctuation;
    - the number, rounded to `decimals`, must be within 1 unit of the last digit of
      `value` rounded to `decimals` (so 0.556 -> 0.6 matches 0.6; 0.035 -> 0.035 matches).
    - no ANSWER line (or round limit hit) = unanswered = wrong.
    """
    if answer is None:
        return False
    name, number = answer
    if name.strip().lower() != q["answer"].lower():
        return False
    d = q["decimals"]
    return abs(round(number, d) - round(q["value"], d)) <= 10 ** -d + 1e-9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="output folder under outputs/")
    ap.add_argument("--strategies", nargs="+", default=["s1", "s2", "s3"], choices=STRATEGIES)
    ap.add_argument("--questions", nargs="+", help="question ids (default: all 20)")
    ap.add_argument("--vague", action="store_true", help="S3 with the one-line lookup description (C1)")
    args = ap.parse_args()

    questions = [q for q in QUESTIONS if not args.questions or q["id"] in args.questions]
    out_dir = ROOT / "outputs" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    settings = {"model": strategies.MODEL, "max_tokens": strategies.MAX_TOKENS,
                "thinking": strategies.THINKING, "effort": strategies.EFFORT,
                "temperature": "default (1); Haiku 5.5 rejects other values",
                "k": strategies.K, "max_rounds": strategies.MAX_ROUNDS,
                "vague_lookup": args.vague, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows = []

    for strat in args.strategies:
        (out_dir / strat).mkdir(exist_ok=True)
        for q in questions:
            fn = STRATEGIES[strat]
            try:
                r = fn(q["question"], vague_lookup=args.vague) if strat == "s3" else fn(q["question"])
            except Exception as exc:  # keep the run going; the question counts as unanswered
                r = {"answer": None, "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
                     "seconds": 0.0, "api_calls": 0, "log": {"error": repr(exc)}}
            ok = is_correct(r["answer"], q)
            row = {"strategy": strat, "id": q["id"], "correct": ok,
                   "unanswered": r["answer"] is None,
                   "pred": list(r["answer"]) if r["answer"] else None,
                   "expected": [q["answer"], q["value"]],
                   **{k: r[k] for k in ("input_tokens", "output_tokens", "cost", "seconds", "api_calls")}}
            if strat == "s3":
                row["rounds"] = r["log"].get("rounds")
                row["tool_calls"] = len(r["log"].get("tool_calls", []))
            rows.append(row)
            (out_dir / strat / f"{q['id']}.json").write_text(
                json.dumps({"question": q["question"], "row": row, "log": r["log"]}, indent=2, ensure_ascii=False),
                encoding="utf-8")
            print(f"{strat} {q['id']}: {'OK ' if ok else 'XX '} pred={row['pred']} "
                  f"expected={row['expected']} {row['seconds']:.1f}s ${row['cost']:.5f}", flush=True)

    summary = []
    for strat in args.strategies:
        rs = [r for r in rows if r["strategy"] == strat]
        summary.append({
            "strategy": strat,
            "correct": sum(r["correct"] for r in rs),
            "n": len(rs),
            "unanswered": sum(r["unanswered"] for r in rs),
            "input_tokens": sum(r["input_tokens"] for r in rs),
            "output_tokens": sum(r["output_tokens"] for r in rs),
            "median_seconds": round(statistics.median(r["seconds"] for r in rs), 2),
            "total_seconds": round(sum(r["seconds"] for r in rs), 1),
            "cost": round(sum(r["cost"] for r in rs), 5),
        })
    (out_dir / "results.json").write_text(
        json.dumps({"settings": settings, "summary": summary, "rows": rows}, indent=2), encoding="utf-8")

    print("\n| Strategy | Correct | Unanswered | Input tokens | Output tokens | Median s | Total s | Cost ($) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in summary:
        print(f"| {s['strategy']} | {s['correct']}/{s['n']} | {s['unanswered']} | {s['input_tokens']} | "
              f"{s['output_tokens']} | {s['median_seconds']} | {s['total_seconds']} | {s['cost']:.4f} |")


if __name__ == "__main__":
    main()
