"""The Grok function-tool export stays aligned with jarvis_mcp.TOOL_SPECS."""
import json
from pathlib import Path

import grok_tools
from jarvis_mcp import TOOL_SPECS

ROOT = Path(__file__).parent.parent
COMMITTED = ROOT / "docs" / "grok_function_tools.json"


def test_committed_function_tools_match_tool_specs():
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    live = grok_tools.as_openai_functions()
    assert committed == live
    assert [tool["function"]["name"] for tool in committed] == [spec["name"] for spec in TOOL_SPECS]


def test_each_tool_is_an_openai_function_with_the_mcp_schema():
    tools = grok_tools.as_openai_functions()
    assert tools, "TOOL_SPECS produced no functions"
    for spec, tool in zip(TOOL_SPECS, tools):
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["name"] == spec["name"]
        assert function["description"] == (spec.get("description") or "")
        expected = spec.get("inputSchema") or {"type": "object", "properties": {}}
        assert function["parameters"] == expected
        assert function["parameters"]["type"] == "object"
        assert "properties" in function["parameters"]


def test_write_json_round_trips(tmp_path):
    target = tmp_path / "grok_function_tools.json"
    written = grok_tools.write_json(str(target))
    assert written == str(target)
    assert json.loads(target.read_text(encoding="utf-8")) == grok_tools.as_openai_functions()
