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

### What I changed from Part A while coding

<!-- what changed in your plan, and why. "None" is an answer too. -->

### B2 — Tests

```text
<!-- pytest output -->
```

### B3 — The loop

- Round limit, and why:
- Where the logs are:
- Real Q-09 conversation compared with my A3 version, what is different:

### B4 — Three strategies

**What I kept the same:**

<!-- model, temperature, k, prompts, answer format, anything else -->

**My rule for a correct answer** (written before the first full run):

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | | | | | | | |
| 1 | S2 think and vote (k = ) | | | | | | | |
| 1 | S3 tools | | | | | | | |
| 2 | S1 direct | | | | | | | |
| 2 | S2 think and vote (k = ) | | | | | | | |
| 2 | S3 tools | | | | | | | |

**Per question (run 1):**

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | | | |
| Q-02 | | | |
| Q-03 | | | |
| Q-04 | | | |
| Q-05 | | | |
| Q-06 | | | |
| Q-07 | | | |
| Q-08 | | | |
| Q-09 | | | |
| Q-10 | | | |
| Q-11 | | | |
| Q-12 | | | |
| Q-13 | | | |
| Q-14 | | | |
| Q-15 | | | |
| Q-16 | | | |
| Q-17 | | | |
| Q-18 | | | |
| Q-19 | | | |
| Q-20 | | | |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| | | | | |

### C2 — Three mistakes explained

### C3 — Which strategy I would use, and what would change it

### C4 — How sure I can be

### Final questions

1.
2.
3.
4.
5.
6.
7.
8.
