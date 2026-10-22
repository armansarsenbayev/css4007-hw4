"""One scorer for every strategy.

Rule (fixed before the first full run):
  * the reply must contain a line  ANSWER: <name> | <number>  (the last such line counts);
    no line -> unanswered (and therefore not correct);
  * the name must equal the gold `answer`, ignoring case and surrounding spaces/punctuation;
  * the number, after removing units / thousands separators, is rounded to the gold `decimals`
    and must be within one unit of the last digit of the gold `value`
    (|round(x, d) - value| <= 10**-d, with a tiny float tolerance).
"""
from __future__ import annotations

import re

ANSWER_RE = re.compile(r"ANSWER:\s*\**\s*([^|\n]+?)\s*\|\s*([^\n]+)", re.I)
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_answer(text: str):
    """Return (name, number) from the last ANSWER line, or None."""
    if not text:
        return None
    matches = ANSWER_RE.findall(text)
    if not matches:
        return None
    name, rest = matches[-1]
    name = name.strip().strip("*`'\".").strip()
    m = NUM_RE.search(rest.replace(",", "").replace(" ", ""))
    if not name or not m:
        return None
    return name, float(m.group())


def is_correct(text: str, gold: dict) -> bool:
    p = parse_answer(text)
    if p is None:
        return False
    name, num = p
    if name.lower() != str(gold["answer"]).lower():
        return False
    d = gold["decimals"]
    return abs(round(num, d) - gold["value"]) <= 10 ** -d + 1e-9
