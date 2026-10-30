"""The shared Cursor CLI helper: argv, env, and one supervised turn."""
import json
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cursor_cli


def test_resolve_prefers_an_explicit_path(tmp_path):
    binary = tmp_path / "agent"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    assert cursor_cli.resolve_executable(str(binary)) == str(binary)


def test_resolve_env_override(monkeypatch, tmp_path):
    binary = tmp_path / "cursor-agent"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("JARVIS_CURSOR_AGENT", str(binary))
    assert cursor_cli.resolve_executable() == str(binary)


def test_child_env_drops_provider_keys_and_keeps_home(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-secret")
    monkeypatch.setenv("AIDER_MODEL", "gpt-4")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("HOME", "/keep/home")
    env = cursor_cli.child_env()
    assert "XAI_API_KEY" not in env
    assert "CURSOR_API_KEY" not in env
    assert "AIDER_MODEL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["HOME"] == "/keep/home"
    assert "CURSOR_API_KEY" not in cursor_cli.child_env()


def test_print_argv_is_headless_and_does_not_embed_the_prompt():
    cmd = cursor_cli.print_argv(
        "agent", model="sonnet", force=True, resume="chat-9", partial=True,
    )
    assert cmd[:1] == ["agent"]
    assert "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--resume") + 1] == "chat-9"
    assert "--force" in cmd and "--trust" in cmd
    assert "--stream-partial-output" in cmd
    assert "chat-9" not in cmd[cmd.index("--model") + 1]


def test_print_argv_can_withhold_force():
    cmd = cursor_cli.print_argv("agent", model="sonnet", force=False)
    assert "--force" not in cmd
    assert "--trust" in cmd


def test_streaming_delta_becomes_a_brain_text_delta():
    event = {
        "type": "assistant",
        "timestamp_ms": 1,
        "session_id": "s",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
    }
    lines, saw = cursor_cli._events_for_brain(event, False)
    assert saw is True
    assert lines[0]["type"] == "stream_event"
    assert lines[0]["event"]["delta"]["text"] == "Hi"
    assert lines[1] is event


def test_a_buffered_flush_is_not_spoken_twice():
    event = {
        "type": "assistant",
        "timestamp_ms": 2,
        "model_call_id": "m",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
    }
    lines, saw = cursor_cli._events_for_brain(event, True)
    assert lines == [event]
    assert saw is True


def _fake_agent(tmp_path: Path) -> Path:
    script = tmp_path / "fake-agent.py"
    marker = tmp_path / "calls.jsonl"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"prompt = sys.stdin.read()\n"
        f"open({str(marker)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'prompt': prompt}}) + '\\n')\n"
        "sid = 'sess-1'\n"
        "def emit(obj):\n"
        "    sys.stdout.write(json.dumps(obj) + '\\n')\n"
        "    sys.stdout.flush()\n"
        "emit({'type': 'system', 'subtype': 'init', 'session_id': sid, 'model': 'fake'})\n"
        "emit({'type': 'assistant', 'timestamp_ms': 1, 'session_id': sid,\n"
        "      'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'OK'}]}})\n"
        "emit({'type': 'tool_call', 'subtype': 'started', 'session_id': sid,\n"
        "      'tool_call': {'readToolCall': {'args': {'path': 'README.md'}}}})\n"
        "emit({'type': 'result', 'subtype': 'success', 'is_error': False,\n"
        "      'result': 'OK', 'session_id': sid})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_supervise_sends_the_prompt_to_the_agent_and_streams(tmp_path):
    agent = _fake_agent(tmp_path)
    user = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
    proc = subprocess.run(
        [sys.executable, str(Path(cursor_cli.__file__).resolve()), "supervise",
         "--model", "sonnet", "--agent", str(agent),
         "--append-system-prompt", "BE THE BUTLER"],
        input=user + "\n" + user + "\n",
        capture_output=True, text=True, timeout=15, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert any(e.get("type") == "stream_event" and e["event"]["delta"]["text"] == "OK"
               for e in events)
    assert any(e.get("type") == "tool_call" for e in events)
    assert any(
        e.get("type") == "assistant"
        and any(b.get("type") == "tool_use" and b.get("name") == "read"
                for b in (e.get("message") or {}).get("content") or [])
        for e in events
    )
    assert events[-1]["type"] == "result" and events[-1]["is_error"] is False
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 2
    assert calls[0]["prompt"].startswith("BE THE BUTLER")
    assert calls[0]["prompt"].endswith("hello")
    assert "--force" in calls[0]["argv"] and "--trust" in calls[0]["argv"]
    assert calls[0]["argv"][calls[0]["argv"].index("--model") + 1] == "sonnet"
    assert "--resume" not in calls[0]["argv"]
    assert calls[1]["argv"][calls[1]["argv"].index("--resume") + 1] == "sess-1"
    assert calls[1]["prompt"] == "hello"
    assert "CURSOR_API_KEY" not in calls[0]["argv"]


def test_supervise_reports_a_missing_binary_without_crashing(tmp_path):
    user = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
    proc = subprocess.run(
        [sys.executable, str(Path(cursor_cli.__file__).resolve()), "supervise",
         "--model", "sonnet", "--agent", str(tmp_path / "missing-agent"),
         "--append-system-prompt", "BE THE BUTLER"],
        input=user + "\n",
        capture_output=True, text=True, timeout=15, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert events[-1]["type"] == "result"
    assert events[-1]["is_error"] is True
    assert "could not start" in events[-1]["result"]
