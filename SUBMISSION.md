# HW4 — submission

**AI assistance:** Claude Code (Anthropic, model Claude Opus 5.5) helped me draft Part A, write the code and tests, and run the experiments. <!-- TODO: say in your own words what you did yourself and what you checked -->

**Deviation from the brief:** the brief asks for OpenAI `gpt-5.6-luna`. I use the **Anthropic Claude API** instead (Messages API with `tools=[...]`). The tool definitions below therefore use Anthropic's format (`input_schema` instead of `parameters`), and tool requests come back as `tool_use` content blocks with an `id`, answered by `tool_result` blocks with the matching `tool_use_id`. The ideas (the model only *asks*, my code decides what runs) are the same.

---

## Part A — Plan on paper (Easy)

> Commit this whole part before any `.py` file exists.

### A1 — The steps

Every question in `questions.json` has the same shape: *take one or more facts about 1–3 districts, combine them with arithmetic into a metric per district, compare, and report a winner (or yes/no) plus one number.* I split that into seven steps. Each step owns exactly one kind of decision, so no two steps can disagree about the same thing.

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Tool, loop, or model? |
|---|---|---|---|---|---|
| 1 | **Plan the question**: find the districts, the metric (e.g. density = population / area) and the list of raw facts needed | `question: str` | `districts: list[str]`, `facts: list[(district: str, field: str)]`, `formula: str` (in words) | Metric not in the field list (e.g. "founding year" is fine, "GDP" is not) → the model must say it cannot answer, not invent a field. Misread question (e.g. "older" = smaller founding year) → wrong winner; nothing downstream can catch it. | **model** |
| 2 | **Resolve the name**: map a district name typed by the model to exactly one of the 12 canonical names | `name: str` | `canonical: str` | No match → error with the closest names. Two plausible matches (`Oss…` → Ossbridge / Ossford) → error listing both; **never guess**. Exact (case-insensitive) match only is accepted. | **tool** (`lookup`, inside) |
| 3 | **Pick the authoritative source**: choose the document that is allowed to answer `(district, field)` | `canonical: str`, `field: str` | `doc_id: str` (+ `corrected_by: str \| None`) | Only an ARCHIVED profile has the fact → refuse (archived profiles are never used). A correction notice exists for this field → the notice wins over the profile. No document has the field → error. | **tool** (`lookup`, inside) |
| 4 | **Read and normalise the value**: pull the number out of the text, convert to the standard unit | `doc_id: str`, `field: str` | `value: float`, `unit: str`, `evidence: str` (the one sentence it came from, ≤ 200 chars) | Number cannot be parsed → error, no value. Unit not one of the known ones (megalitres, cubic metres, km², km, million tenge, tenge/m³) → error. Lindenmoor gives water in m³ → converted to megalitres (÷ 1,000) and the conversion is stated in a `note`. | **tool** (`lookup`, inside) |
| 5 | **Do the arithmetic**: evaluate one expression built from the values of step 4 | `expression: str` (e.g. `"44675 / 921.4"`) | `result: float` (full precision) | Syntax error, a name / call / attribute in the expression, exponent too large, result too large, division by zero → error, nothing is run. | **tool** (`calculate`) |
| 6 | **Compare and answer**: decide which metric is larger (or yes/no), take the difference, round, write the final line | per-district metrics `float`, difference `float` | `ANSWER: <name or yes/no> \| <number>` (`str`) | Compares the wrong way round, rounds too early, or forgets the final line → scored wrong / unanswered. | **model** (the difference itself goes through step 5) |
| 7 | **Dispatch**: send the model's tool requests to the right function and send the results back | assistant message with `tool_use` blocks (`id: str`, `name: str`, `input: dict`) | user message with one `tool_result` per `id` | Unknown tool name, input that does not match the schema, tool exception → an error `tool_result` (`is_error: true`) for that `id`, never a crash. Round limit reached → question marked **unanswered**. | **loop** |

A separate eighth piece, **scoring**, lives outside the conversation (my run script): it reads the `ANSWER:` line and compares it with `questions.json`. The model never sees the correct answers.

**Why this set is complete and does not overlap:** a fact travels question → (1) which facts → (2) which district → (3) which document → (4) which number → (5) arithmetic → (6) answer, and (7) carries every request and result between the model and the tools. Remove any step and some question has no one responsible for that decision. Each decision has exactly one owner: only step 2 decides *which district*, only step 3 decides *which document* (archives and corrections), only step 4 decides *units*, only step 5 does *arithmetic*, only steps 1 and 6 do *reasoning about the question*.

**How the steps connect:**

```text
question (str)
   │
   ▼
[1 plan — model] ──(district, field) pairs──┐
                                             ▼
                             ┌─────── lookup tool ───────┐
                             │ [2 resolve name]          │
                             │      │ canonical          │
                             │      ▼                    │
                             │ [3 pick source]           │
                             │      │ doc_id             │
                             │      ▼                    │
                             │ [4 read + normalise]      │
                             └──────┬────────────────────┘
                                    │ value, unit, source, evidence
                                    ▼
[1/6 model writes an expression] ──► [5 calculate tool] ──► result (float)
                                    │   (repeat per district, then for the difference)
                                    ▼
                           [6 compare + answer — model]
                                    │  "ANSWER: name | number"
                                    ▼
                           [8 scoring — my run script]

[7 loop] wraps everything between the model and the two tools:
model → tool_use(id) → loop → tool → loop → tool_result(id) → model
```

**What I am assuming:**

- **Year.** "2025" means the 2025 census / 2025 fiscal year / calendar 2025 water use, as NR-00 says. "2020" figures come only from the "2020 census" phrases inside the 2025 profiles. The pupil numbers are for the school year 2025/26 and count as "2025".
- **Archived profiles (NR-13 Tarnvale, NR-14 Kelmarsh) are never used.** They are not even indexed by `lookup`; asking for a 2019 figure is an error.
- **Corrections win.** NR-16 replaces the Brightwater area (912.4 → **921.4** km²). `lookup` applies it and says so in the result, so the model cannot pick the old number.
- **Units.** Water use is returned in **megalitres** for every district. Lindenmoor's 2,151,400 m³ becomes 2,151.4 ML (1 ML = 1,000 m³, NR-15). The tariff is 142.35 tenge/m³ (2025), never the 2024 tariff.
- **Rounding happens once, at the very end** (step 6). Tools return full precision, so rounding errors cannot pile up.
- **Wording traps.** Stonecairn and Coldharbour say "up from" but their populations fell. `lookup` returns the numbers and ignores the words.

**The assumption the solution is most sensitive to:** that **`lookup` returns the authoritative number** (step 3 + 4 are right). In S3 the model never sees the documents. If `lookup` returned the archived Tarnvale population or the uncorrected Brightwater area, the model would have no way to notice, and every later step would be correct arithmetic on a wrong fact. For Q-09 the uncorrected area alone turns the right answer 0.6 into 0.1. That is why archives and corrections are handled *inside the tool* by fixed rules, and why the tests in B2 aim at exactly these cases.

### A2 — The two tools

#### `lookup`

I chose a **structured** lookup: one district + one field → one number. The model asks a precise question and gets a precise answer with its source, so it never has to read prose or fix units itself.

```json
{
  "name": "lookup",
  "description": "Look up ONE official 2025 fact about ONE district of the Nine Rivers Region (or a region-wide fact) and get back a single number with its unit and the id of the document it came from. Archived 2019 profiles are never used, and published corrections are applied automatically, so trust the value returned. Water use is always returned in megalitres. Call it once per (district, field) pair; you may call it several times in one turn. If the district name is not recognised, the result is an error listing the closest valid names: retry with one of them. For the household water tariff use district=\"region\" and field=\"water_tariff_tenge_per_m3\".",
  "input_schema": {
    "type": "object",
    "properties": {
      "district": {
        "type": "string",
        "description": "District name exactly as in the profiles (Ossbridge, Ossford, Tarnvale, Kelmarsh, Brightwater, Stonecairn, Harrowfield, Lindenmoor, Redfen, Ashgrove, Millbrook, Coldharbour), or \"region\" for region-wide facts."
      },
      "field": {
        "type": "string",
        "enum": [
          "population_2025", "population_2020", "area_km2",
          "budget_2025_million_tenge", "water_use_2025_megalitres",
          "schools", "pupils_2025_26", "paved_road_km", "founded_year",
          "water_tariff_tenge_per_m3"
        ],
        "description": "Which fact to return."
      }
    },
    "required": ["district", "field"],
    "additionalProperties": false
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district": "Brightwater", "field": "population_2025", "value": 44675, "unit": "residents", "source": "NR-05", "evidence": "Census population: 39,902 in 2020 and 44,675 in 2025."}` |
| success, corrected value | same shape plus `"source": "NR-16", "note": "corrected by NR-16; profile NR-05 says 912.4"` |
| success, converted unit | same shape, `"value": 2151.4, "unit": "megalitres"`, plus `"note": "profile NR-08 gives 2,151,400 cubic metres; converted at 1 ML = 1,000 m3"` |
| unknown / misspelled district | `{"error": "no district named 'Ossbrige'; did you mean Ossbridge or Ossford?"}` (never auto-corrected, because two names are this close) |
| ambiguous district (`"Oss"`) | `{"error": "'Oss' matches more than one district: Ossbridge, Ossford. Use the full name."}` |
| unknown field | `{"error": "unknown field 'gdp'; valid fields: population_2025, ..."}` |
| field not available for this district (e.g. `region` + `schools`) | `{"error": "field 'schools' is not available for 'region'"}` |
| number found but unreadable / unknown unit | `{"error": "could not read field 'area_km2' from NR-05"}`. Says which document failed and gives no value. |
| wrong input types / missing keys | the loop rejects it before the tool runs: `{"error": "invalid input: 'field' is required"}` |

**Worst thing it could do with strange or dangerous input:** `lookup` only *reads* an in-memory index built from `data/corpus.jsonl`. It never opens a file path, runs a query or executes text from the input. The inputs are matched against a fixed list of 12 names + `region` and a fixed `enum` of fields. So the worst realistic failure is **returning a wrong but plausible number**: a bug in a regex, or a district resolved to its look-alike. That error is silent, and the model in S3 cannot detect it. For that reason it never fuzzy-matches automatically, and every result carries `source` + `evidence` so a human can check it in the log. A very long input string is cut off (names > 50 chars → error), so it cannot blow up the context.

#### `calculate`

```json
{
  "name": "calculate",
  "description": "Evaluate ONE arithmetic expression exactly and return the numeric result at full precision. Use it for every calculation (divisions, differences, percentages, unit conversions) instead of doing arithmetic in your head. Allowed: numbers, + - * / ** %, unary minus and parentheses. Not allowed: variables, function calls, commas as thousands separators (write 44675, not 44,675). Example: \"(37203 / 758.6) - (44675 / 921.4)\".",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "The arithmetic expression, e.g. \"44675 / 921.4\". At most 200 characters."
      }
    },
    "required": ["expression"],
    "additionalProperties": false
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression": "44675 / 921.4", "result": 48.4859995659}` (rounded to 10 decimals only to remove float noise) |
| syntax error (`"44,675 / 921.4"`, `"2 +"`) | `{"error": "could not parse expression: ..."}` (the comma case gets a hint to remove thousands separators) |
| forbidden element (name, call, attribute, subscript, string, lambda…), e.g. `__import__('os').system('echo hi')`, `(1).__class__` | `{"error": "not allowed in expression: Call"}`, resp. `Attribute`. Rejected while the tree is checked, **before anything is evaluated** |
| exponent too large, e.g. `9**9**9` | `{"error": "exponent too large (max 100)"}`. The inner `9**9` is checked first, so the huge power is never computed |
| result too large (> 1e15 in absolute value) | `{"error": "result too large"}` |
| division by zero | `{"error": "division by zero"}` |
| expression longer than 200 characters / deeper than 50 nodes | `{"error": "expression too long"}` |

**Worst thing it could do with strange or dangerous input:** with `eval` the model could run any Python, read `.env` with my API key, delete files or freeze the machine with `9**9**9`. With an `ast` whitelist the only nodes that ever execute are numbers and the arithmetic operators I listed. Names, calls and attributes are rejected before evaluation, and exponents, size and length are capped. What it *can* still do: compute the **wrong** expression correctly (the model types 921.4 where it meant 912.4, or swaps numerator and denominator). The calculator removes arithmetic errors, not reasoning errors.

### A3 — Q-09 by hand

Q-09: *"Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"* In Anthropic's format, tool requests are `tool_use` blocks inside an assistant message, and the results are `tool_result` blocks inside the next user message. I expect the model to ask for the four facts in parallel in one turn.

```json
[
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?\n\nEnd your reply with exactly one line: ANSWER: <name or yes/no> | <number>"},

  {"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_01", "name": "lookup", "input": {"district": "Brightwater", "field": "population_2025"}},
    {"type": "tool_use", "id": "toolu_02", "name": "lookup", "input": {"district": "Brightwater", "field": "area_km2"}},
    {"type": "tool_use", "id": "toolu_03", "name": "lookup", "input": {"district": "Millbrook",   "field": "population_2025"}},
    {"type": "tool_use", "id": "toolu_04", "name": "lookup", "input": {"district": "Millbrook",   "field": "area_km2"}}
  ]},

  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "{\"district\": \"Brightwater\", \"field\": \"population_2025\", \"value\": 44675, \"unit\": \"residents\", \"source\": \"NR-05\", \"evidence\": \"Census population: 39,902 in 2020 and 44,675 in 2025.\"}"},
    {"type": "tool_result", "tool_use_id": "toolu_02", "content": "{\"district\": \"Brightwater\", \"field\": \"area_km2\", \"value\": 921.4, \"unit\": \"km2\", \"source\": \"NR-16\", \"evidence\": \"The correct area is 921.4 square kilometres.\", \"note\": \"corrected by NR-16; profile NR-05 says 912.4\"}"},
    {"type": "tool_result", "tool_use_id": "toolu_03", "content": "{\"district\": \"Millbrook\", \"field\": \"population_2025\", \"value\": 37203, \"unit\": \"residents\", \"source\": \"NR-11\", \"evidence\": \"Census population: 34,590 in 2020 and 37,203 in 2025.\"}"},
    {"type": "tool_result", "tool_use_id": "toolu_04", "content": "{\"district\": \"Millbrook\", \"field\": \"area_km2\", \"value\": 758.6, \"unit\": \"km2\", \"source\": \"NR-11\", \"evidence\": \"The district, founded in 1897, stretches along the Mill Brook over 758.6 square kilometres and keeps 360.1 km of paved road.\"}"}
  ]},

  {"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_05", "name": "calculate", "input": {"expression": "44675 / 921.4"}},
    {"type": "tool_use", "id": "toolu_06", "name": "calculate", "input": {"expression": "37203 / 758.6"}}
  ]},

  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_05", "content": "{\"expression\": \"44675 / 921.4\", \"result\": 48.4859995659}"},
    {"type": "tool_result", "tool_use_id": "toolu_06", "content": "{\"expression\": \"37203 / 758.6\", \"result\": 49.0416556815}"}
  ]},

  {"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_07", "name": "calculate", "input": {"expression": "37203 / 758.6 - 44675 / 921.4"}}
  ]},

  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_07", "content": "{\"expression\": \"37203 / 758.6 - 44675 / 921.4\", \"result\": 0.5556561156}"}
  ]},

  {"role": "assistant", "content": [
    {"type": "text", "text": "Brightwater: 44,675 residents on 921.4 km² (corrected area, NR-16) = 48.486 per km². Millbrook: 37,203 on 758.6 km² = 49.042 per km². Millbrook is denser by 0.556 residents per km².\nANSWER: Millbrook | 0.556"}
  ]}
]
```

That is 4 model turns (3 with tool calls + 1 final answer) and 7 tool calls.

**My arithmetic:**

- Brightwater: 44,675 / **921.4** (corrected, NR-16) = 48.4860 residents/km²
- Millbrook: 37,203 / 758.6 = 49.0417 residents/km²
- Difference: 49.0417 − 48.4860 = 0.5557 → rounded to 1 decimal = **0.6**, winner **Millbrook**. This matches `questions.json` (`Millbrook`, 0.6).
- Trap check: with the uncorrected area 44,675 / 912.4 = 48.9643, so the difference is 0.0774 → **0.1**. Using the profile without the correction notice gives the right winner but the wrong number.

### A4 — Why I split it this way

**Alternative I rejected: one `get_profile(district)` tool that returns the whole profile text** (plus the notices), and lets the model read the numbers itself.

It looks simpler: one tool, no regexes, works for any question. I did not choose it because it moves steps 3 and 4 (pick the authoritative source, normalise the unit) back into the model. Those are exactly the steps where the traps are: the archived Tarnvale/Kelmarsh profiles, the Brightwater correction and Lindenmoor's cubic metres. The model would then make the same kind of mistakes as in S1, just with extra round trips, so S3 would test nothing new. It also returns whole documents, which the brief forbids, and puts more tokens into every following round. With my split, the rules that must *always* hold (never use archives, corrections win, water in ML) are code, which I can test without a model (B2). The model keeps only what code cannot do well: understanding the question and choosing the formula.

**Also rejected: a separate tool per metric** (`density(district)`, `budget_per_resident(district)`, …). That would put the whole answer inside the tools. The model would only pick a function, and every new question type would need new code. The 20 questions already use about ten different metrics.

---

## Part B — Build it and run it (Medium)

### What I changed from Part A while coding

- **The tools themselves: no change.** Both definitions in `tools.py` are exactly the ones in A2. The `lookup` index follows the plan: archived profiles are never indexed, the correction is applied, and Lindenmoor's m³ are converted.
- **Small additions inside `lookup`.** It also accepts `"Brightwater district"` (trailing "district" is stripped), and for Tarnvale/Kelmarsh it adds `"archived_ignored": "NR-13"` / `"NR-14"` to the result, so the log shows that the archive was seen and skipped.
- **Validation (step 7) is in `tools.py` (`validate_args`)** and not only in the loop, so I can test it without the model (`tests/test_calculate.py::test_loop_validation_rejects_bad_arguments`). It also accepts `input` as a JSON *string*, the OpenAI way, although Anthropic's SDK already delivers a parsed `dict`.
- **S1 had to become structured output.** With thinking turned off, Claude Haiku 5.5 ignored "Reply with the ANSWER line only. Do not show any working." It wrote its calculations anyway (`outputs/smoke/s1/Q-09.json`: 381 output tokens of arithmetic before the ANSWER line). A stronger version of the instruction did not help either (Q-09: 361 tokens, Q-12: 479 tokens of working). That would turn S1 into a hidden single-sample S2. So S1 now asks for a JSON object `{"name": str, "number": float}` (`output_config.format` with a JSON schema). The code turns it into the same `ANSWER: name | number` line, so one parser scores all three strategies. This is the only part of the prompt that differs between S1 and S2 besides the reasoning instruction itself.

### B2 — Tests

```text
============================= test session starts =============================
platform win32 -- Python 3.13.15, pytest-9.1.1, pluggy-1.7.0 -- C:\Users\Arito\MyProgs\AI\css4007-hw4\.venv\Scripts\python.exe
rootdir: C:\Users\Arito\MyProgs\AI\css4007-hw4
configfile: pytest.ini
testpaths: tests
collecting ... collected 23 items

tests/test_calculate.py::test_multiplication_is_exact PASSED             [  4%]
tests/test_calculate.py::test_q09_expression PASSED                      [  8%]
tests/test_calculate.py::test_precedence_parentheses_and_unary_minus PASSED [ 13%]
tests/test_calculate.py::test_refuses_dangerous_inputs_quickly[__import__('os').system('echo hi')-not allowed] PASSED [ 17%]
tests/test_calculate.py::test_refuses_dangerous_inputs_quickly[(1).__class__-not allowed] PASSED [ 21%]
tests/test_calculate.py::test_refuses_dangerous_inputs_quickly[9**9**9-exponent too large] PASSED [ 26%]
tests/test_calculate.py::test_division_by_zero PASSED                    [ 30%]
tests/test_calculate.py::test_too_large_results_are_refused PASSED       [ 34%]
tests/test_calculate.py::test_other_bad_inputs PASSED                    [ 39%]
tests/test_calculate.py::test_loop_validation_rejects_bad_arguments PASSED [ 43%]
tests/test_lookup.py::test_finds_correct_2025_population PASSED          [ 47%]
tests/test_lookup.py::test_finds_2020_population_from_all_three_phrasings PASSED [ 52%]
tests/test_lookup.py::test_misspelled_name_is_not_guessed PASSED         [ 56%]
tests/test_lookup.py::test_similar_names_are_kept_apart PASSED           [ 60%]
tests/test_lookup.py::test_archived_profile_is_never_used PASSED         [ 65%]
tests/test_lookup.py::test_correction_notice_wins PASSED                 [ 69%]
tests/test_lookup.py::test_cubic_metres_converted_to_megalitres PASSED   [ 73%]
tests/test_lookup.py::test_region_tariff_is_2025_not_2024 PASSED         [ 78%]
tests/test_lookup.py::test_bad_inputs_return_errors_not_exceptions PASSED [ 82%]
tests/test_lookup.py::test_evidence_is_short_not_whole_document PASSED   [ 86%]
tests/test_scoring.py::test_parse_takes_the_last_answer_line PASSED      [ 91%]
tests/test_scoring.py::test_scoring_rule PASSED                          [ 95%]
tests/test_scoring.py::test_majority_vote PASSED                         [100%]

============================= 23 passed in 1.72s ==============================
```

10 tests for `lookup`, 10 for `calculate` + the loop's input validation (the three dangerous inputs are one parametrised test each, and each must be refused in under 0.5 s), and 3 for the answer parser, the vote and the scoring rule. None of them needs an API key.

### B3 — The loop

The loop is `run_s3` in `strategies.py`. It is a manual loop on `client.messages.create(..., tools=[...])`:

- It appends the assistant message **unchanged** (`response.content`, with its `tool_use` blocks) to the conversation.
- For **every** `tool_use` block it validates the input (`validate_args`: known tool, object, required keys, no extra keys, string types, enum), runs the tool, and adds a `tool_result` with the same `tool_use_id`. Invalid input or a tool error comes back with `is_error: true`, never as an exception. All results of one turn go back in **one** user message.
- It stops when the model answers without asking for a tool, or after `MAX_ROUNDS` model calls. If the limit is hit, the question is marked **unanswered**.

- **Round limit, and why:** **8 model calls per question.** The hardest questions need about 6 facts (3 districts × 2 fields) + 3 per-district calculations + 1–2 comparisons. With parallel tool calls that is 3–4 rounds, as in my A3 plan (4 rounds for Q-09). If the model asks for facts one at a time it needs up to about 7. 8 leaves room for that plus one retry after a tool error. More rounds would only let a confused model keep going, and each extra round costs more than the last, because the whole growing conversation is sent again.
- **Where the logs are:** `outputs/<run>/s3/Q-xx.json`. Each file holds every API call (round, input/output tokens, seconds, stop reason) and every tool call (round, `tool_use` id, tool, input, result, `is_error`, seconds), plus the full transcript. `outputs/<run>/results.json` has the per-question table and the summary.
- **Real Q-09 conversation compared with my A3 version** (`outputs/run1/s3/Q-09.json`): the *structure* is identical to A3. There are 4 model calls and 7 tool calls in the same groups: 4 `lookup`s in parallel in round 1, the two densities in round 2, the difference in round 3, the answer in round 4. All inputs and results are exactly the ones I wrote by hand, including the corrected area 921.4 from NR-16. What is different:
  1. The model writes a short sentence before each group of calls, which I did not plan: *"I'll look up the 2025 population and area for both districts."*, *"Now I'll calculate the densities."*, *"Millbrook is denser than Brightwater, so I'll take the difference in the other direction."* That is 310 output tokens in round 1 instead of the ~100 the bare calls need.
  2. The ids are real API ids (`toolu_01BHJzmHMicihiPxESKKWVby`, …), not `toolu_01`…`toolu_07`.
  3. The difference is written with parentheses: `(37203 / 758.6) - (44675 / 921.4)`.
  4. The final text cites the source: *"using the corrected Brightwater area of 921.4 km²"*. It can do that because `lookup` returned `source` and `note`.
  5. The cost I had not written down: the input grows every round, 1,302 → 2,064 → 2,292 → 2,434 tokens. Each round resends the whole conversation, so Q-09 costs 8,092 input tokens in total, not 4 × 1,302.

### B4 — Three strategies

**What I kept the same:**

| Setting | Value |
|---|---|
| Model | `claude-haiku-5-5` for every call |
| Thinking | `{"type": "disabled"}` for every call. All reasoning has to be written out as text, so S2's step-by-step really is the only reasoning |
| Effort | `medium` (the model's default; thinking can only be disabled at effort ≤ high) |
| `max_tokens` | 4096 |
| Temperature | Not settable: Claude Haiku 5.5 returns a 400 for any temperature other than the default 1. Every call (all strategies) therefore samples at temperature 1, which is also what makes S2's 5 samples differ |
| k (S2) | 5 samples, sent in parallel; majority vote on (name, number rounded to 3 dp), ties → the more common name, then the earlier sample |
| Round limit (S3) | 8 model calls |
| System prompt | the same first sentence for all three. S1/S2 add all 17 documents (archived ones and the correction included), S3 adds the tool instructions and no documents |
| Answer format | the same `ANSWER: <name or yes/no> \| <number>` line, number rounded to 3 decimals (S1 via JSON, see above) |
| Questions | the same 20, same order, run 1 and run 2 with identical code |
| Prompt caching | off for all strategies. Token counts are the real billable tokens, and the documents (~3.2k tokens) are below the size where caching would work anyway |
| Prices used for cost | Claude Haiku 5.5: $0.10 per million input tokens, $0.50 per million output tokens (prompts ≤ 100K tokens) |

**My rule for a correct answer** (written before the first full run):

1. Take the **last** `ANSWER:` line of the reply. No such line (or S3 hit the round limit) → **unanswered**, which counts as wrong.
2. The **name** must equal `answer` in `questions.json`, ignoring upper/lower case and surrounding spaces, `*` and quotes. No partial matches: "Ossford" ≠ "Ossbridge".
3. The **number** is rounded to the question's `decimals`. It must be within **1 unit of the last digit** of `value` (rounded the same way). Example Q-09: 0.556 → 0.6 ✓, 0.5 ✓, 0.077 → 0.1 ✗ (the uncorrected-area answer).
4. Both 2 and 3 must hold.

Why this rule: the name is exact, because the traps (Ossbridge/Ossford, wrong winner) are exactly name mistakes. The ±1 in the last digit allows for honest rounding differences: I ask for 3 decimals and round again, and the reference was computed by someone else's rounding. It still rejects every trap answer, which all differ by much more. The model is never told `decimals` or `value`; it always gives 3 decimals. The rule is implemented in `run.py::is_correct` and tested in `tests/test_scoring.py`.

Produced by `python run.py --name run1` and `python run.py --name run2` (same code, one after the other), tables by `python analyze.py run1 run2`. Raw data: `outputs/run1/results.json`, `outputs/run2/results.json`. S2's seconds are wall-clock with the 5 samples sent in parallel. Tokens are summed from `usage` of **every** call (all 5 S2 samples, every S3 round).

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 1 | 0 | 67,552 | 403 | 1.03 | 21.7 | 0.0070 |
| 1 | S2 think and vote (k = 5) | 19 | 0 | 325,260 | 48,942 | 2.98 | 60.7 | 0.0570 |
| 1 | S3 tools | 20 | 0 | 144,432 | 12,508 | 4.83 | 94.6 | 0.0207 |
| 2 | S1 direct | 1 | 0 | 67,552 | 406 | 1.06 | 22.4 | 0.0070 |
| 2 | S2 think and vote (k = 5) | 19 | 0 | 325,260 | 47,808 | 2.97 | 61.1 | 0.0564 |
| 2 | S3 tools | 20 | 0 | 142,430 | 12,693 | 4.90 | 97.5 | 0.0206 |

**What everything cost:** $0.169 for the two full runs. Including the smoke tests and C1, $0.189 is logged in `outputs/*/results.json`. A few unlogged trial calls while fixing S1 (about 8 calls) add well under $0.01.

**Per question (run 1, with run 2 next to it):** ✓ correct, ✗ wrong, ∅ unanswered

| Question | S1 r1 | S1 r2 | S2 r1 | S2 r2 | S3 r1 | S3 r2 | S3 rounds r1 | S3 tool calls r1 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|
| Q-01 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-02 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 6 |
| Q-03 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 6 |
| Q-04 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-05 | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | 4 | 7 |
| Q-06 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 5 |
| Q-07 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-08 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 4 |
| Q-09 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-10 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 3 | 3 |
| Q-11 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 10 |
| Q-12 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-13 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 9 |
| Q-14 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-15 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 7 |
| Q-16 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 4 |
| Q-17 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 8 |
| Q-18 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 3 | 3 |
| Q-19 | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 4 | 7 |
| Q-20 | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | 4 | 10 |

Two more facts from the logs that the table hides:
- **S1 picked the right winner in 10/20 questions (both runs)**, but the number was right only once. Q-10 is a plain subtraction of two founding years, 1845 − 1837.
- **S2, single samples:** 94/100 samples correct in run 1 and 91/100 in run 2. All 15 wrong samples come from just four questions: Q-05, Q-08, Q-13, Q-20. S3 had **0 tool errors** in 264 tool calls (131 in run 1, 133 in run 2).

**Why twenty questions, and why this rule.** Twenty is what the brief gives. It is enough to separate a strategy that fails almost everything (S1, 2/40) from strategies that almost never fail. It is *not* enough to rank S2 against S3; see C4. The name must match exactly, because the deliberate traps (look-alike names, the wrong winner) produce name errors. The ±1 tolerance in the last digit only absorbs rounding differences between my 3-decimal answers and the reference. Every trap answer (uncorrected area, archived population, m³ read as ML) misses by far more than that, so the tolerance never turns a trap into a pass.

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

`python run.py --name c1_vague --strategies s3 --vague --questions Q-02 Q-03 Q-08 Q-09 Q-18`. Only the top-level `lookup` description changed, to `"Looks things up."`. The schema (with its `enum` of fields and the `district` property description), the calculator, the prompts and the model stayed the same. I picked the five questions with a trap or a special case: Q-02 (archived Tarnvale), Q-03 (Lindenmoor in m³), Q-08 (regional tariff), Q-09 (correction), Q-18 (projection). The baseline is S3 in run 1. Table by `python analyze.py --c1 run1 c1_vague`.

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-02 | 6 (3 rounds) | 7 (4 rounds) | Harrowfield 1.687 ✓ | Harrowfield 1.687 ✓ |
| Q-03 | 6 (3 rounds) | 7 (4 rounds) | Lindenmoor 5.34 ✓ | Lindenmoor 5.34 ✓ |
| Q-08 | 4 (3 rounds) | 8 (5 rounds) | Brightwater 72.456 ✓ | Brightwater 72.456 ✓ |
| Q-09 | 7 (4 rounds) | 7 (4 rounds) | Millbrook 0.556 ✓ | Millbrook 0.556 ✓ |
| Q-18 | 3 (3 rounds) | 3 (3 rounds) | yes 40013.4 ✓ | yes 40013.4 ✓ |

**What changed.** The answers did not change (5/5 both times). The number of calls, the rounds and the cost did. Together the five questions used 37,017 input tokens with the vague description and 30,298 with mine (+22 %), although each vague request is ~190 tokens *shorter* (the tools add 864 instead of 1,055 tokens, `outputs/tool_tokens.json`).

- **Q-08 is where the description mattered.** Only my description says *"For the household water tariff use district="region""*. With the vague one, the model first asked for `lookup(Brightwater, water_tariff_tenge_per_m3)` and `lookup(Millbrook, water_tariff_tenge_per_m3)`. Both came back as errors: `field 'water_tariff_tenge_per_m3' is region-wide; use district="region"`. In round 2 it retried with `region` and got 142.35. That is 2 wasted calls, 2 extra rounds and 9,854 instead of 5,484 input tokens (+80 %). It recovered only because the **error message** told it what to do. Without that, the vague description would have been a wrong or unanswered question.
- **Q-02 and Q-03:** the model took one extra round. With my description it finished after the two per-district calculations, doing the difference in its head at the end (1.687, 5.340). With the vague one it made a third `calculate` call for the difference (`7.8974751522 - 6.2100157705`). Same answer, one more round.
- **Q-09 and Q-18: identical** calls and inputs.

**Why so little changed:** most of what the model needs is in the *schema*, not in the description. The `enum` lists the ten field names (`area_km2`, `water_use_2025_megalitres`, …), and the `district` property lists the 12 names. So even "Looks things up." leaves an almost self-explaining tool. The things only the description said, like the region convention and "trust the value, corrections are applied", were exactly where behaviour changed. My prediction would be a much bigger effect for a free-text `lookup(query)` tool, where the description is the only guide. I did not test that.

### C2 — Three mistakes explained

**S1 (direct) — Q-09, wrong.** `outputs/run1/s1/Q-09.json`: `{"name": "Millbrook", "number": 9.036}` (correct: Millbrook, 0.6). 21 output tokens, no working. The winner is right, the number is meaningless: it is neither density nor difference. The reason is computational, not a missing fact. A model produces one token at a time, and every token gets the same fixed amount of computation. To get 0.556 it must divide 44,675 by 921.4, divide 37,203 by 758.6 and subtract, which needs intermediate results written down somewhere. In S1 the JSON leaves nowhere to put them, so the model can only *guess* a number that "looks right". That is why S1 got the winner right in 10/20 (a comparison can often be judged roughly) but the number in only 1/20. The one success, Q-10 (1845 − 1837 = 8), is the only question whose arithmetic fits into one step. This also explains the B4 smoke test: given the chance, Haiku *wrote* the working (381 tokens) and got Q-09 right. Visible text is the model's only working memory when thinking is off.

**S2 (think and vote) — Q-05 in run 2, wrong.** `outputs/run2/s2/Q-05.json`. Sample 1 does the right thing with the right facts, then divides badly: Stonecairn 2,884,600,000 / 14,926 *"≈ 193,256.333"* (correct: 193,260.08), Coldharbour *"≈ 207,501.535"* (correct: 207,495.40). Then it "verifies": *"14,926 × 193,256 = 2,884,596,... ; … Confirmed ≈ 193,256.333."* The "verification" is itself made up; it trails off into "..." exactly where the digits would show the error. The difference becomes 14,245.202 instead of 14,235.3. The 5 samples were 14245.202, 14.235, 14208.995, **14235.314**, **14235.315**. Two samples were right, but they differ in the 3rd decimal, so under my exact-match vote all five keys were different. The tie went to the earliest sample, which was wrong.

*Why voting fixes some mistakes but not others.* Voting reduces **variance**: if each sample is right with probability *p* > 0.5 and the errors scatter, the majority of 5 is right with probability Σ_{k≥3} C(5,k)pᵏ(1−p)⁵⁻ᵏ. At my measured per-sample accuracy (185/200 = 92.5 %) that is 99.6 %, and that is what happened on Q-13. There one sample wrote `-4.159` (the loss as a negative number) and four wrote `4.159`, so the vote fixed it. Voting stops working in three cases, and my runs show each:
1. **when *p* is near or below 0.5 on that question**: Q-05 run 2 had 2/5 right. At p = 0.4 the majority of 5 is right only 32 % of the time;
2. **when the errors are correlated**: Q-20 run 1 had *two* samples making the *same* scale error, 175,497 tenge written as *"≈ 175.49717"*, both ending in `2.993`. A repeated wrong answer outvotes scattered right ones;
3. **when right answers do not compare equal**: continuous numbers with rounding noise (14235.314 vs 14235.315) split the vote. Re-voting the same saved samples with a 0.05 % tolerance (`python analyze.py --revote run1 run2`, `outputs/s2_revote.md`, offline, no new calls) gives 20/20 in both runs. But Q-20 run 1 is then a 2–2 tie between `2993.3x` and `2.993`, which wins only by sample order, so that "fix" is luck. The rule in the table stays the one I fixed before the run.

Voting cannot remove a **bias**. Every sample does long division "in its head", so every sample has the same kind of arithmetic error, and averaging five biased estimates does not unbias them.

**S3 (tools) — no wrong answer, so its most expensive question: Q-20** (run 1, 9,745 input + 946 output tokens, $0.00145, 6.0 s). The log shows 6 `lookup`s in round 1 (budget and population for 3 districts), 3 per-resident divisions in round 2 (`9284.5 * 1000000 / 52904` → 175497.1268713141, …), the difference in round 3 (`178490.4697072839 - 175497.1268713141` → 2993.3428359698), and the answer in round 4. This is the same division that broke S2 in Q-20 run 1. Here the model only *writes* the expression; the calculator computes it. The arithmetic error is therefore **bounded by floating point**, about 1e-10, whatever the model's skill at long division. The model can still choose the wrong expression, but it can no longer get the right expression wrong. That is why S3 had zero numeric errors.

*Why it needed 4 rounds:* the rounds follow the dependency depth of the problem, not the number of facts. Facts → per-district metrics → difference → answer. Calls at the same level go in parallel; the next level has to wait for the results. *Why each round costs more:* the API is stateless, so every round resends the whole conversation, including all earlier tool calls and results. Q-20's input grew 1,325 → 2,479 → 2,872 → 3,069. The big jump after round 1 is the six `lookup` results with their evidence sentences plus the model's own 485 output tokens. The total input therefore grows roughly with the *square* of the number of rounds, which is why the round limit is also a cost limit.

### C3 — Which strategy I would use, and what would change it

**I would use S3 (tools).** It was correct on 40/40 question-runs, cost $0.0207 per 20 questions (2.75× cheaper than S2), and its accuracy does not rely on the model's arithmetic. The traps are handled by tested code, not by the model noticing them.

- **Against S1:** S1 is the cheapest ($0.0070) and the fastest (1.0 s median), but it got 2/40. A direct answer has no room for the multi-step arithmetic these questions need (C2). Cheap and wrong is not cheap.
- **Against S2:** S2 is almost as accurate (38/40), but it costs 2.75× more than S3 and 8.2× more than S1. The documents are sent 5 times, and five reasoning chains cost 121× S1's output tokens. Its remaining errors are exactly the kind voting cannot fix: correlated, bias-type arithmetic errors (Q-20) and splits on continuous answers (Q-05). S2 is faster than S3 (3.0 s vs 4.8 s median, because the samples run in parallel while S3's rounds are sequential). For 20 questions that difference does not matter.

**What would change my choice:**

| Situation | What I would pick, and why |
|---|---|
| **1,000× more documents** (~3M tokens) | **S3, even more clearly.** S1/S2 can no longer even fit the documents into Haiku's 1M context, and S2 would cost about 1,000× more per question. S3's cost does not depend on corpus size; `lookup` would need a real index (see final question 6). |
| **Strict time limit, e.g. < 3 s per question** | **S2 with k = 1–3 in parallel** (or plain single-sample step-by-step). S3's 4 sequential rounds took ~4.8 s. One step-by-step sample was right 92.5 % of the time with a median of 2.4 s. That is a deliberate accuracy-for-latency trade. |
| **Questions with no arithmetic** (look up one fact, like Q-10's founding years, or "how many schools has Redfen?") | **S1.** The one thing S1 did get right was the one-step question. Without computation the direct answer is enough, at ⅓ of S3's cost and ⅕ of its time. |
| **Questions my `lookup` cannot express** (free text: "which districts lie on the Oss?", "what does NR-00 say about archives?") | **S2** (or S3 with a text-search `lookup`). My structured tool only knows ten fields, so it would fail where the documents in the prompt still work. |
| **Very small budget** | still **S3**: it is already cheaper than S2 at higher accuracy, and S1 is not an option at 5 %. |

### C4 — How sure I can be

- **How different were the two runs?** The scores were identical: S1 1/1, S2 19/19, S3 20/20. Tokens differed by at most 2.4 % (S2 output 48,942 vs 47,808; S3 input 144,432 vs 142,430), time by under 4 %. But the identical S2 score hides real variance. S2 failed **different** questions (Q-20 in run 1, Q-05 in run 2), and its single-sample accuracy moved from 94 % to 91 %. So 2 of 20 S2 outcomes flipped between runs. S1 was deterministic in practice (the same wrong answers), and S3 was stable.
- **Is the gap between the two best strategies bigger than that?** No. S3 vs S2 is 1 question per run, the same size as the run-to-run flips inside S2. Pooled over both runs, S3 = 40/40 (95 % Wilson interval **91.2 %–100 %**) and S2 = 38/40 (**83.5 %–98.6 %**). The intervals overlap almost completely. A paired sign test on the 2 discordant questions gives p = 0.5. So I **cannot claim from accuracy that S3 beats S2**; my choice of S3 rests on cost and on the principle (bounded arithmetic error), not on the 1-question gap. The S1 result *is* solid: 2/40 (1.4 %–16.5 %) does not overlap either of the others.
- **How many questions would I need?** If S2's true error rate is about the 5 % I measured and S3's is about 0, a sign test needs at least **6 discordant questions all favouring S3** to reach p < 0.05 (0.5⁶ × 2 = 0.031). At 5 % that takes about **120 questions**, more with real noise; 150–200 to be comfortable. It would also have to be a *new* set of questions: my 20 share one corpus, and all of S2's errors come from one family (large-number divisions: Q-05, Q-08, Q-20), so they are not 20 independent tests. Things this comparison cannot settle at all: another model (a stronger one would probably close the S2 gap; a weaker one could also make S3 fail by choosing wrong expressions), other temperatures (not settable here), and other values of k.

### Final questions

1. **When the model sends a `tool_calls` message, what has actually run so far?** Nothing except the model itself. The `tool_use` blocks are just text the model generated in the tool format: a request. No lookup or calculation has happened. In my Q-09 log, round 1 ends with `stop_reason: "tool_use"` and four `tool_use` blocks. The four lookups ran only afterwards, in *my* loop, taking 0.06–0.11 ms each, and the model saw their values only in round 2.
2. **Why does `arguments` arrive as a string, and what goes wrong if you pass it straight into your function?** The model can only generate text, so the arguments are JSON *text*; in OpenAI's API they reach the client as a raw string. Passing that string straight into `lookup(**args)` fails (a string is not a mapping), and `calculate(args)` would try to evaluate `{"expression": "…"}` itself. Worse, the JSON may be invalid, have missing or extra keys, or wrong types. Anthropic's SDK, which I used, already parses `input` into a `dict`, so the "string" step is hidden. My loop still validates every input before running anything (`validate_args`: object, required keys, no extra keys, string types, enum), and it also accepts a JSON string (tested in `test_loop_validation_rejects_bad_arguments`). In 264 real calls nothing invalid arrived, but nothing in the API *guarantees* that, because I did not use `strict: true`.
3. **How many tokens do the two tool definitions add to every S3 request? Measure it.** **1,055 tokens.** `python measure_tools.py` counts the first Q-09 request with `count_tokens`: 248 tokens without tools, 1,303 with tools (`outputs/tool_tokens.json`). This includes the instructions the API adds on its own when tools are present, not only my JSON. With the vague `lookup` description it is 864. Because the whole request is resent each round, a 4-round question pays this about 4 times, ~4,200 tokens. Over run 1 (71 rounds) the tool definitions make up 1,055 × 71 / 144,432 ≈ **52 % of all S3 input tokens**. Still, the full first S3 request (1,303) is far smaller than S1/S2's request with the documents (3,200).
4. **How much more did S2 cost than S1?** Run 1: $0.0570 vs $0.0070, **8.2× (+$0.050)**. Run 2: 8.1×. Input tokens are 4.8× (325,260 vs 67,552): five samples of the same 3.2k-token prompt, slightly less than 5× because S1's prompt also carries the JSON schema. Output tokens are **121×** (48,942 vs 403): S1 answers in ~20 tokens, each S2 sample writes ~490 tokens of reasoning. Output is 5× the price of input, so S2's bill is 57 % input ($0.0325) and 43 % output ($0.0245). The cost of "think and vote" is k times the prompt *plus* k reasoning chains.
5. **Which question needed the most rounds in S3, and why?** No question needed more than 4 rounds (11 of 20 used 4, the rest 3), so none came near the limit of 8. The most *tool calls* were in **Q-11 and Q-20 (10 each)**: 3 districts × 2 facts = 6 lookups, 3 per-district calculations, 1 difference. They still needed only 4 rounds, because the number of rounds equals the dependency depth (facts → metrics → difference → answer), not the number of facts: calls at the same level run in one round. 3-round questions merged two levels: Q-08 put the whole difference into one expression, and Q-10 and Q-18 need only one calculation. The most rounds anywhere was 5, in C1 Q-08 with the vague description: one extra round after the two error results.
6. **What would I change in `lookup` if there were 100,000 documents?** My `lookup` relies on a fixed rule (one profile per district, one sentence per field, matched by regex) and on a scan over all documents when building the index. For 100,000 documents I would: build the index **offline** into a database (district → field → value, source, date, superseded-by), so a call is one keyed query and not a pass over the text. Extract values with a tested parser per document type, with logged failures, instead of a handful of regexes. Keep the archive/correction rules as data: every record has `valid_from` and `superseded_by`, so "never archived, corrections win" stays a query condition. Add a second, **search-style** tool (`search(query, k=5)` over an embedding or BM25 index, returning short passages with ids) for questions the fields do not cover. Return at most a few results with the source, never whole documents. Paginate, and let the name matcher report ambiguity, because with more districts look-alike names become common.
7. **What stops my `calculate` from running dangerous code? Could the model still make it misbehave?** It never calls `eval`/`exec`. It parses the string with `ast.parse(..., mode="eval")` and walks the **whole tree before evaluating anything**. Only `Expression`, `BinOp`, `UnaryOp`, numeric `Constant` and the 6 operators I listed are allowed, so names, calls, attributes, subscripts, strings, booleans and lambdas are rejected (`__import__('os')…` → `not allowed in expression: Call`, `(1).__class__` → `Attribute`). The evaluator then caps exponents at 100 *before* computing (`9**9**9` → refused in < 0.5 s), results at 1e15, input at 200 characters / 100 nodes, and turns division by zero into an error. What the model *can* still do: make it compute the wrong thing correctly (a wrong number copied from a lookup, or swapped operands), get a float-rounding answer (`0.1 + 0.2`), or call it a thousand times. That last one is limited by my round limit, not by the calculator. It cannot make it read files, run commands or hang.
8. **For which kind of question did tools help most, and for which not at all?** They helped most on **multi-step arithmetic with large numbers**: budget per resident (Q-05, Q-20), water cost in million tenge (Q-08), percentage changes (Q-13). These were exactly where S2's samples failed (all 15 wrong S2 samples are in Q-05, Q-08, Q-13, Q-20) and S1 failed completely, while S3 got all of them right in both runs. Tools also guarded the traps by construction (Q-02 archived Tarnvale, Q-03 m³, Q-09 correction). Here, though, S2 coped well too, because the documents were in its prompt and it read the correction notice. They did **not** help on **one-step questions**. On Q-10 (1845 − 1837) every strategy was right, including S1 with 21 output tokens, $0.00035 and 1.5 s. S3 spent 3 rounds and 3 tool calls on the same answer: 1.5× the tokens (5,058 vs 3,382), 1.8× the cost ($0.00063) and 2.2× the time (3.3 s).
