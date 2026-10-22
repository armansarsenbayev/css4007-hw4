"""Final question 3: how many input tokens do the two tool definitions add to a request?

Sends the same short request with and without tools and compares usage.prompt_tokens.
Result is saved to outputs/tool_tokens.json.
"""
import json

import strategies as S
from tools import tool_schemas, YEAR_DESCRIPTION_V1, YEAR_DESCRIPTION_V2, VAGUE_LOOKUP_DESCRIPTION

msgs = [{"role": "user", "content": "Say OK."}]
_, base = S.chat(msgs)
out = {"without_tools": base["input_tokens"]}
for name, kw in {"tools_v1": {"year_description": YEAR_DESCRIPTION_V1},
                 "tools_v2": {"year_description": YEAR_DESCRIPTION_V2},
                 "tools_v2_vague_lookup": {"year_description": YEAR_DESCRIPTION_V2,
                                           "lookup_description": VAGUE_LOOKUP_DESCRIPTION}}.items():
    _, rec = S.chat(msgs, tools=tool_schemas(**kw))
    out[name] = rec["input_tokens"]
    out[name + "_added"] = rec["input_tokens"] - base["input_tokens"]
print(json.dumps(out, indent=2))
with open("outputs/tool_tokens.json", "w") as f:
    json.dump(out, f, indent=2)
