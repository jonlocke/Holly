# LLM Tool Aliasing

Holly supports app-side tool execution even when the upstream LLM does not provide native function or tool calling.

## Why aliasing exists

Some weaker or completion-only models do not reliably emit the exact tool identifier Holly expects. Common failure modes:

- surrounding the JSON object with prose
- wrapping the JSON object in Markdown fences
- returning a simplified tool name such as `"Weather"` instead of the canonical tool id
- returning near-miss names such as `"get_current_weather"`
- rewriting literal command arguments instead of copying them from the user request

This is common with small `llama.cpp` style models that are being prompted to imitate tool calling rather than using a native tool/function calling API.

## Holly requirement

When a plugin tool is added, consider whether the raw model output may use a simplified alias. If that risk is real, update `_parse_llm_tool_request()` in [main.py](/home/jonlo/Holly/main.py) to normalize those aliases to the canonical plugin tool name.

Current examples:

- `weather` -> `weather.get_current_weather`
- `get_current_weather` -> `weather.get_current_weather`
## Guidance

- Keep aliasing narrow and explicit.
- Prefer canonical plugin ids in prompts, but do not assume small models will obey them exactly.
- For command-style tools, instruct the model to preserve literal command arguments verbatim.
- Do not treat aliasing as a substitute for schema-constrained decoding when a backend can support it.
- Add a regression test in [tests/test_stream_and_git.py](/home/jonlo/Holly/tests/test_stream_and_git.py) for each alias you accept.
