# HW4 — submission

**AI assistance:** Claude Code (Anthropic, model Claude Opus 5.5) was used as a coding and writing assistant for the whole homework: drafting the Part A plan, writing `tools.py`, `strategies.py`, `run.py`, `score.py` and the tests, running the experiments, and drafting the Part C analysis from the saved logs in `outputs/`. Every number in this file comes from the code and logs in this repository.

---

## Part A — Plan on paper (Easy)

> Commit this whole part before any `.py` file exists.

### A1 — The steps

All twenty questions have the same shape: *"Which of districts X, Y (, Z) has more/less of metric M (or does X+Y exceed Z), and by how much?"* Every metric is a ratio, sum, difference or growth rate of a few raw profile figures. So the task splits into: **understand the question → get raw facts → do arithmetic → decide and format**, plus the loop that connects model and tools, plus the scorer that checks the result.

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Tool, loop, or model? |
|---|---|---|---|---|---|
| 1 | **Plan** — read the question and decide which facts and which formula are needed | `question: str` | `plan`: list of `(district: str, field: str, year: int)` facts to fetch + a formula in words, e.g. `density = population_2025 / area_km2` | Question names a metric that is not in the profiles → the model must say it cannot answer (`ANSWER: unknown | 0`) instead of inventing a fact | model |
| 2 | **Resolve name** — map the name the model wrote to one of the 12 canonical districts | `district: str` (any case, maybe misspelled) | `canonical: str` (one of the 12) | 0 matches → `{"error": "no district named X; did you mean A or B?"}` (closest names by edit distance). Ambiguous prefix (e.g. `"Oss"`) → `{"error": "ambiguous: Ossbridge or Ossford?"}`. Never guesses silently. | tool (`lookup`, inside) |
| 3 | **Select current document** — pick the profile that is valid for 2025 | `canonical: str` | `doc_id: str` (the 2025 profile, e.g. `"NR-05"`) + `corrections: list[doc_id]` that apply to it | Only an ARCHIVED profile exists → error, never fall back to it. Two current profiles → error (should not happen in this corpus). | tool (`lookup`, inside) |
| 4 | **Extract fact** — read one figure from the selected document, apply any correction notice | `doc_id: str`, `field: str` (from a fixed enum), `year: int` (2025 default; 2020 only for population) | `{"district": str, "field": str, "value": float, "unit": str, "year": int, "source": str, "evidence": str, "note": str?}` | Field not in enum → error listing valid fields. Pattern not found / number unreadable (e.g. `"1,2.3"`) → error `"could not read <field> from <doc>"`, no guess. Correction exists → returns corrected value, `source` = notice id, and `note` naming the old value. | tool (`lookup`, inside) |
| 5 | **Normalise unit** — make the same field always come back in the same unit | `value: float`, `unit_in_text: str` | `value: float` in the canonical unit (water → megalitres; area → km²; budget → million tenge) | Unknown unit word → error, not a silent pass-through. Cubic metres → ÷ 1000 to megalitres, with a `note` saying a conversion happened. | tool (`lookup`, inside) |
| 6 | **Compute** — evaluate every arithmetic expression (ratios, differences, growth, unit factors like ×1000 / ÷365) | `expression: str`, e.g. `"44675/921.4 - 37203/758.6"` | `{"expression": str, "result": float}` (full precision, not rounded) | Syntax error, name/attribute/call, division by zero, too-large power or result → `{"error": "..."}`. Never runs code. | tool (`calculate`) |
| 7 | **Decide** — compare the computed metrics, choose the district (or yes/no) and the reported difference | the computed `float`s from step 6 + the question | `name: str` (district or `yes`/`no`), `number: float` | Two metrics equal at full precision → name both in text, answer the first; the model must not round before comparing. | model |
| 8 | **Round & format** — produce the final line | `name: str`, `number: float` | one line `ANSWER: <name or yes/no> | <number>` (number without units or thousands separators, at least 3 decimals for non-integers) | Model writes units or commas → the scorer strips them; missing line → counted as unanswered. | model |
| 9 | **Orchestrate** — send question + tool definitions, run requested tools, return results | `messages: list[dict]`, model reply with `tool_calls` | updated `messages`; final assistant text; per-call log `{round, id, name, args, result, seconds}` | `arguments` not valid JSON / wrong types / unknown tool → send an error result for that `tool_call_id` (do not crash, do not skip the id). Round limit (step budget) reached → stop, mark question **unanswered**. API error → retry 3× with back-off, then mark unanswered. | loop |
| 10 | **Score** (evaluation only, never seen by the model) | final text: `str`, gold `{answer, value, decimals}` | `correct: bool`, `answered: bool` | No `ANSWER:` line → unanswered. Number unparsable → wrong. | scorer (my code) |

**How the steps connect:**

```text
question ──► [1 Plan: model] ──(district, field, year) ×N──► [9 Loop] ──► lookup:
                                                                         [2 Resolve name] ─► [3 Select doc] ─► [4 Extract] ─► [5 Normalise]
                                                                                │ error                                          │
                                                                                └──────── error JSON ──┐        fact JSON ◄──────┘
                                                                                                       ▼
                                   [9 Loop] ◄──── tool results (one per tool_call_id) ────────────────┘
                                       │
                                       ▼
                              [1/7 model] ──expression──► [9 Loop] ──► [6 calculate] ──► result JSON ──► [9 Loop] ──► model
                                       │
                                       ▼
                              [7 Decide: model] ──► [8 Format: model] ──► "ANSWER: name | number" ──► [10 Score]
```

Steps 2→3→4→5 always run together, inside one `lookup` call, so the model only sees step 2–5 as one tool. Step 6 can run several times (once per sub-result, or once with the whole formula). Steps 1, 7 and 8 are the only places where the model decides anything; every fact and every number it uses must come back through the loop (step 9).

**Why the set is complete and non-overlapping:** each step owns exactly one kind of decision — *which facts* (1), *which entity* (2), *which document* (3), *which number in the text* (4), *which unit* (5), *what arithmetic result* (6), *which answer* (7), *what string* (8), *who runs what* (9), *was it right* (10). No step reads documents except 3–4, no step does arithmetic except 5 (a fixed unit factor) and 6, and only 7–8 write the answer. Removing any step leaves a trap uncovered: without 2 the similar names (Ossbridge/Ossford) collide; without 3 the archived Tarnvale/Kelmarsh figures leak in; without the correction branch of 4 Brightwater's area is wrong; without 5 Lindenmoor's water is 1000× off; without 6 the model does long division in its head.

**What I am assuming:**

- **Year.** "2025" means the 2025 census / fiscal year / calendar year (NR-00). Population defaults to the 2025 census; the 2020 census is only used when a question asks for growth. School figures are for 2025/26.
- **Archived profiles** (NR-13, NR-14) are never used for any answer — NR-00 says they are superseded. `lookup` does not return their numbers at all.
- **Corrections take precedence** (NR-00): the only one is NR-16, Brightwater area 912.4 → **921.4 km²**. `lookup` applies it and reports both ids.
- **Units.** Water use is in megalitres everywhere except Lindenmoor (2,151,400 m³ = 2,151.4 ML). 1 ML = 1,000 m³ = 1,000,000 L (NR-15). The 2025 tariff is 142.35 tenge/m³, same in every district. Budgets are in million tenge.
- **Per day.** "Per resident per day" uses 365 days (2025 is not a leap year).
- **Rounding.** No intermediate rounding anywhere; the tools return full precision and the model rounds only the final number. The scorer then rounds the final number to the question's `decimals`.
- **"By how much"** means the absolute difference of the two metrics, in the metric's unit (for growth questions: percentage *points*).
- **Projection (Q-18)** uses compound growth: `pop2030 = pop2025 × (pop2025 / pop2020)`.

**The assumption the solution is most sensitive to:** that `lookup` returns the *right* number — current profile, correction applied, unit normalised. Every trap in the corpus (similar names, archived profiles, typo + correction, odd unit) sits in steps 2–5. If any of them is wrong, the model will do flawless arithmetic on a wrong fact and the answer is still wrong, and nothing downstream can notice. That is why all four traps are handled deterministically in code, not left to the model, and why most of the `lookup` tests target them.

### A2 — The two tools

#### `lookup`

```json
{
  "type": "function",
  "function": {
    "name": "lookup",
    "description": "Get ONE official figure about ONE district of the Nine Rivers Region (or the regional water tariff). Uses only the current 2025 district profiles: archived 2019 profiles are never used and published correction notices are already applied. Returns the number at full precision, its unit, the id of the source document and the sentence it was read from. Water use is always returned in megalitres (converted if a profile uses cubic metres). Districts: Ossbridge, Ossford, Tarnvale, Kelmarsh, Brightwater, Stonecairn, Harrowfield, Lindenmoor, Redfen, Ashgrove, Millbrook, Coldharbour. Call once per (district, field); call it several times in parallel when you need several figures. Do not guess figures yourself.",
    "parameters": {
      "type": "object",
      "properties": {
        "district": {
          "type": "string",
          "description": "District name, e.g. \"Brightwater\". Not needed for field water_tariff_tenge_per_m3."
        },
        "field": {
          "type": "string",
          "enum": [
            "population",
            "area_km2",
            "budget_million_tenge",
            "water_use_megalitres",
            "schools",
            "pupils",
            "paved_road_km",
            "founded_year",
            "water_tariff_tenge_per_m3"
          ],
          "description": "Which figure. population = census residents; pupils = enrolled 2025/26; budget = 2025 budget; water_use = 2025 household water use."
        },
        "year": {
          "type": "integer",
          "enum": [2020, 2024, 2025],
          "description": "Optional, default 2025. Use 2020 only for population (2020 census) and 2024 only for the water tariff."
        }
      },
      "required": ["field"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district": "Millbrook", "field": "population", "year": 2025, "value": 37203, "unit": "residents", "source": "NR-11", "evidence": "Census population: 34,590 in 2020 and 37,203 in 2025."}` |
| success with correction | `{"district": "Brightwater", "field": "area_km2", "year": 2025, "value": 921.4, "unit": "km2", "source": "NR-16", "evidence": "The correct area is 921.4 square kilometres.", "note": "NR-05 says 912.4; corrected by notice NR-16"}` |
| success with unit conversion | `{"district": "Lindenmoor", ..., "value": 2151.4, "unit": "megalitres", "source": "NR-08", "note": "profile gives 2,151,400 cubic metres; converted to megalitres (1 ML = 1,000 m3)"}` |
| misspelled / unknown name | `{"error": "no district named 'Ossbrige'; did you mean Ossbridge or Ossford?"}` |
| ambiguous name (`"Oss"`) | `{"error": "'Oss' is ambiguous: Ossbridge or Ossford? Use the full name."}` |
| only archived data asked for (e.g. `year: 2019`) | schema rejects it; if it slips through: `{"error": "year must be one of 2020, 2024, 2025 ..."}`. Archived profiles are never a source. |
| unknown field | `{"error": "unknown field 'density'; valid fields: population, area_km2, ..."}` |
| year not available for that field (e.g. area in 2020) | `{"error": "year 2020 is only available for population; ..."}` |
| district missing (non-tariff field) | `{"error": "field 'population' needs a district"}` |
| figure cannot be read from text | `{"error": "could not read pupils from NR-xx"}` |
| bad argument types / extra keys | `{"error": "invalid arguments: ..."}` (checked by the loop before the tool runs, and again inside the tool) |

**Worst thing it could do with strange or dangerous input:** `lookup` only does dictionary/regex matching on a fixed in-memory corpus: no file paths, no SQL, no code execution, so input cannot make it read anything outside `data/corpus.jsonl`. The realistic worst case is a **silent wrong fact**: matching a misspelled name to the wrong similar district ("Ossbrdge" → Ossford) or returning an archived/uncorrected number. That is why it never auto-corrects names (it only *suggests*) and never falls back to archived profiles. A very long input string is truncated before fuzzy matching so it cannot slow the tool down. Output is always a short JSON object (one sentence of evidence, ≤ 300 characters), never whole documents.

#### `calculate`

```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Evaluate ONE arithmetic expression exactly and return the result at full precision. Use it for every calculation (ratios, differences, percentages, unit conversions) instead of doing arithmetic yourself. Allowed: numbers (no thousands separators), + - * / // % **, unary minus and parentheses. No variables, names or functions. Example: \"44675/921.4 - 37203/758.6\".",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Arithmetic expression, e.g. \"(52904/1284.6) - (30982/846.2)\". Max 300 characters."
        }
      },
      "required": ["expression"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression": "44675/921.4", "result": 48.48600...}` |
| syntax error (`"2 +* 3"`, `"52,904/2"`) | `{"error": "could not parse expression: ... (do not use thousands separators)"}` |
| forbidden element (name, call, attribute, string, subscript, lambda…) e.g. `__import__('os').system('echo hi')`, `(1).__class__` | `{"error": "not allowed in expression: Call"}` / `"...: Attribute"` — refused while checking the syntax tree, before anything is evaluated |
| too-large power (`9**9**9`) | `{"error": "exponent too large (max 100)"}` — the exponent is checked before the power is computed |
| result too large | `{"error": "result too large (|x| > 1e15)"}` |
| division by zero | `{"error": "division by zero"}` |
| empty / too long (> 300 chars) | `{"error": "expression is empty"}` / `{"error": "expression too long"}` |

**Worst thing it could do with strange or dangerous input:** with `eval` it would run arbitrary Python (delete files, read the API key from the environment, open network connections). With an `ast` whitelist it never executes anything: it parses the string to a tree and only walks number, binary-operator and unary-operator nodes. The remaining risk is **resource exhaustion** — `9**9**9`, or many large multiplications, would freeze the process or eat memory. That is closed by: an exponent limit (|exp| ≤ 100) checked *before* computing the power, a magnitude limit on every intermediate result, a 300-character limit and a node-count limit. A model could still pass a *wrong but valid* expression — the tool cannot know the formula is wrong; that stays the model's responsibility.

### A3 — Q-09 by hand

```json
[
  {"role": "system", "content": "You answer questions about the Nine Rivers Region using only the tools lookup and calculate. ... End with one line: ANSWER: <name or yes/no> | <number>"},
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"population\"}"}},
    {"id": "call_2", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"area_km2\"}"}},
    {"id": "call_3", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"population\"}"}},
    {"id": "call_4", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"area_km2\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"district\": \"Brightwater\", \"field\": \"population\", \"year\": 2025, \"value\": 44675, \"unit\": \"residents\", \"source\": \"NR-05\", \"evidence\": \"Census population: 39,902 in 2020 and 44,675 in 2025.\"}"},
  {"role": "tool", "tool_call_id": "call_2", "content": "{\"district\": \"Brightwater\", \"field\": \"area_km2\", \"year\": 2025, \"value\": 921.4, \"unit\": \"km2\", \"source\": \"NR-16\", \"evidence\": \"The correct area is 921.4 square kilometres.\", \"note\": \"NR-05 says 912.4; corrected by notice NR-16\"}"},
  {"role": "tool", "tool_call_id": "call_3", "content": "{\"district\": \"Millbrook\", \"field\": \"population\", \"year\": 2025, \"value\": 37203, \"unit\": \"residents\", \"source\": \"NR-11\", \"evidence\": \"Census population: 34,590 in 2020 and 37,203 in 2025.\"}"},
  {"role": "tool", "tool_call_id": "call_4", "content": "{\"district\": \"Millbrook\", \"field\": \"area_km2\", \"year\": 2025, \"value\": 758.6, \"unit\": \"km2\", \"source\": \"NR-11\", \"evidence\": \"...stretches along the Mill Brook over 758.6 square kilometres...\"}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_5", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"44675/921.4\"}"}},
    {"id": "call_6", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203/758.6\"}"}},
    {"id": "call_7", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203/758.6 - 44675/921.4\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_5", "content": "{\"expression\": \"44675/921.4\", \"result\": 48.48600}"},
  {"role": "tool", "tool_call_id": "call_6", "content": "{\"expression\": \"37203/758.6\", \"result\": 49.04166}"},
  {"role": "tool", "tool_call_id": "call_7", "content": "{\"expression\": \"37203/758.6 - 44675/921.4\", \"result\": 0.55566}"},

  {"role": "assistant", "content": "Brightwater: 44,675 / 921.4 km² (corrected area, NR-16) = 48.486 residents/km². Millbrook: 37,203 / 758.6 km² = 49.042 residents/km². Millbrook is denser by 0.556 residents/km².\nANSWER: Millbrook | 0.556"}
]
```

(Results shortened to 5 decimals here; the tool returns full float precision.) Three model rounds: one with 4 parallel lookups, one with calculations, one final answer.

**My arithmetic:**

- Brightwater area: the profile NR-05 says 912.4 km², but correction NR-16 says the correct value is **921.4 km²**.
- Brightwater density = 44,675 / 921.4. 921.4 × 48 = 44,227.2; 44,675 − 44,227.2 = 447.8; 447.8 / 921.4 = 0.48600. → **48.486 /km²**
- Millbrook density = 37,203 / 758.6. 758.6 × 49 = 37,171.4; 37,203 − 37,171.4 = 31.6; 31.6 / 758.6 = 0.04166. → **49.042 /km²**
- Difference = 49.0417 − 48.4860 = **0.5557 → 0.6** (1 decimal). Millbrook is denser. ✓ matches the gold answer `Millbrook | 0.6`.
- With the uncorrected 912.4: 44,675 / 912.4 = 48.964, difference 0.078 → **0.1**. Same winner, wrong number — the typo trap only shows up in the magnitude, which is why the correction must be applied by the tool and not left to chance.

### A4 — Why I split it this way

**Rejected alternative: a free-text `search(query)` lookup that returns the matching sentences** (the "search phrase" option from the brief), with the model reading the numbers out of the sentences itself.

Why I did not choose it:

1. **It pushes every trap back onto the model.** A search for "Brightwater area" returns both "912.4 square kilometres" (NR-05) and "correct area is 921.4" (NR-16); a search for "Tarnvale population" returns the 2025 profile *and* the archived 2019 one; "Lindenmoor water" returns cubic metres. The model has to notice and resolve each conflict on every question, and step 2–5 (my most sensitive assumption, A1) becomes probabilistic instead of deterministic. That is exactly what S1/S2 already do with the whole corpus in the prompt — S3 would then mostly test "fewer tokens in context", not "a tool that removes failure modes".
2. **Harder to test without the model.** With `lookup(district, field)` I can unit-test "Brightwater area = 921.4 from NR-16" directly. With free-text search the correctness depends on how the model reads the sentences, which pytest cannot check.
3. **More tokens per round.** Sentences are longer than one JSON fact, and every tool result stays in the context for all later rounds.

What I give up: generality. A fixed field enum cannot answer a question about a figure I did not anticipate (e.g. "how many rivers"); a search tool could. For this corpus every question uses only the nine fields, so that trade is worth it. I also rejected the opposite extreme — **one tool per metric** (`density(district)`, `water_per_resident_day(district)` …) — because it hard-codes the 20 question types, hides the formula from the model and from the log, and would need a new tool for every new kind of question; `calculate` keeps arithmetic general while still making it exact.

---

## Part B — Build it and run it (Medium)

Code: [`tools.py`](tools.py) (the two tools, their schemas, argument validation), [`strategies.py`](strategies.py) (S1, S2, S3 and the loop), [`score.py`](score.py) (one scorer for all strategies), [`run.py`](run.py) (runs and saves everything), [`measure_tool_tokens.py`](measure_tool_tokens.py), [`tests/test_tools.py`](tests/test_tools.py).

Reproduce: `pip install -r requirements.txt`, put `OPENAI_API_KEY` in `.env`, then `python run.py --run 1` (S1+S2+S3 v1), `python run.py --run 1-S3v2 --strategies S3 --year-v2`, and the same with `2`. C1: `python run.py --run c1-yours --strategies S3 --year-v2 --questions Q-01,Q-03,Q-08,Q-09,Q-13` and the same with `--run c1-vague --vague`.

### What I changed from Part A while coding

1. **`reasoning_effort="none"` for every strategy.** The first S3 call failed with HTTP 400: *"Function tools with reasoning_effort are not supported for gpt-5.6-luna in /v1/chat/completions … set reasoning_effort to 'none'"* (`outputs/run-test` was re-run after this). To keep the strategies identical in everything except the strategy, I set `none` for S1 and S2 too. Side effect: S1 is now really "direct" (in my first S1 test with default reasoning the model used 285 hidden reasoning tokens per question and got 2/2; with `none` it writes ~35 tokens and gets 4–7/20). So the only reasoning in S2 is the reasoning it writes out.
2. **`temperature` = 1 everywhere.** The model rejects any other value (`temperature 0.7` → HTTP 400 *"Only the default (1) value is supported"*). S2's 5 samples still vary because 1 is a sampling temperature; S1 and S3 are also sampled at 1, which is why two runs of the same strategy differ.
3. **The `year` description of `lookup` (v1 → v2). This is the important one.** In the first two full runs S3 got only 15 and 14/20, although every fact `lookup` returned was correct and every calculation was exact. The logs showed why: the model sent `"year": 2020` for **population** in 22 of 34 population lookups (run 1) and `"year": 2024` for the **tariff** in every tariff lookup, so it divided by the 2020 census and used the 2024 tariff. My Part A description said *"Use 2020 only for population (2020 census) and 2024 only for the water tariff"*. I meant "2020 is only allowed for population"; the model read it as "for population, use 2020".
   - First hypothesis: the model takes the first enum value (`[2020, 2024, 2025]`). Test: same description, enum reordered to `[2025, 2024, 2020]`, on the 7 failing questions → **1/7**, still 13 of 15 population lookups with 2020 (`outputs/run-probe-enum-v2`). Rejected.
   - Second hypothesis: the wording. v2 says *"leave it out to get the 2025 figure, which is what almost every question needs … Send 2020 ONLY when the question explicitly asks about the 2020 census"*. Same 7 questions → **7/7** (`outputs/run-probe-year-desc-v2`). Then all 20, twice: **19/20 and 20/20**.
   - I kept the v1 runs in the main table (they are the plan from Part A) and report v2 as an extra row. Nothing else changed between v1 and v2: same model, prompts, tool code, field enum, questions.
4. **A validation layer in the loop** (`validate_args` in `tools.py`): the loop parses `arguments` with `json.loads`, rejects unknown tools, extra keys and wrong types *before* calling the tool, and sends an error result for that `tool_call_id` instead. The schema was not strict, so the model could (and once did) send a value outside the enum (`"field": "budget"`, Q-12, run 1-S3v2).
5. **The `evidence` sentence contains more than the asked figure.** Profiles mention 2020 and 2025 population in the same sentence, so `lookup(population, 2020)` also shows the 2025 number. In `outputs/run-test/S3/Q-09.json` the model asked for 2020 but used 44,675 (the 2025 figure) from the evidence. I kept it (the source sentence is useful for checking), but it means the model is sometimes reading text, not just the `value`.

### B2 — Tests

32 tests in `tests/test_tools.py` (15 for `lookup`, 16 for `calculate`, 1 for the loop's argument validation). No API key needed. Full output also in `outputs/pytest.txt`.

```text
$ python -m pytest -v
platform win32 -- Python 3.11.1, pytest-9.1.1, pluggy-1.7.0
collected 32 items

tests/test_tools.py::test_lookup_finds_2025_population PASSED            [  3%]
tests/test_tools.py::test_lookup_2020_population PASSED                  [  6%]
tests/test_tools.py::test_lookup_misspelled_name_suggests_but_does_not_guess PASSED [  9%]
tests/test_tools.py::test_lookup_similar_names_are_kept_apart PASSED     [ 12%]
tests/test_tools.py::test_lookup_ambiguous_prefix_is_an_error PASSED     [ 15%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Tarnvale-population-71388-65030] PASSED [ 18%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Tarnvale-water_use_megalitres-5207-4980] PASSED [ 21%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Kelmarsh-schools-11-10] PASSED [ 25%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Kelmarsh-pupils-3268-2944] PASSED [ 28%]
tests/test_tools.py::test_lookup_refuses_archived_year PASSED            [ 31%]
tests/test_tools.py::test_lookup_applies_correction_notice PASSED        [ 34%]
tests/test_tools.py::test_lookup_converts_cubic_metres_to_megalitres PASSED [ 37%]
tests/test_tools.py::test_lookup_water_tariff PASSED                     [ 40%]
tests/test_tools.py::test_lookup_bad_inputs_never_crash PASSED           [ 43%]
tests/test_tools.py::test_lookup_result_is_short PASSED                  [ 46%]
tests/test_tools.py::test_calculate_multiplication PASSED                [ 50%]
tests/test_tools.py::test_calculate_q09_expression PASSED                [ 53%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[__import__('os').system('echo hi')] PASSED [ 56%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[(1).__class__] PASSED [ 59%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[9**9**9] PASSED [ 62%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[open('x')] PASSED [ 65%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[x + 1] PASSED [ 68%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[[1, 2]] PASSED [ 71%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic['a' * 3] PASSED [ 75%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[lambda: 1] PASSED [ 78%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[True + 1] PASSED [ 81%]
tests/test_tools.py::test_calculate_refuses_non_arithmetic[(1).__class__.__bases__[0].__subclasses__()] PASSED [ 84%]
tests/test_tools.py::test_calculate_division_by_zero PASSED              [ 87%]
tests/test_tools.py::test_calculate_large_numbers PASSED                 [ 90%]
tests/test_tools.py::test_calculate_syntax_errors_and_commas PASSED      [ 93%]
tests/test_tools.py::test_calculate_precedence_and_unary PASSED          [ 96%]
tests/test_tools.py::test_run_tool_validates_json_arguments PASSED       [100%]

============================= 32 passed in 0.61s ==============================
```

The three dangerous inputs are refused while checking the syntax tree (`Call`, `Attribute`) or before computing the power (`9**9**9` → `exponent too large (max 100)`); the test also checks each takes < 1 s and prints nothing.

### B3 — The loop

- **Round limit, and why:** `MAX_ROUNDS = 8` model calls per question (`strategies.py`). The A3 walk-through needs 3 rounds (lookups → calculations → answer). The hardest shape (3 districts, pick max and min, then subtract) needs 4: lookups, ratios, difference, answer. One extra round for recovering from a tool error makes 5. 8 gives ~2× headroom over that while capping a runaway loop at about 8 × 2,000 = 16k input tokens (≈ $0.004) per question. Observed: max **5** rounds with v1 (Q-01, runs 1 and 2), max **4** with v2; **no question hit the limit** in any run (Unanswered = 0 everywhere). A question that hits the limit is saved with `"hit_round_limit": true` and an empty answer, and is scored as unanswered.
- **Where the logs are:** `outputs/run-<name>/<strategy>/<question>.json`, one file per question and strategy. Each has the final text, the parsed answer, every API call (`input_tokens`, `output_tokens`, `cached_tokens`, `seconds`, `round`), and for S3 every tool call (`round`, `id`, `name`, raw `arguments` string, `result`, `seconds`) plus the full message list. S2 logs keep all 5 samples and the vote counts. `outputs/run-<name>/summary.json` has the totals and settings; `outputs/console-*.txt` the printed summaries.
- **Real Q-09 conversation compared with my A3 version** (`outputs/run-1/S3/Q-09.json`):
  - **Same:** 3 rounds; round 1 is exactly my 4 parallel lookups (population and area for both districts); `lookup` returned 921.4 from NR-16 with the correction note, exactly as in A3; the answer is Millbrook | 0.556 → scored 0.6 ✓.
  - **Different:**
    1. The model always sends the optional `"year": 2025` explicitly (I left it out in A3).
    2. It put all three calculations into one round in parallel, including the difference, so it wrote the difference before seeing the two densities. It chose Brightwater − Millbrook = **−0.5557** and then flipped the sign in its text. That works here, but the same habit causes the Q-01 mistake in C2.
    3. The ids are random (`call_u3jtL1UeQvr1dXmw2itoJjjz`), not `call_1`…
    4. The final answer is not rounded (0.556), as the prompt asked.
    5. Input tokens grow each round: 690 → 1,127 → 1,298, because each round resends the whole history.
    6. Tool time is tiny (0.09–0.42 ms per call) compared with model time (1.5–2.1 s per round), so S3 latency is almost entirely model rounds.
  - In the v1 test run (`outputs/run-test/S3/Q-09.json`) the model asked for `population` with `"year": 2020` and still answered correctly, because it read 44,675 from the evidence sentence. That was my first hint of the year problem (change 3 above).

### B4 — Three strategies

**What I kept the same:**

| Setting | Value |
|---|---|
| Model | `gpt-5.6-luna`, Chat Completions API |
| Temperature | 1.0 for every call (the only value the model accepts) |
| Reasoning effort | `none` for every call (required for tools, see change 1) |
| Questions | the same 20, the question text sent verbatim as the user message, the same order |
| Answer format | identical `ANSWER_FORMAT` text in every system prompt (`ANSWER: <name or yes/no> | <number>`, no units or separators, ≥ 3 decimals) |
| Documents | S1 and S2: all 17 documents, the same text, in the system prompt. S3: none, only the 2 tools |
| What differs | only one instruction sentence (S1: "Give the answer directly, without showing your working"; S2: "Think step by step: write out which facts you use and every calculation"; S3: "get every fact with lookup and do every calculation with calculate") plus documents vs tools |
| k | S2: k = 5, majority vote over (name, number rounded to the question's `decimals`), ties → first sample. S1, S3: k = 1 |
| S3 loop | max 8 rounds, parallel tool calls allowed, the same tool code in v1 and v2 (only the `year` description differs) |
| Scorer | `score.py`, the same for all strategies |
| Retries | OpenAI client `max_retries=4`, plus 3 attempts in `run.py` (no question needed them) |
| Concurrency | 4 questions in parallel; S2's 5 samples in parallel |
| Price | $0.20 / 1M input, $1.20 / 1M output tokens (GPT-5.6 Luna list price after the 30 July 2026 cut, as listed on aggregator sites; I could not open OpenAI's pricing page directly). Cached-token discounts are **not** applied, so the costs are an upper bound |

**My rule for a correct answer** (written before the first full run, implemented in [`score.py`](score.py)):

- The reply must contain a line `ANSWER: <name> | <number>`; if there are several, the **last** one counts. No such line (or the S3 loop hit its round limit) → **unanswered**, and unanswered counts as wrong.
- **Name:** must equal the gold `answer` exactly, ignoring only letter case and surrounding spaces / `*` / quotes (`millbrook` = `Millbrook`; `Millbrook district` ≠ `Millbrook`).
- **Number:** units and thousands separators are stripped, the number is rounded to the gold `decimals`, and it must be within one unit of the last digit of the gold `value`: `|round(x, decimals) − value| ≤ 10^−decimals`. So for Q-09 (`0.6`, 1 decimal) any of 0.5–0.7 after rounding is accepted, for Q-05 (`14235`, 0 decimals) 14234–14236.
- **Both** must hold. A right name with a wrong number is wrong (the "by how much" part is half the question).
- The model is told to give at least 3 decimals and never sees `decimals`, so rounding is done by the scorer, the same way for all three strategies. In S2 the vote is taken over `(name, number rounded to decimals)` pairs, using the same rounding.

Why this rule: the tolerance of one last-digit unit absorbs legitimate rounding-order differences (e.g. rounding densities before subtracting), but it does **not** absorb any trap: the uncorrected Brightwater area gives 0.1 instead of 0.6 on Q-09, unconverted Lindenmoor water is off by ×1000, archived Tarnvale figures change Q-02 by far more than 0.01. An exact-match rule would punish correct reasoning for formatting; a percentage tolerance (say ±5 %) would accept Q-09 = 0.57… but also accept wrong answers on large values like Q-18 (40013 ± 2000 would include "no, it stays below 40,000").

**Why 20 questions and two runs:** 20 is the question set we were given, and it covers every trap at least twice (similar names: Q-01, Q-16; archived profiles: Q-02, Q-03, Q-14, Q-15; correction: Q-09; m³ unit: Q-03; Q-19 uses Lindenmoor without water, as a control). Because temperature is fixed at 1, a single run mixes the strategy effect with sampling noise, so I ran everything twice to measure that noise (C4).

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 4 | 0 | 43,880 | 698 | 1.55 | 44.4 | 0.0096 |
| 1 | S2 think and vote (k = 5) | 14 | 0 | 220,300 | 17,964 | 2.56 | 51.7 | 0.0656 |
| 1 | S3 tools (v1, as planned in Part A) | 15 | 0 | 71,348 | 5,854 | 5.30 | 110.4 | 0.0213 |
| 1 | S3 tools (v2, `year` description fixed) | **19** | 0 | 73,234 | 5,705 | 5.47 | 136.7 | 0.0215 |
| 2 | S1 direct | 7 | 0 | 43,880 | 804 | 1.58 | 46.1 | 0.0097 |
| 2 | S2 think and vote (k = 5) | 15 | 0 | 220,300 | 17,780 | 2.42 | 51.3 | 0.0654 |
| 2 | S3 tools (v1, as planned in Part A) | 14 | 0 | 72,989 | 6,096 | 5.30 | 111.0 | 0.0219 |
| 2 | S3 tools (v2, `year` description fixed) | **20** | 0 | 70,599 | 5,744 | 5.28 | 134.3 | 0.0210 |

Notes on the measures:
- **Tokens** are summed from `usage` of every call: 20 calls for S1, 100 for S2 (5 per question), 63–67 for S3 (every loop round).
- **Seconds per question** is wall time for that question. S2's 5 samples run in parallel, so its time is the slowest sample; run one after another they would take about 5 × 2.4 s. **Total seconds** is the sum over the 20 questions. Questions ran 4 at a time, so the real wall clock was shorter.
- **Cached tokens:** 98–99 % of S1/S2 input tokens and 45–64 % of S3 input tokens were reported as `cached_tokens`, so the real bill is lower than the cost column, most of all for S2.
- The whole homework (both runs, v2 runs, probes, C1, tests) cost about **$0.28** at list price.

**Per question (run 1, and run 2 after the slash):**

| Question | S1 | S2 | S3 (v1) | S3 (v2) |
|---|:---:|:---:|:---:|:---:|
| Q-01 | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| Q-02 | ✗ / ✗ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-03 | ✗ / ✗ | ✓ / ✓ | ✓ / ✗ | ✓ / ✓ |
| Q-04 | ✗ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-05 | ✗ / ✗ | ✗ / ✗ | ✓ / ✗ | ✓ / ✓ |
| Q-06 | ✗ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-07 | ✗ / ✗ | ✓ / ✓ | ✗ / ✗ | ✓ / ✓ |
| Q-08 | ✗ / ✗ | ✗ / ✓ | ✗ / ✗ | ✓ / ✓ |
| Q-09 | ✗ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-10 | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-11 | ✗ / ✗ | ✓ / ✓ | ✗ / ✓ | ✓ / ✓ |
| Q-12 | ✗ / ✗ | ✗ / ✗ | ✓ / ✓ | ✓ / ✓ |
| Q-13 | ✗ / ✗ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-14 | ✗ / ✗ | ✗ / ✗ | ✓ / ✗ | ✓ / ✓ |
| Q-15 | ✗ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-16 | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-17 | ✗ / ✗ | ✓ / ✗ | ✗ / ✗ | ✓ / ✓ |
| Q-18 | ✓ / ✗ | ✗ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-19 | ✗ / ✗ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| Q-20 | ✗ / ✗ | ✗ / ✗ | ✗ / ✓ | ✓ / ✓ |
| **Total** | **4 / 7** | **14 / 15** | **15 / 14** | **19 / 20** |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

I re-ran S3 (v2 tools) on five questions that each hit a different trap: Q-01 (similar names), Q-03 (m³ unit), Q-08 (tariff), Q-09 (correction), Q-13 (2020 census). The only change was the top-level `lookup` description, replaced by `"Looks things up."`. The parameter schema (field enum, the `year` description) stayed the same. Logs: `outputs/run-c1-yours`, `outputs/run-c1-vague`.

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-01 | 5 (4 lookup + 1 calc), 3 rounds | 7 (4 lookup + 3 calc), 4 rounds | Ossford \| 4.570 ✗ | Ossbridge \| 4.570 ✓ |
| Q-03 | 5, 3 rounds | 5, 3 rounds | Lindenmoor \| 5.340 ✓ | Lindenmoor \| 5.340 ✓ |
| Q-08 | 4, 3 rounds | 4, 3 rounds | Brightwater \| 72.456 ✓ | Brightwater \| 72.456 ✓ |
| Q-09 | 7, 3 rounds | 7, 3 rounds | Millbrook \| 0.556 ✓ | Millbrook \| 0.556 ✓ |
| Q-13 | 9, 3 rounds | 9, 3 rounds | Coldharbour \| 4.159 ✓ | Coldharbour \| 4.159 ✓ |

**What changed:** almost nothing. In 4 of 5 questions the vague version made the **same tool calls with the same arguments** (same districts, fields, years, even the same expressions) and gave the same answer. The only difference is Q-01. There the "yours" run wrote the difference in one expression and then named the wrong district. That is the same decision slip as in run 1-S3v2 (C2), not a lookup problem: both versions got exactly the same four facts. The vague description saved about 155 input tokens per request (615 → 460 tokens of tool definitions, `outputs/tool_tokens.json`), which is why the vague run used fewer input tokens in total (15,643 vs 16,707).

**Why:** the model does not learn how to call `lookup` from the one-line description alone. It learns it from the whole schema: the name `lookup`, the `field` **enum** (nine self-explaining names like `water_use_megalitres`), the `district` and `year` parameter descriptions, and the S3 system prompt ("get every fact with the lookup tool"). The traps are handled inside the tool, so the model does not need the description to tell it about corrections or archives. The returned `note` and `source` fields show it anyway.

**But descriptions do matter, a lot: the evidence is the `year` parameter.** One sentence of the `year` description (v1 → v2, change 3 in Part B), with everything else identical, moved S3 from **15 / 14** to **19 / 20** correct. In v1 the model sent `year: 2020` in 40 of 70 population lookups and `year: 2024` in every tariff lookup, across both runs. In v2 it sent 2020 only in the growth questions (Q-02, Q-13, Q-18) and 2025 everywhere else, in both runs. So the model follows the parameter-level text very literally, and a precise but ambiguous phrase ("2020 only for population") did more damage than a vague one-line tool description. The lesson for writing tools: the text that sits next to the argument the model has to choose is the text that matters.

### C2 — Three mistakes explained

**S1 — Q-09, run 1: `ANSWER: Brightwater | 2.170` (gold Millbrook | 0.6).** Log `outputs/run-1/S1/Q-09.json`, the whole reply:

> Brightwater has the higher population density by 2.17 residents per square kilometre.
> ANSWER: Brightwater | 2.170

With `reasoning_effort: none` and "answer directly", the model has to do two long divisions (44,675 / 921.4 and 37,203 / 758.6) and a subtraction in a single forward pass, without writing any digit down. The difference between the two densities is 0.56 out of ~49, about 1 %, so the error in a "mental" estimate of each density is larger than the gap itself, and the winner flips. It also cannot show whether it used 912.4 or 921.4: even 44,675/912.4 = 48.96 does not give Brightwater, so this is an arithmetic error, not the correction trap. S1's errors are mostly the right name with a wrong number: it named the right district in 13/20 (run 1) and 15/20 (run 2) questions but had the right number in only 4 and 7. Examples: Q-03 0.511 instead of 5.34, Q-07 16.295 instead of 18.496. The model "knows" which facts to use but cannot compute without writing. Between run 1 and run 2 S1 went from 4 to 7 correct, and 5 questions changed result: the arithmetic is effectively a random guess near the right value.

**S2 — Q-14, both runs: all 5 samples say `ashgrove | 0.0` (gold Ashgrove | 4.9).** Log `outputs/run-1/S2/Q-14.json`, `votes: {"ashgrove | 0.0": 5}`. Sample 1:

> Tarnvale: 5,207 × 1,000,000 ÷ 71,388 ÷ 365 = 0.199827… litres per resident per day.
> Ashgrove: 4,390 × 1,000,000 ÷ 58,760 ÷ 365 = 0.204727… litres per resident per day.
> ANSWER: Ashgrove | 0.005

The facts and the formula are right (it even uses 71,388, the 2025 figure, not the archived one), but it divides wrongly by a factor of 1,000: the true values are 199.8 and 204.7 L/day. All 10 samples in the two runs made the **same** error, so the vote was unanimous and wrong.

Voting works because sampling at temperature 1 makes each sample's error partly random. If each sample is right with probability p > 0.5 and the samples are independent, the majority is right more often than one sample is. It fixes Q-09, Q-11, Q-13, Q-19, where S1 sometimes guessed wrong but most chains of thought got it right. Voting stops working in two cases, and both show up here:

1. **Correlated errors.** If the same prompt pushes every sample into the same mistake (here, a ×1000 slip in a long chain of conversions), the samples are not independent, p ≈ 0 for the right answer, and 5 votes are just 5 copies of the wrong one.
2. **Continuous answers.** On Q-05 (run 1) the 5 samples gave 14230, 14240, 14214, 14269, 14238: five *different* numbers, all off by small arithmetic errors, none within ±1 of 14235. A vote needs at least two samples to agree *exactly* after rounding. When each sample's number has independent noise wider than the tolerance, there is no majority to find, and the "winner" is just the first sample. Voting reduces the variance of a discrete choice (which district). It does not reduce the error of a number that has to be correct to the last digit. Q-12 (63.9, 63.8, 64.0, 64.1 vs 64.4) and Q-20 (2994–3001 vs 2993) fail the same way.

A third, smaller failure is format splitting: on Q-18 run 1 two samples wrote `Millbrook, yes | 40013` and only one wrote `yes | 40013`, so the wrong string won the vote although 4/5 samples had the right content.

S2 pays for all this: 5 × the input tokens of S1 plus 25 × the output tokens, because it writes the working out.

**S3 — Q-01, run 1 with v2 tools: `ANSWER: Ossford | 4.570153872` (gold Ossbridge | 4.6).** Log `outputs/run-1-S3v2/S3/Q-01.json`:

```text
round 1  lookup Ossbridge population 2025 -> 52904 (NR-01)   lookup Ossbridge area_km2 -> 1284.6 (NR-01)
         lookup Ossford   population 2025 -> 30982 (NR-02)   lookup Ossford   area_km2 -> 846.2  (NR-02)
round 2  calculate "52904/1284.6-30982/846.2" -> 4.57015387231975
round 3  "Ossford has the higher 2025 population density … the difference is 4.570153872 …"
```

Every fact is right and the similar-names trap was handled: NR-01 and NR-02 were kept apart. The calculator result is exact. The error is in step 7 of my plan (*Decide*, done by the model). The model computed only the **difference** Ossbridge − Ossford, got a positive number, and then named the wrong district. A positive result means the *first* term (Ossbridge) is larger. Without the two densities written separately, the model has to infer the winner from the sign of an expression it wrote itself, and it got that wrong. In run 2, and in the vague C1 run, it computed 41.18 and 36.61 separately and got it right.

This mistake shows exactly what a calculator does and does not bound. The tool makes the *arithmetic* error zero: every S3 v2 number is exact to 15 digits, so the whole class of S1/S2 errors above (Q-05, Q-12, Q-14, Q-20) disappears. The model cannot do this itself, because a transformer predicts digits one token at a time from patterns, with no carry or division algorithm it is guaranteed to run. The tool cannot check that the *formula* or the *decision* is right. In S3 v1 the formula used the wrong year (14–15/20); in v2 the decision from the sign failed once (19/20).

**Why the loop needed that many rounds, and why each round costs more:** Q-01 in v1 needed **5 rounds**, the most of any question (`outputs/run-1/S3/Q-01.json`): round 1 asked for population with `year: 2020`; round 2 asked again for 2025 when it noticed the census years; round 3 computed the two densities; round 4 the difference; round 5 the answer. Input tokens per round: **690 → 1,128 → 1,353 → 1,470 → 1,540**. Each round resends the system prompt, the ~560 tokens of tool definitions, the question, every earlier assistant message and every tool result, so round *n* costs roughly the fixed part plus everything produced in rounds 1…n−1. The total grows roughly quadratically with the number of rounds. Prompt caching (45–64 % of S3 input tokens were cached) softens the price but not the token count.

### C3 — Which strategy I would use, and what would change it

**I would use S3 (tools), with the v2 tool definitions.**

| Over 2 runs (40 answers) | S1 | S2 (k = 5) | S3 v1 | S3 v2 |
|---|---:|---:|---:|---:|
| Correct | 11/40 (28 %) | 29/40 (73 %) | 29/40 (73 %) | **39/40 (98 %)** |
| Input tokens / question | 2,194 | 11,015 | 3,608 | 3,596 |
| Output tokens / question | 38 | 894 | 149 | 144 |
| Cost / question (list price) | $0.0005 | $0.0033 | $0.0011 | $0.0011 |
| Median seconds / question | 1.6 | 2.5 (parallel) | 5.3 | 5.4 |

**Why not S2:** it is the only real competitor on accuracy, and it lost by 10 answers out of 40 while costing **3× more** than S3 (5 × the prompt with all documents, plus long written reasoning). More important is *why* it lost. Its remaining errors (Q-05, Q-12, Q-14, Q-20 in both runs) are arithmetic errors. Voting cannot fix those (C2: correlated or continuous errors), and raising k would only make S2 more expensive without addressing them. S2 is faster per question (2.5 s vs 5.4 s) only because I ran its 5 samples in parallel. It still does 5× the work.

**Why not S1:** it is the cheapest (3× cheaper than S3) and fastest (1.6 s), but 28 % correct is not usable. It almost always picks the right name and then gets the number wrong (C2), and the number is half of every question.

**Why S3:** highest accuracy (39/40), the second-lowest cost, and its errors are visible in a log: every fact has a `source` id and every number has an expression. Its weaknesses: latency (3–4 sequential model rounds, about 2× S2's wall time) and **sensitivity to the tool design**. The S3 I planned in Part A got 29/40, no better than S2, until I fixed one sentence. So "S3 wins" really means "S3 with carefully tested tool descriptions wins".

**Situations that would change my choice:**

1. **Strict time limit (e.g. an answer within 2 s).** S3 cannot make it: even one model round plus the answer round takes about 3 s, and these questions need 3–4 rounds. I would pick **S2 with samples in parallel** (median 2.4–2.6 s), or S2 with fewer samples, and accept about 73 % accuracy. Alternatively I would let the model emit all lookups and the full formula in a single round (fewer, larger rounds).
2. **1,000× more documents (~2.3 M tokens).** S1 and S2 become impossible: the documents no longer fit in the context window, and even if they did, S2 would cost ~$2.30 per question at list price. **S3** is the only option, because its cost does not depend on corpus size, only on the facts the question needs. `lookup` would need an index (Final question 6).
3. **Questions with no arithmetic** (single facts, or trivial sums like Q-10 and Q-16, which *every* strategy got right in both runs). **S1** is enough: 1 call, 1.6 s, a third of S3's cost, and the tools add nothing.
4. **Very small budget with accuracy still mattering.** S3 stays the choice: it is already 3× cheaper than S2 and 4× more accurate than S1. Only if I could pay ≈ $0.0005 per question and no more would I fall back to S1 and accept its accuracy.
5. **Open-ended questions about figures my field enum does not cover** (e.g. "which river does Kelmarsh lie on?"). My `lookup` cannot answer at all. I would use **S2**, or S3 with a free-text search tool (the alternative I rejected in A4).

### C4 — How sure I can be

- **How different were my two runs?** Totals: S1 4 vs 7 (Δ3), S2 14 vs 15 (Δ1), S3 v1 15 vs 14 (Δ1), S3 v2 19 vs 20 (Δ1). The totals hide more churn per question: the result of 5 questions changed between runs for S1, 3 for S2, 5 for S3 v1, and 1 for S3 v2. All runs use temperature 1, so this is sampling noise, and it is the floor for any difference I claim.
- **Is the difference between my two best strategies bigger than that?**
  - S3 **v1** vs S2: 15/14 vs 14/15, 29 vs 29 over 40 answers. The gap (0) is smaller than the run-to-run change, so **I cannot rank them**.
  - S3 **v2** vs S2: 39 vs 29 of 40. Paired by question, v2 was right where S2 was wrong 11 times, and the reverse happened once (Q-01, run 1). An exact sign test on 11 vs 1 gives p ≈ 0.006. Counting each question once (the runs share the same 20 questions, so the 40 answers are not independent), the per-run gap of 5 is still 5× the run-to-run change of S2. This difference is real for *these* 20 questions.
  - The plain 95 % confidence interval for one strategy on 20 questions is wide. At 75 % it is about ±19 points (√(0.75·0.25/20) ≈ 0.097). At 97.5 % (S3 v2) the Wilson interval for 39/40 is about 87–100 %.
- **Caveats that make me less sure than the p-value suggests:**
  1. The v2 description was fixed **after** I saw the v1 failures on these same 20 questions. The fix is generic (it mentions no question or answer), but it was still tuned on the test set. A fair estimate of v2's accuracy needs new questions.
  2. I spent design effort only on S3. The S1/S2 prompts are one sentence each and were not tuned (for example, "give every intermediate result to 6 significant digits" might help S2).
  3. Two runs give only a rough estimate of the run-to-run noise.
  4. One model, and one hand-made corpus where every question has the same shape.
- **How many questions would I need?** For a gap as large as S3 v2 vs S2 (~25 points), 20 questions were just enough. The usual estimate n ≈ (1.96 + 0.84)² · (p₁q₁ + p₂q₂) / Δ² with p₁ = 0.97, p₂ = 0.72 gives n ≈ 29 per strategy for 80 % power. So **30–50 fresh questions** would make the S3-v2 > S2 ranking reliable. To separate S2 from S3 v1 (a true gap of maybe 0–5 points) I would need ~1,000+ questions, so for practical purposes they are tied. To show that S2 beats S1, the 20 already suffice (~45 points apart in both runs).

### Final questions

1. **When the model sends a `tool_calls` message, what has actually run so far?** Only the model: it generated tokens that spell out a JSON request (tool name + an `arguments` string). No `lookup` and no `calculate` has run. The tools run only when *my* loop parses the request, validates it and calls the Python function. In my logs the model rounds take 1.2–2.1 s and the tools 0.1–0.7 ms, so the two are clearly separate steps. If my loop decided not to run the call, nothing would happen.
2. **Why does `arguments` arrive as a string, and what goes wrong if you pass it straight in?** The model outputs text, so the arguments are text that is *supposed* to be JSON, and nothing guarantees it is valid JSON or matches the schema (no strict mode). Passing the string straight into `lookup(arguments)` would put the whole JSON text into `district`. `json.loads` without checks lets wrong types, extra keys (→ `TypeError` on `**args`, crashing the loop) or values outside the enum through. This happened: in Q-12 (run 1-S3v2) the model sent `"field": "budget"`, which is not in the enum. My loop sent back `unknown field 'budget'; valid fields: …`, and the model fixed it in the next round.
3. **How many tokens do your two tool definitions add to every S3 request?** Measured with `measure_tool_tokens.py` (the same 1-line request with and without `tools`, comparing `usage.prompt_tokens`): **561 tokens** for the v1 definitions, **615** for v2, and 460 with the vague lookup description (`outputs/tool_tokens.json`). They are sent in every round, so in run 2-S3v2 they were 63 rounds × 615 ≈ 38,700 of 70,599 input tokens, **about 55 % of everything S3 sent**.
4. **How much more did S2 cost than S1?** Run 1: $0.0656 vs $0.0096, **6.8×** (run 2: 6.7×). Input tokens are exactly 5.0× (220,300 vs 43,880), because S2 sends the same ~2,190-token prompt 5 times. Output tokens are 26× (17,964 vs 698), because each S2 sample writes ~180 tokens of working while S1 writes ~35. Output tokens cost 6× more per token, so the reasoning text makes S2 more than 5× as expensive. Since 99 % of S2's input was cached, the real price difference is probably smaller, but the token count is not.
5. **Which question needed the most rounds in S3, and why?** With v1 tools, **Q-01 (5 rounds, 9 tool calls)** in both runs: it first fetched 2020 populations (the year-description bug), then fetched 2025 populations in a second round, then computed the densities, then the difference, then answered. With v2 the maximum was 4 rounds (Q-03, Q-05, Q-11, Q-12, Q-20). Q-11 and Q-20 (three districts, "highest minus lowest") need a round to compute three ratios, and only then can the model see which is highest and lowest and subtract them in the next round. Q-12 used its extra round recovering from the `"field": "budget"` error.
6. **What would you change in `lookup` if there were 100,000 documents?** Extract once, offline: parse every profile into a table `(district, field, year, value, unit, doc_id, published_date, status)`, apply corrections and archive status there, and let `lookup` query that table (a dict or SQLite with an index on district + field). Name matching would use an index of entity names instead of `difflib` over everything. For questions outside the fixed fields, add a `search` tool backed by BM25 or embeddings that returns the top-k short passages with their ids and dates. Prefer the newest non-archived document and flag conflicts instead of returning the first match. Cap and paginate the results so a tool result never brings large text back into the context.
7. **What stops your `calculate` from running dangerous code? Could the model still make it misbehave?** It never calls `eval` or `exec`. It parses the string with `ast.parse(mode="eval")` and walks the whole tree **before evaluating anything**. Any node that is not a number constant, `BinOp` (+ − × ÷ // % **) or `UnaryOp` (±) is refused. So names, calls, attributes, subscripts, strings, lambdas and comprehensions cannot run: `__import__('os')…` fails as `Call`, `(1).__class__` as `Attribute`. Resource attacks are capped: max 300 characters and 200 nodes, the exponent is checked to be ≤ 100 *before* the power is computed (`9**9**9` is refused in microseconds), every intermediate result must stay below 10¹⁵, and division by zero returns an error. It can still misbehave in harmless ways: floating-point rounding (`0.1+0.2` → 0.30000000000000004), and above all **a valid but wrong expression**. The calculator returns the exact value of whatever the model wrote, as with the 2020 populations in v1 or the reversed subtraction in Q-09.
8. **For which kind of question did tools help most, and for which did they not help at all?** They helped most on **multi-step ratios with big numbers or unit conversions**: budget per resident (Q-05, Q-20), litres per resident per day (Q-03, Q-14), tariff per resident (Q-17), budget per pupil (Q-12). S1 and S2 got these wrong in both runs by small or ×1000 arithmetic slips, and S3 v2 got them all right. They did not help at all on **questions with trivial arithmetic**: Q-10 (1845 − 1837) and Q-16 (1,284.6 + 846.2 − 2,106.9) were correct for **every** strategy in **both** runs, and S3 just spent 3× S1's tokens and 3× its time on them. The tools also do not help with **decision mistakes**: naming the wrong district from the sign of a difference (Q-01) can happen with exact numbers.
