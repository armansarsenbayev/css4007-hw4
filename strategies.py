"""The three strategies: S1 direct, S2 think-and-vote, S3 tools (with the loop).

Every strategy returns a dict with the same keys:
    text, answered, calls (list of API calls with usage and seconds), log (strategy-specific)
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from score import parse_answer
from tools import run_tool, tool_schemas, LOOKUP_DESCRIPTION, YEAR_ENUM_V1, YEAR_DESCRIPTION_V1

# Key comes from .env (or from the file named in ENV_FILE). It is never printed or logged.
load_dotenv(os.getenv("ENV_FILE", ".env"))

MODEL = "gpt-5.6-luna"
TEMPERATURE = 1.0          # the only value gpt-5.6-luna accepts (0.7 is rejected with HTTP 400)
K = 5                      # samples for S2
# Chat Completions refuses function tools on gpt-5.6-luna unless reasoning_effort="none",
# so every strategy uses "none": the only reasoning is what the model writes in its reply.
REASONING_EFFORT = "none"
MAX_ROUNDS = 8             # model calls per question in S3
PRICE_IN = 0.20 / 1e6      # $ per input token
PRICE_OUT = 1.20 / 1e6     # $ per output token

DATA = Path(__file__).parent / "data"

ANSWER_FORMAT = (
    "The last line of your reply must be exactly:\n"
    "ANSWER: <district name, or yes/no> | <number>\n"
    "Write the number without units and without thousands separators. Do not round it to "
    "fewer than 3 decimal places unless it is a whole number."
)

S1_INSTRUCTION = "Answer the question using only the documents below. Give the answer directly, " \
                 "without showing your working."
S2_INSTRUCTION = "Answer the question using only the documents below. Think step by step: write " \
                 "out which facts you use and every calculation before giving the answer."
S3_INSTRUCTION = "Answer the question about the Nine Rivers Region. You have no documents; get " \
                 "every fact with the lookup tool and do every calculation with the calculate " \
                 "tool. Then explain briefly which facts and calculations you used."


def corpus_text() -> str:
    lines = []
    with open(DATA / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            lines.append(f"[{d['id']}] {d['title']}\n{d['text']}")
    return "\n\n".join(lines)


CORPUS = corpus_text()

_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(max_retries=4, timeout=120)
    return _client


def chat(messages, tools=None):
    """One API call. Returns (message, call_record)."""
    kwargs = dict(model=MODEL, messages=messages, temperature=TEMPERATURE,
                  reasoning_effort=REASONING_EFFORT)
    if tools:
        kwargs["tools"] = tools
    t0 = time.perf_counter()
    r = client().chat.completions.create(**kwargs)
    dt = time.perf_counter() - t0
    u = r.usage
    rec = {
        "input_tokens": u.prompt_tokens,
        "output_tokens": u.completion_tokens,
        "cached_tokens": getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0,
        "reasoning_tokens": getattr(u.completion_tokens_details, "reasoning_tokens", 0) or 0,
        "seconds": round(dt, 3),
        "finish_reason": r.choices[0].finish_reason,
    }
    return r.choices[0].message, rec


def doc_messages(instruction: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": f"{instruction}\n\n{ANSWER_FORMAT}\n\nDOCUMENTS:\n\n{CORPUS}"},
        {"role": "user", "content": question},
    ]


# ------------------------------- S1 -------------------------------------

def s1_direct(q: dict, **_) -> dict:
    msg, rec = chat(doc_messages(S1_INSTRUCTION, q["question"]))
    text = msg.content or ""
    return {"text": text, "answered": parse_answer(text) is not None, "calls": [rec],
            "log": {"reply": text}}


# ------------------------------- S2 -------------------------------------

def vote(texts: list[str], decimals: int):
    """Majority vote over (name, number rounded to the question's decimals)."""
    keys = []
    for t in texts:
        p = parse_answer(t)
        if p is not None:
            name, num = p
            keys.append((name.lower(), round(num, decimals)))
    if not keys:
        return None, {}
    counts = Counter(keys)
    best, n = counts.most_common(1)[0]           # ties -> first one seen
    return best, {f"{k[0]} | {k[1]}": v for k, v in counts.items()}


def s2_vote(q: dict, k: int = K, **_) -> dict:
    messages = doc_messages(S2_INSTRUCTION, q["question"])
    with ThreadPoolExecutor(k) as ex:
        results = list(ex.map(lambda _: chat(messages), range(k)))
    texts = [m.content or "" for m, _ in results]
    calls = [rec for _, rec in results]
    best, counts = vote(texts, q["decimals"])
    if best is None:
        text = "no sample produced an ANSWER line"
    else:
        text = f"ANSWER: {best[0]} | {best[1]}"
    return {"text": text, "answered": best is not None, "calls": calls,
            "log": {"samples": texts, "votes": counts, "winner_count": max(counts.values(), default=0)},
            # the 5 samples run in parallel, so wall time = slowest sample
            "wall_seconds": max(c["seconds"] for c in calls)}


# ------------------------------- S3 -------------------------------------

def s3_tools(q: dict, lookup_description: str = LOOKUP_DESCRIPTION, max_rounds: int = MAX_ROUNDS,
             year_enum: list[int] = YEAR_ENUM_V1, year_description: str = YEAR_DESCRIPTION_V1,
             **_) -> dict:
    tools = tool_schemas(lookup_description, year_enum, year_description)
    messages = [
        {"role": "system", "content": f"{S3_INSTRUCTION}\n\n{ANSWER_FORMAT}"},
        {"role": "user", "content": q["question"]},
    ]
    calls, tool_log = [], []
    for rnd in range(1, max_rounds + 1):
        msg, rec = chat(messages, tools)
        rec["round"] = rnd
        calls.append(rec)
        # add the assistant message unchanged (including its tool_calls)
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            text = msg.content or ""
            return {"text": text, "answered": parse_answer(text) is not None, "calls": calls,
                    "log": {"rounds": rnd, "tool_calls": tool_log, "messages": messages}}
        # answer every tool_call_id
        for tc in msg.tool_calls:
            t0 = time.perf_counter()
            result = run_tool(tc.function.name, tc.function.arguments)
            dt = time.perf_counter() - t0
            tool_log.append({"round": rnd, "id": tc.id, "name": tc.function.name,
                             "arguments": tc.function.arguments, "result": result,
                             "seconds": round(dt, 6)})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)})
    return {"text": "", "answered": False, "calls": calls,
            "log": {"rounds": max_rounds, "hit_round_limit": True, "tool_calls": tool_log,
                    "messages": messages}}


STRATEGIES = {"S1": s1_direct, "S2": s2_vote, "S3": s3_tools}
