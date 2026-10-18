"""The three strategies, all on the same model with the same answer format.

S1 direct          - all documents in the prompt, answer only, one call
S2 think and vote  - same prompt, reason step by step, k samples, majority vote
S3 tools           - no documents, only `lookup` + `calculate`, tool-calling loop
"""

import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from tools import run_tool, tool_definitions

load_dotenv()

# ---- settings held fixed across all strategies ----------------------------
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4096
THINKING = {"type": "disabled"}   # no hidden reasoning: S2's reasoning is only what it writes
EFFORT = "medium"                  # thinking off requires effort <= high; medium is the model default
K = 5                              # S2 samples
MAX_ROUNDS = 8                     # S3 model calls per question
# Claude Haiku 5.5 accepts only temperature=1 (the default) - any other value is a 400.
# So every call samples at temperature 1; S2's samples vary because of that.

PRICE_IN = 0.10 / 1_000_000        # $ per input token  (Claude Haiku 5.5, prompts <= 100K)
PRICE_OUT = 0.50 / 1_000_000       # $ per output token

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

BASE_SYSTEM = (
    "You answer questions about the Nine Rivers Region, a fictional region. "
    "Each question asks for a name (or yes/no) and one number."
)

ANSWER_FORMAT = (
    "End your reply with exactly one final line in this format:\n"
    "ANSWER: <district name or yes/no> | <number>\n"
    "Write the number as a plain number (no units, no thousands separators), "
    "rounded to 3 decimal places."
)

S1_INSTRUCTION = (
    "Answer directly with the district name (or yes/no) and the number, "
    "rounded to 3 decimal places."
)
# With thinking off, Haiku 5.5 ignored a plain-text "no working" instruction and wrote its
# calculations anyway (outputs/smoke/s1), which would make S1 a hidden
# single-sample S2. A JSON schema with no room for reasoning keeps S1 truly direct; the
# code renders the JSON as the same ANSWER line, so one parser scores every strategy.
S1_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "number": {"type": "number"}},
    "required": ["name", "number"],
    "additionalProperties": False,
}
S2_INSTRUCTION = (
    "Think step by step: first write down every fact you need and the document it comes "
    "from, then do the calculations, then compare. Then give the ANSWER line."
)
S3_SYSTEM_EXTRA = (
    " You do not have the documents. Use the lookup tool to get every fact you need, and "
    "the calculate tool for every calculation - do not do arithmetic in your head. "
    "When you use a tool, you may say a brief sentence first. If no tool can express what "
    "the question asks for, say so instead of guessing."
)

ANSWER_RE = re.compile(r"ANSWER:\s*\**\s*([^|\n]+?)\s*\|\s*([-+]?[\d,]*\.?\d+)")

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=5)  # key from ANTHROPIC_API_KEY in .env
    return _client


def documents_block() -> str:
    docs = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    parts = [f'<document id="{d["id"]}" title="{d["title"]}">\n{d["text"]}\n</document>' for d in docs]
    return "<documents>\n" + "\n".join(parts) + "\n</documents>"


def parse_answer(text: str):
    """Last ANSWER line in the text -> (name, number) or None."""
    matches = ANSWER_RE.findall(text or "")
    if not matches:
        return None
    name, number = matches[-1]
    name = name.strip().strip("*\"'`. ").strip()
    try:
        return name, float(number.replace(",", ""))
    except ValueError:
        return None


def _call(json_schema: dict | None = None, **kwargs):
    """One API call with the fixed settings. Returns (response, seconds)."""
    output_config = {"effort": EFFORT}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    start = time.perf_counter()
    response = client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking=THINKING,
        output_config=output_config,
        **kwargs,
    )
    return response, time.perf_counter() - start


def _text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text")


def _usage(response) -> dict:
    return {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}


def _result(answer, calls: list[dict], seconds: float, log: dict) -> dict:
    inp = sum(c["input_tokens"] for c in calls)
    out = sum(c["output_tokens"] for c in calls)
    return {
        "answer": answer,  # (name, number) or None = unanswered
        "input_tokens": inp,
        "output_tokens": out,
        "cost": inp * PRICE_IN + out * PRICE_OUT,
        "seconds": seconds,
        "api_calls": len(calls),
        "log": log,
    }


# ---- S1 --------------------------------------------------------------------

def run_s1(question: str) -> dict:
    system = BASE_SYSTEM + "\n\n" + documents_block()
    user = f"{question}\n\n{S1_INSTRUCTION}"
    start = time.perf_counter()
    response, secs = _call(json_schema=S1_SCHEMA, system=system, messages=[{"role": "user", "content": user}])
    raw = _text(response)
    try:
        data = json.loads(raw)
        text = f"ANSWER: {data['name']} | {float(data['number']):f}"
    except (json.JSONDecodeError, KeyError, TypeError):
        text = raw
    call = {**_usage(response), "seconds": secs, "stop_reason": response.stop_reason,
            "raw": raw, "text": text}
    return _result(parse_answer(text), [call], time.perf_counter() - start,
                   {"strategy": "S1", "user": user, "calls": [call]})


# ---- S2 --------------------------------------------------------------------

def majority_vote(answers: list):
    """Most common (name, number) among parsed samples; ties -> most common name, then earliest."""
    valid = [(n.lower(), round(x, 3)) for a in answers if a for n, x in [a]]
    if not valid:
        return None
    counts = Counter(valid)
    name_counts = Counter(n for n, _ in valid)
    best = max(counts, key=lambda key: (counts[key], name_counts[key[0]], -valid.index(key)))
    original_name = next(a[0] for a in answers if a and a[0].lower() == best[0])
    return original_name, best[1]


def run_s2(question: str, k: int = K) -> dict:
    system = BASE_SYSTEM + "\n\n" + documents_block()
    user = f"{question}\n\n{S2_INSTRUCTION}\n{ANSWER_FORMAT}"
    start = time.perf_counter()

    def sample(_):
        response, secs = _call(system=system, messages=[{"role": "user", "content": user}])
        text = _text(response)
        return {**_usage(response), "seconds": secs, "stop_reason": response.stop_reason,
                "text": text, "parsed": parse_answer(text)}

    with ThreadPoolExecutor(max_workers=k) as pool:  # the k samples run in parallel
        calls = list(pool.map(sample, range(k)))
    answer = majority_vote([c["parsed"] for c in calls])
    return _result(answer, calls, time.perf_counter() - start,
                   {"strategy": "S2", "k": k, "user": user, "calls": calls, "vote": answer})


# ---- S3: the tool-calling loop ---------------------------------------------

def run_s3(question: str, vague_lookup: bool = False, max_rounds: int = MAX_ROUNDS) -> dict:
    tools = tool_definitions(vague_lookup)
    system = BASE_SYSTEM + S3_SYSTEM_EXTRA
    user = f"{question}\n\n{ANSWER_FORMAT}"
    messages = [{"role": "user", "content": user}]
    transcript = [{"role": "user", "content": user}]   # JSON-serialisable copy for the log
    calls, tool_calls = [], []
    answer, final_text, status = None, "", "hit_round_limit"
    start = time.perf_counter()

    for round_no in range(1, max_rounds + 1):
        response, secs = _call(system=system, tools=tools, messages=messages)
        calls.append({**_usage(response), "seconds": secs, "round": round_no,
                      "stop_reason": response.stop_reason})
        # The assistant message goes back unchanged, tool_use blocks included.
        messages.append({"role": "assistant", "content": response.content})
        transcript.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "tool_use" and tool_uses:
            results = []
            for block in tool_uses:  # one tool_result for EVERY tool_use id
                t0 = time.perf_counter()
                result, is_error = run_tool(block.name, block.input)
                dt = time.perf_counter() - t0
                tool_calls.append({"round": round_no, "id": block.id, "tool": block.name,
                                   "input": block.input, "result": result,
                                   "is_error": is_error, "seconds": dt})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(result), "is_error": is_error})
            messages.append({"role": "user", "content": results})
            transcript.append({"role": "user", "content": results})
            continue

        final_text = _text(response)
        answer = parse_answer(final_text)
        status = "answered" if answer else f"no_answer_line ({response.stop_reason})"
        break

    if status == "hit_round_limit":
        answer = None  # marked unanswered
    log = {"strategy": "S3", "vague_lookup": vague_lookup, "status": status,
           "rounds": len(calls), "calls": calls, "tool_calls": tool_calls,
           "final_text": final_text, "transcript": transcript}
    return _result(answer, calls, time.perf_counter() - start, log)


STRATEGIES = {"s1": run_s1, "s2": run_s2, "s3": run_s3}
