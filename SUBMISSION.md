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
