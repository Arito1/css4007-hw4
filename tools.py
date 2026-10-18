"""The two tools the model can ask for: `lookup` and `calculate`.

Both functions never raise. On any problem they return {"error": "..."} so the
model can read what went wrong and try again.
"""

import ast
import difflib
import json
import math
import operator
import re
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

# --------------------------------------------------------------------------
# Tool definitions, exactly as sent to the model (Anthropic format).
# --------------------------------------------------------------------------

FIELDS = [
    "population_2025",
    "population_2020",
    "area_km2",
    "budget_2025_million_tenge",
    "water_use_2025_megalitres",
    "schools",
    "pupils_2025_26",
    "paved_road_km",
    "founded_year",
    "water_tariff_tenge_per_m3",
]

LOOKUP_DESCRIPTION = (
    "Look up ONE official 2025 fact about ONE district of the Nine Rivers Region "
    "(or a region-wide fact) and get back a single number with its unit and the id "
    "of the document it came from. Archived 2019 profiles are never used, and "
    "published corrections are applied automatically, so trust the value returned. "
    "Water use is always returned in megalitres. Call it once per (district, field) "
    "pair; you may call it several times in one turn. If the district name is not "
    "recognised, the result is an error listing the closest valid names: retry with "
    "one of them. For the household water tariff use district=\"region\" and "
    "field=\"water_tariff_tenge_per_m3\"."
)

VAGUE_LOOKUP_DESCRIPTION = "Looks things up."

LOOKUP_TOOL = {
    "name": "lookup",
    "description": LOOKUP_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "district": {
                "type": "string",
                "description": (
                    "District name exactly as in the profiles (Ossbridge, Ossford, "
                    "Tarnvale, Kelmarsh, Brightwater, Stonecairn, Harrowfield, "
                    "Lindenmoor, Redfen, Ashgrove, Millbrook, Coldharbour), or "
                    "\"region\" for region-wide facts."
                ),
            },
            "field": {
                "type": "string",
                "enum": FIELDS,
                "description": "Which fact to return.",
            },
        },
        "required": ["district", "field"],
        "additionalProperties": False,
    },
}

CALCULATE_TOOL = {
    "name": "calculate",
    "description": (
        "Evaluate ONE arithmetic expression exactly and return the numeric result at "
        "full precision. Use it for every calculation (divisions, differences, "
        "percentages, unit conversions) instead of doing arithmetic in your head. "
        "Allowed: numbers, + - * / ** %, unary minus and parentheses. Not allowed: "
        "variables, function calls, commas as thousands separators (write 44675, not "
        "44,675). Example: \"(37203 / 758.6) - (44675 / 921.4)\"."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The arithmetic expression, e.g. \"44675 / 921.4\". At most 200 characters.",
            }
        },
        "required": ["expression"],
        "additionalProperties": False,
    },
}

TOOL_DEFINITIONS = [LOOKUP_TOOL, CALCULATE_TOOL]


def tool_definitions(vague_lookup: bool = False) -> list[dict]:
    """The tool list for S3; `vague_lookup` swaps only the lookup description (C1)."""
    if not vague_lookup:
        return TOOL_DEFINITIONS
    return [{**LOOKUP_TOOL, "description": VAGUE_LOOKUP_DESCRIPTION}, CALCULATE_TOOL]


# --------------------------------------------------------------------------
# Corpus index (built once at import)
# --------------------------------------------------------------------------

NUM = r"(\d[\d,]*(?:\.\d+)?)"

# field -> list of (regex, unit). The first group of the regex is the number.
FIELD_PATTERNS = {
    "population_2025": [
        (rf"2025 census (?:recorded|counted) {NUM} residents", "residents"),
        (rf"Census population: [\d,]+ in 2020 and {NUM} in 2025", "residents"),
    ],
    "population_2020": [
        (rf"2020 census had recorded {NUM}", "residents"),
        (rf"up from {NUM} at the 2020 census", "residents"),
        (rf"Census population: {NUM} in 2020", "residents"),
    ],
    "area_km2": [(rf"{NUM} square kilometres", "km2")],
    "budget_2025_million_tenge": [(rf"{NUM} million tenge", "million tenge")],
    "water_use_2025_megalitres": [(rf"{NUM} (megalitres|cubic metres)", None)],
    "schools": [(rf"{NUM} schools", "schools")],
    "pupils_2025_26": [(rf"{NUM} pupils", "pupils")],
    "paved_road_km": [(rf"{NUM} km\b", "km")],
    "founded_year": [(r"[Ff]ounded in (\d{4})", "year")],
}

REGION_PATTERNS = {
    "water_tariff_tenge_per_m3": [
        (rf"tariff is {NUM} tenge per cubic metre", "tenge per m3"),
    ],
}

# Words used in correction notices -> field they correct.
CORRECTION_WORDS = {"area": "area_km2"}

MAX_EVIDENCE = 200
MAX_NAME = 50


def _to_number(text: str) -> float | int:
    text = text.replace(",", "")
    return float(text) if "." in text else int(text)


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=\.)\s+(?=[A-Z])", text)


def _load_index(path: Path = CORPUS_PATH) -> dict:
    docs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    profiles, archived, corrections, region = {}, {}, {}, []
    megalitre_m3 = None
    for doc in docs:
        title = doc["title"]
        if "ARCHIVED" in title:
            archived[title.split()[0]] = doc["id"]
            continue
        m = re.match(r"^(\w+) district profile \(2025\)$", title)
        if m:
            profiles[m.group(1)] = doc
            continue
        m = re.match(r"^Correction notice - (\w+)$", title)
        if m:
            for sentence in _sentences(doc["text"]):
                c = re.search(rf"The correct (\w+) is {NUM}", sentence)
                if c and c.group(1) in CORRECTION_WORDS:
                    corrections[(m.group(1), CORRECTION_WORDS[c.group(1)])] = {
                        "value": _to_number(c.group(2)),
                        "source": doc["id"],
                        "evidence": sentence[:MAX_EVIDENCE],
                    }
            continue
        if "about these profiles" not in title:
            region.append(doc)
        u = re.search(r"One megalitre is ([\d,]+) cubic metres", doc["text"])
        if u:
            megalitre_m3 = _to_number(u.group(1))
    return {
        "profiles": profiles,
        "archived": archived,
        "corrections": corrections,
        "region": region,
        "megalitre_m3": megalitre_m3,
    }


INDEX = _load_index()
DISTRICTS = sorted(INDEX["profiles"])


def resolve_district(name: str) -> tuple[str | None, str | None]:
    """Return (canonical_name, None) or (None, error message). Never guesses."""
    if not isinstance(name, str) or not name.strip():
        return None, "district must be a non-empty string"
    if len(name) > MAX_NAME:
        return None, f"district name too long (max {MAX_NAME} characters)"
    key = re.sub(r"\s+district$", "", name.strip(), flags=re.I).lower()
    if key == "region":
        return "region", None
    by_lower = {d.lower(): d for d in DISTRICTS}
    if key in by_lower:
        return by_lower[key], None

    prefix = [d for d in DISTRICTS if d.lower().startswith(key)]
    if len(prefix) > 1:
        return None, f"'{name}' matches more than one district: {', '.join(prefix)}. Use the full name."
    close = difflib.get_close_matches(key, list(by_lower), n=3, cutoff=0.6)
    # Districts that share the first three letters are always offered together,
    # so a near-miss on Ossbridge also mentions Ossford (and vice versa).
    suggestions = [by_lower[c] for c in close] + prefix
    suggestions += [d for d in DISTRICTS if len(key) >= 3 and d.lower()[:3] == key[:3]]
    suggestions = list(dict.fromkeys(suggestions))
    if suggestions:
        return None, f"no district named '{name}'; did you mean {' or '.join(suggestions)}?"
    return None, f"no district named '{name}'; valid districts: {', '.join(DISTRICTS)}"


def _extract(doc: dict, patterns: list[tuple[str, str | None]]) -> dict | None:
    for sentence in _sentences(doc["text"]):
        for pattern, unit in patterns:
            m = re.search(pattern, sentence)
            if m:
                return {"raw": m.group(1), "unit": unit or m.group(2), "evidence": sentence[:MAX_EVIDENCE]}
    return None


def _lookup(district: str, field: str) -> dict:
    canonical, error = resolve_district(district)
    if error:
        return {"error": error}
    if not isinstance(field, str) or field not in FIELDS:
        return {"error": f"unknown field '{field}'; valid fields: {', '.join(FIELDS)}"}

    if canonical == "region":
        if field not in REGION_PATTERNS:
            return {"error": f"field '{field}' is not available for 'region'; use a district name"}
        for doc in INDEX["region"]:
            hit = _extract(doc, REGION_PATTERNS[field])
            if hit:
                return {"district": "region", "field": field, "value": _to_number(hit["raw"]),
                        "unit": hit["unit"], "source": doc["id"], "evidence": hit["evidence"]}
        return {"error": f"no region-wide document has field '{field}'"}

    if field in REGION_PATTERNS:
        return {"error": f"field '{field}' is region-wide; use district=\"region\""}

    doc = INDEX["profiles"][canonical]
    result = {"district": canonical, "field": field}
    correction = INDEX["corrections"].get((canonical, field))
    hit = _extract(doc, FIELD_PATTERNS[field])

    if correction:
        result.update(value=correction["value"], unit="km2" if field == "area_km2" else None,
                      source=correction["source"], evidence=correction["evidence"])
        old = f"; profile {doc['id']} says {hit['raw']}" if hit else ""
        result["note"] = f"corrected by {correction['source']}{old}"
    elif hit is None:
        return {"error": f"could not read field '{field}' from {doc['id']}"}
    else:
        try:
            value = _to_number(hit["raw"])
        except ValueError:
            return {"error": f"could not read field '{field}' from {doc['id']}"}
        unit = hit["unit"]
        if field == "water_use_2025_megalitres":
            if unit == "cubic metres":
                if not INDEX["megalitre_m3"]:
                    return {"error": f"cannot convert cubic metres to megalitres for {doc['id']}"}
                result["note"] = (f"profile {doc['id']} gives {hit['raw']} cubic metres; "
                                  f"converted at 1 ML = {INDEX['megalitre_m3']:,} m3")
                value = round(value / INDEX["megalitre_m3"], 6)
                unit = "megalitres"
            elif unit != "megalitres":
                return {"error": f"unknown water unit '{unit}' in {doc['id']}"}
        result.update(value=value, unit=unit, source=doc["id"], evidence=hit["evidence"])

    if canonical in INDEX["archived"]:
        result["archived_ignored"] = INDEX["archived"][canonical]
    return result


def lookup(district: str, field: str) -> dict:
    """One fact about one district (or the region). Never raises."""
    try:
        return _lookup(district, field)
    except Exception as exc:  # last line of defence: the model gets a message, not a crash
        return {"error": f"internal lookup error: {type(exc).__name__}"}


# --------------------------------------------------------------------------
# calculate: an ast whitelist, no eval/exec
# --------------------------------------------------------------------------

MAX_EXPRESSION = 200
MAX_NODES = 100
MAX_EXPONENT = 100
MAX_ABS = 1e15

BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                 *BINARY_OPS, *UNARY_OPS)


class CalcError(Exception):
    pass


def _check(value):
    if isinstance(value, complex) or not math.isfinite(value) or abs(value) > MAX_ABS:
        raise CalcError("result too large")
    return value


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        return UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalcError(f"exponent too large (max {MAX_EXPONENT})")
        try:
            return _check(BINARY_OPS[type(node.op)](left, right))
        except ZeroDivisionError:
            raise CalcError("division by zero") from None
        except OverflowError:
            raise CalcError("result too large") from None
    raise CalcError(f"not allowed in expression: {type(node).__name__}")


def calculate(expression: str) -> dict:
    """Evaluate one arithmetic expression without eval/exec. Never raises."""
    try:
        if not isinstance(expression, str) or not expression.strip():
            return {"error": "expression must be a non-empty string"}
        if len(expression) > MAX_EXPRESSION:
            return {"error": f"expression too long (max {MAX_EXPRESSION} characters)"}
        if re.search(r"\d,\d", expression):
            return {"error": "could not parse expression: remove thousands separators (write 44675, not 44,675)"}
        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except SyntaxError as exc:
            return {"error": f"could not parse expression: {exc.msg}"}

        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_NODES:
            return {"error": "expression too long (too many parts)"}
        # Whitelist check of the whole tree happens before anything is evaluated.
        for node in nodes:
            if not isinstance(node, ALLOWED_NODES):
                return {"error": f"not allowed in expression: {type(node).__name__}"}
            if isinstance(node, ast.Constant) and (
                isinstance(node.value, bool) or not isinstance(node.value, (int, float))
            ):
                return {"error": f"not allowed in expression: constant {node.value!r}"}

        result = float(_check(_eval(tree)))
        return {"expression": expression, "result": round(result, 10)}
    except CalcError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # e.g. RecursionError on absurd nesting
        return {"error": f"could not evaluate expression: {type(exc).__name__}"}


# --------------------------------------------------------------------------
# Input validation + dispatch, used by the loop
# --------------------------------------------------------------------------

TOOL_FUNCTIONS = {"lookup": lookup, "calculate": calculate}
SCHEMAS = {t["name"]: t["input_schema"] for t in TOOL_DEFINITIONS}


def validate_args(name: str, args) -> str | None:
    """Check tool input against its schema before running. Returns an error or None."""
    if name not in SCHEMAS:
        return f"unknown tool '{name}'; available tools: {', '.join(SCHEMAS)}"
    if isinstance(args, str):  # tolerate a JSON string, as OpenAI-style APIs send it
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return "invalid input: arguments are not valid JSON"
    if not isinstance(args, dict):
        return "invalid input: arguments must be a JSON object"
    schema = SCHEMAS[name]
    for key in schema["required"]:
        if key not in args:
            return f"invalid input: '{key}' is required"
    for key, value in args.items():
        if key not in schema["properties"]:
            return f"invalid input: unexpected argument '{key}'"
        prop = schema["properties"][key]
        if prop["type"] == "string" and not isinstance(value, str):
            return f"invalid input: '{key}' must be a string"
        if "enum" in prop and value not in prop["enum"]:
            return f"invalid input: '{key}' must be one of {', '.join(prop['enum'])}"
    return None


def run_tool(name: str, args) -> tuple[dict, bool]:
    """Validate, then run. Returns (result, is_error)."""
    error = validate_args(name, args)
    if error:
        return {"error": error}, True
    if isinstance(args, str):
        args = json.loads(args)
    result = TOOL_FUNCTIONS[name](**args)
    return result, "error" in result
