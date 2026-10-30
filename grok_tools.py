"""OpenAI-style function tools derived from jarvis_mcp.TOOL_SPECS (for Grok API).

`docs/grok_function_tools.json` is the committed export. Regenerate it with
`python grok_tools.py` after TOOL_SPECS changes; tests/test_grok_tools.py
fails if the file drifts from `as_openai_functions()`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jarvis_mcp import TOOL_SPECS

_DEFAULT_PARAMETERS = {"type": "object", "properties": {}}


def as_openai_functions() -> list[dict[str, Any]]:
    """Return tools in OpenAI / xAI chat-completions function-calling shape.

    Each MCP spec's `inputSchema` becomes `function.parameters`. Names stay
    in TOOL_SPECS order so a Grok tool call can be forwarded by that name
    to the existing `/internal/tool` handlers.
    """
    out: list[dict[str, Any]] = []
    for spec in TOOL_SPECS:
        parameters = spec.get("inputSchema") or _DEFAULT_PARAMETERS
        if not isinstance(parameters, dict):
            parameters = _DEFAULT_PARAMETERS
        out.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description") or "",
                "parameters": parameters,
            },
        })
    return out


def write_json(path: str | None = None) -> str:
    """Write docs/grok_function_tools.json (or path). Returns the path written."""
    target = Path(path) if path else Path(__file__).resolve().parent / "docs" / "grok_function_tools.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(as_openai_functions(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return str(target)


if __name__ == "__main__":
    print(write_json())
