"""The two tools the model can call: lookup and calculate.

Both return a dict and never raise: on any problem they return {"error": "..."}
so the model can read what went wrong and try again.
"""
from __future__ import annotations

import ast
import difflib
import json
import math
import operator
import re
from pathlib import Path

DATA = Path(__file__).parent / "data" / "corpus.jsonl"

DISTRICTS = [
    "Ossbridge", "Ossford", "Tarnvale", "Kelmarsh", "Brightwater", "Stonecairn",
    "Harrowfield", "Lindenmoor", "Redfen", "Ashgrove", "Millbrook", "Coldharbour",
]

FIELDS = [
    "population", "area_km2", "budget_million_tenge", "water_use_megalitres",
    "schools", "pupils", "paved_road_km", "founded_year", "water_tariff_tenge_per_m3",
]

UNITS = {
    "population": "residents",
    "area_km2": "km2",
    "budget_million_tenge": "million tenge",
    "water_use_megalitres": "megalitres",
    "schools": "schools",
    "pupils": "pupils (2025/26)",
    "paved_road_km": "km",
    "founded_year": "year",
    "water_tariff_tenge_per_m3": "tenge per cubic metre",
}

NUM = r"(\d[\d,]*(?:\.\d+)?)"

# Each field: list of regexes; the first group is the number.
PATTERNS = {
    ("population", 2025): [
        rf"2025 census recorded {NUM} residents",
        rf"2025 census counted {NUM} residents",
        rf"in 2020 and {NUM} in 2025",
    ],
    ("population", 2020): [
        rf"2020 census had recorded {NUM}",
        rf"up from {NUM} at the 2020 census",
        rf"Census population: {NUM} in 2020",
    ],
    ("area_km2", 2025): [rf"{NUM} square kilometres"],
    ("budget_million_tenge", 2025): [rf"{NUM} million tenge"],
    ("schools", 2025): [rf"{NUM} schools"],
    ("pupils", 2025): [rf"{NUM} pupils"],
    ("paved_road_km", 2025): [rf"{NUM} km of paved road", rf"paved road network is {NUM} km"],
    ("founded_year", 2025): [r"[Ff]ounded in (\d{4})"],
}
# water use is special: two possible units
WATER_PATTERNS = [
    (rf"{NUM} megalitres", 1.0, None),
    (rf"{NUM} cubic metres of water", 1 / 1000,
     "profile gives {raw} cubic metres; converted to megalitres (1 ML = 1,000 m3)"),
]

MAX_EVIDENCE = 300


def _load_corpus(path: Path = DATA) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


CORPUS = _load_corpus()


def _num(s: str) -> float:
    v = float(s.replace(",", ""))
    return int(v) if v.is_integer() else v


def _sentence_with(text: str, start: int) -> str:
    """The sentence of `text` that contains character position `start`."""
    dot = text.rfind(". ", 0, start)
    left = dot + 2 if dot >= 0 else 0
    right = text.find(". ", start)
    right = len(text) if right == -1 else right + 1
    return text[left:right].strip()[:MAX_EVIDENCE]


def is_archived(doc: dict) -> bool:
    return "ARCHIVED" in doc["title"] or doc["text"].startswith("ARCHIVED")


def current_profile(district: str) -> dict | None:
    """The non-archived profile whose title starts with the district name."""
    hits = [d for d in CORPUS
            if d["title"].startswith(district + " district profile") and not is_archived(d)]
    return hits[0] if len(hits) == 1 else None


def corrections_for(district: str) -> list[dict]:
    return [d for d in CORPUS
            if d["title"].lower().startswith("correction") and district in d["title"]]


def resolve_district(name) -> tuple[str | None, str | None]:
    """Return (canonical name, None) or (None, error message)."""
    if not isinstance(name, str) or not name.strip():
        return None, "missing district name"
    raw = name.strip()[:60]
    cleaned = re.sub(r"\s+district$", "", raw, flags=re.I).strip()
    for d in DISTRICTS:
        if d.lower() == cleaned.lower():
            return d, None
    prefix = [d for d in DISTRICTS if d.lower().startswith(cleaned.lower())]
    if len(prefix) > 1:
        return None, f"'{raw}' is ambiguous: {' or '.join(prefix)}? Use the full name."
    close = difflib.get_close_matches(cleaned.title(), DISTRICTS, n=3, cutoff=0.5)
    # similar-looking names (Ossbridge/Ossford) are always offered together
    if close and close[0].startswith("Oss"):
        close = [close[0]] + [d for d in ("Ossbridge", "Ossford") if d != close[0]]
    if close:
        return None, f"no district named '{raw}'; did you mean {' or '.join(close[:3])}?"
    return None, f"no district named '{raw}'. Districts: {', '.join(DISTRICTS)}"


def _extract(doc: dict, field: str, year: int):
    text = doc["text"]
    for pat in PATTERNS[(field, year)]:
        m = re.search(pat, text)
        if m:
            try:
                return _num(m.group(1)), _sentence_with(text, m.start())
            except ValueError:
                return None, None
    return None, None


def lookup(district: str | None = None, field: str | None = None, year: int | None = 2025) -> dict:
    """Return one figure for one district (or the regional water tariff)."""
    try:
        if year is None:
            year = 2025
        if field not in FIELDS:
            return {"error": f"unknown field '{field}'; valid fields: {', '.join(FIELDS)}"}
        if isinstance(year, bool) or not isinstance(year, int):
            return {"error": "year must be an integer: 2020, 2024 or 2025"}

        if field == "water_tariff_tenge_per_m3":
            if year not in (2024, 2025):
                return {"error": "the water tariff is only published for 2024 and 2025"}
            doc = next(d for d in CORPUS if d["title"] == "Household water tariff")
            pat = (rf"{year} tariff was {NUM} tenge" if year == 2024
                   else rf"tariff is {NUM} tenge per cubic metre")
            m = re.search(pat, doc["text"])
            return {"field": field, "year": year, "value": _num(m.group(1)),
                    "unit": UNITS[field], "source": doc["id"],
                    "evidence": _sentence_with(doc["text"], m.start()),
                    "note": "same tariff in every district; 1 megalitre = 1,000 cubic metres"}

        canonical, err = resolve_district(district)
        if err:
            return {"error": err}
        if year not in (2020, 2025):
            return {"error": f"year {year} is not available; use 2025 (or 2020 for population). "
                             "Archived 2019 profiles are not used."}
        if year == 2020 and field != "population":
            return {"error": "year 2020 is only available for population (2020 census)"}

        doc = current_profile(canonical)
        if doc is None:
            return {"error": f"no current (non-archived) profile for {canonical}"}

        out = {"district": canonical, "field": field, "year": year, "unit": UNITS[field],
               "source": doc["id"]}

        if field == "water_use_megalitres":
            for pat, factor, note in WATER_PATTERNS:
                m = re.search(pat, doc["text"])
                if m:
                    raw = m.group(1)
                    value = _num(raw) * factor
                    out.update(value=round(value, 6),
                               evidence=_sentence_with(doc["text"], m.start()))
                    if note:
                        out["note"] = note.format(raw=raw)
                    return out
            return {"error": f"could not read {field} from {doc['id']}"}

        value, evidence = _extract(doc, field, year)
        if value is None:
            return {"error": f"could not read {field} from {doc['id']}"}
        out.update(value=value, evidence=evidence)

        # correction notices take precedence over the profile
        if field == "area_km2":
            for c in corrections_for(canonical):
                m = re.search(rf"correct area is {NUM} square kilometres", c["text"])
                if m:
                    out.update(value=_num(m.group(1)), source=c["id"],
                               evidence=_sentence_with(c["text"], m.start()),
                               note=f"{doc['id']} says {value}; corrected by notice {c['id']}")
        return out
    except Exception as e:  # never crash the loop
        return {"error": f"lookup failed: {type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# calculate: arithmetic only, via ast (no eval / exec)
# --------------------------------------------------------------------------

MAX_LEN = 300
MAX_NODES = 200
MAX_EXP = 100
MAX_ABS = 1e15

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class CalcError(ValueError):
    pass


def _check(x):
    if isinstance(x, complex) or (isinstance(x, float) and not math.isfinite(x)):
        raise CalcError("result is not a finite real number")
    if abs(x) > MAX_ABS:
        raise CalcError(f"result too large (|x| > {MAX_ABS:g})")
    return x


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError(f"not allowed in expression: {type(node.value).__name__} constant")
        return _check(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(_UNARY[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXP:
                raise CalcError(f"exponent too large (max {MAX_EXP})")
            if left == 0 and right < 0:
                raise CalcError("division by zero")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalcError("division by zero")
        try:
            return _check(_BINOPS[type(node.op)](left, right))
        except OverflowError:
            raise CalcError(f"result too large (|x| > {MAX_ABS:g})")
    raise CalcError(f"not allowed in expression: {type(node).__name__}")


def calculate(expression: str) -> dict:
    """Evaluate one arithmetic expression safely."""
    try:
        if not isinstance(expression, str):
            return {"error": "expression must be a string"}
        expr = expression.strip()
        if not expr:
            return {"error": "expression is empty"}
        if len(expr) > MAX_LEN:
            return {"error": f"expression too long (max {MAX_LEN} characters)"}
        expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            return {"error": f"could not parse expression: {e.msg} (use plain numbers without "
                             "thousands separators, and only + - * / // % ** ( ))"}
        if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
            return {"error": "expression too complex"}
        # refuse forbidden nodes before evaluating anything
        allowed = (ast.Expression, ast.Constant, ast.BinOp, ast.UnaryOp,
                   *_BINOPS, *_UNARY)
        for n in ast.walk(tree):
            if isinstance(n, ast.Tuple):
                return {"error": "not allowed in expression: Tuple (do not use commas or "
                                 "thousands separators: write 52904, not 52,904)"}
            if not isinstance(n, allowed):
                return {"error": f"not allowed in expression: {type(n).__name__}"}
        result = _eval(tree)
        return {"expression": expression, "result": result}
    except CalcError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"calculate failed: {type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# Tool definitions sent to the model (same as SUBMISSION.md, Part A2)
# --------------------------------------------------------------------------

LOOKUP_DESCRIPTION = (
    "Get ONE official figure about ONE district of the Nine Rivers Region (or the regional "
    "water tariff). Uses only the current 2025 district profiles: archived 2019 profiles are "
    "never used and published correction notices are already applied. Returns the number at "
    "full precision, its unit, the id of the source document and the sentence it was read "
    "from. Water use is always returned in megalitres (converted if a profile uses cubic "
    "metres). Districts: " + ", ".join(DISTRICTS) + ". Call once per (district, field); call "
    "it several times in parallel when you need several figures. Do not guess figures yourself."
)

VAGUE_LOOKUP_DESCRIPTION = "Looks things up."


def lookup_schema(description: str = LOOKUP_DESCRIPTION) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {
                        "type": "string",
                        "description": "District name, e.g. \"Brightwater\". Not needed for "
                                       "field water_tariff_tenge_per_m3.",
                    },
                    "field": {
                        "type": "string",
                        "enum": FIELDS,
                        "description": "Which figure. population = census residents; pupils = "
                                       "enrolled 2025/26; budget = 2025 budget; water_use = 2025 "
                                       "household water use.",
                    },
                    "year": {
                        "type": "integer",
                        "enum": [2020, 2024, 2025],
                        "description": "Optional, default 2025. Use 2020 only for population "
                                       "(2020 census) and 2024 only for the water tariff.",
                    },
                },
                "required": ["field"],
                "additionalProperties": False,
            },
        },
    }


CALCULATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate ONE arithmetic expression exactly and return the result at full precision. "
            "Use it for every calculation (ratios, differences, percentages, unit conversions) "
            "instead of doing arithmetic yourself. Allowed: numbers (no thousands separators), "
            "+ - * / // % **, unary minus and parentheses. No variables, names or functions. "
            "Example: \"44675/921.4 - 37203/758.6\"."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression, e.g. \"(52904/1284.6) - "
                                   "(30982/846.2)\". Max 300 characters.",
                },
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
}


def tool_schemas(lookup_description: str = LOOKUP_DESCRIPTION) -> list[dict]:
    return [lookup_schema(lookup_description), CALCULATE_SCHEMA]


TOOLS = {"lookup": lookup, "calculate": calculate}


def validate_args(name: str, raw: str) -> tuple[dict | None, str | None]:
    """Parse the JSON string from the model and check it against the schema."""
    if name not in TOOLS:
        return None, f"unknown tool '{name}'; available: lookup, calculate"
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        return None, f"arguments are not valid JSON: {e.msg}"
    if not isinstance(args, dict):
        return None, "arguments must be a JSON object"
    props = lookup_schema()["function"]["parameters"]["properties"] if name == "lookup" \
        else CALCULATE_SCHEMA["function"]["parameters"]["properties"]
    extra = set(args) - set(props)
    if extra:
        return None, f"unexpected argument(s): {', '.join(sorted(extra))}"
    if name == "calculate":
        if not isinstance(args.get("expression"), str):
            return None, "'expression' (string) is required"
    else:
        if not isinstance(args.get("field"), str):
            return None, "'field' (string) is required"
        if "district" in args and not isinstance(args["district"], (str, type(None))):
            return None, "'district' must be a string"
        if "year" in args and args["year"] is not None and (
                isinstance(args["year"], bool) or not isinstance(args["year"], int)):
            return None, "'year' must be an integer"
    return args, None


def run_tool(name: str, raw_arguments: str) -> dict:
    args, err = validate_args(name, raw_arguments)
    if err:
        return {"error": err}
    return TOOLS[name](**args)
