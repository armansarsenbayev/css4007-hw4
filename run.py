"""Run strategies on the questions and save every log to outputs/.

    python run.py --run 1                          # all three strategies, all 20 questions
    python run.py --run test --questions Q-01,Q-09 # quick test
    python run.py --run c1-vague --strategies S3 --questions Q-01,Q-03,Q-08,Q-09,Q-18 --vague
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import strategies as S
from score import is_correct, parse_answer
from tools import (VAGUE_LOOKUP_DESCRIPTION, LOOKUP_DESCRIPTION, YEAR_ENUM_V1, YEAR_ENUM_V2,
                   YEAR_DESCRIPTION_V1, YEAR_DESCRIPTION_V2)

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"


def run_one(strategy: str, q: dict, extra: dict) -> dict:
    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            res = S.STRATEGIES[strategy](q, **extra)
            break
        except Exception as e:  # API failure after the client's own retries
            err = f"{type(e).__name__}: {e}"
            time.sleep(5 * (attempt + 1))
    else:
        res = {"text": "", "answered": False, "calls": [], "log": {"api_error": err}}
    wall = time.perf_counter() - t0
    seconds = res.get("wall_seconds", wall)
    p = parse_answer(res["text"])
    return {
        "id": q["id"], "strategy": strategy,
        "question": q["question"],
        "gold": f"{q['answer']} | {q['value']}",
        "parsed": None if p is None else f"{p[0]} | {p[1]}",
        "answered": res["answered"],
        "correct": res["answered"] and is_correct(res["text"], q),
        "api_calls": len(res["calls"]),
        "input_tokens": sum(c["input_tokens"] for c in res["calls"]),
        "output_tokens": sum(c["output_tokens"] for c in res["calls"]),
        "cached_tokens": sum(c["cached_tokens"] for c in res["calls"]),
        "reasoning_tokens": sum(c["reasoning_tokens"] for c in res["calls"]),
        "seconds": round(seconds, 3),
        "final_text": res["text"],
        "calls": res["calls"],
        "log": res["log"],
    }


def summarise(rows: list[dict]) -> dict:
    tin = sum(r["input_tokens"] for r in rows)
    tout = sum(r["output_tokens"] for r in rows)
    secs = [r["seconds"] for r in rows]
    return {
        "questions": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "unanswered": sum(not r["answered"] for r in rows),
        "api_calls": sum(r["api_calls"] for r in rows),
        "input_tokens": tin,
        "output_tokens": tout,
        "cached_tokens": sum(r["cached_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "median_seconds": round(statistics.median(secs), 2) if secs else 0,
        "total_seconds": round(sum(secs), 1),
        "cost_usd": round(tin * S.PRICE_IN + tout * S.PRICE_OUT, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run name, used as outputs/run-<name>/")
    ap.add_argument("--strategies", default="S1,S2,S3")
    ap.add_argument("--questions", default="", help="comma-separated ids; default all")
    ap.add_argument("--vague", action="store_true", help="S3 with a one-line lookup description")
    ap.add_argument("--enum-v2", action="store_true",
                    help="S3 with the lookup year enum ordered 2025, 2024, 2020")
    ap.add_argument("--year-v2", action="store_true",
                    help="S3 with the rewritten description of the lookup year parameter")
    ap.add_argument("--workers", type=int, default=4, help="questions run in parallel")
    args = ap.parse_args()

    questions = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
    if args.questions:
        keep = set(args.questions.split(","))
        questions = [q for q in questions if q["id"] in keep]

    extra = {"lookup_description": VAGUE_LOOKUP_DESCRIPTION if args.vague else LOOKUP_DESCRIPTION,
             "year_enum": YEAR_ENUM_V2 if args.enum_v2 else YEAR_ENUM_V1,
             "year_description": YEAR_DESCRIPTION_V2 if args.year_v2 else YEAR_DESCRIPTION_V1}
    out_dir = OUT / f"run-{args.run}"
    settings = {"model": S.MODEL, "temperature": S.TEMPERATURE,
                "reasoning_effort": S.REASONING_EFFORT, "k": S.K,
                "max_rounds": S.MAX_ROUNDS, "price_in_per_1M": S.PRICE_IN * 1e6,
                "price_out_per_1M": S.PRICE_OUT * 1e6, "vague_lookup": args.vague, "year_enum": extra["year_enum"],
                "year_description": extra["year_description"],
                "lookup_description": extra["lookup_description"],
                "questions": [q["id"] for q in questions],
                "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    summary = {"settings": settings}
    for strat in args.strategies.split(","):
        sdir = out_dir / strat
        sdir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(args.workers) as ex:
            rows = list(ex.map(lambda q: run_one(strat, q, extra), questions))
        for r in rows:
            (sdir / f"{r['id']}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
        summary[strat] = summarise(rows)
        summary[strat]["per_question"] = {r["id"]: {"correct": r["correct"], "answered": r["answered"],
                                                    "parsed": r["parsed"], "gold": r["gold"],
                                                    "api_calls": r["api_calls"],
                                                    "input_tokens": r["input_tokens"],
                                                    "output_tokens": r["output_tokens"],
                                                    "seconds": r["seconds"]} for r in rows}
        s = summary[strat]
        print(f"{strat}: {s['correct']}/{s['questions']} correct, {s['unanswered']} unanswered, "
              f"in={s['input_tokens']} out={s['output_tokens']} median={s['median_seconds']}s "
              f"total={s['total_seconds']}s cost=${s['cost_usd']}")
        for r in rows:
            print(f"   {r['id']} {'OK ' if r['correct'] else 'BAD'} got={r['parsed']} gold={r['gold']} "
                  f"calls={r['api_calls']}")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
