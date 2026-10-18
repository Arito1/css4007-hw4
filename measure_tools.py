"""How many input tokens do the two tool definitions add to every S3 request?

Counts the same S3 first request with and without `tools=[...]` (count_tokens is free).
    python measure_tools.py
"""

import json
from pathlib import Path

import strategies as S
from tools import tool_definitions

question = json.loads((Path(__file__).parent / "data" / "questions.json").read_text(encoding="utf-8"))[8]
messages = [{"role": "user", "content": f"{question['question']}\n\n{S.ANSWER_FORMAT}"}]
system = S.BASE_SYSTEM + S.S3_SYSTEM_EXTRA


def count(**kwargs) -> int:
    return S.client().messages.count_tokens(model=S.MODEL, system=system, messages=messages, **kwargs).input_tokens


without = count()
with_tools = count(tools=tool_definitions())
with_vague = count(tools=tool_definitions(vague_lookup=True))
docs = S.client().messages.count_tokens(
    model=S.MODEL, system=S.BASE_SYSTEM + "\n\n" + S.documents_block(), messages=messages).input_tokens

result = {
    "question": question["id"],
    "s3_first_request_without_tools": without,
    "s3_first_request_with_tools": with_tools,
    "tool_definitions_add": with_tools - without,
    "tool_definitions_add_vague_lookup": with_vague - without,
    "s1_s2_request_with_documents": docs,
}
print(json.dumps(result, indent=2))
(Path(__file__).parent / "outputs" / "tool_tokens.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
