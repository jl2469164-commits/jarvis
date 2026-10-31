"""How JARVIS invokes the Cursor CLI (`agent` / `cursor-agent`).

The voice brain and the run executor both build their argv and environment
here, so a flag or a scrub cannot be fixed in one child and forgotten in the
other. Authentication is the user's existing `agent` login. This module never
sets `CURSOR_API_KEY` or `XAI_API_KEY`, and it strips both from the child so
a leftover key in `.env` is not what the CLI authenticates with.

`supervise` is the long-lived process the brain keeps open. Each stdin user
message becomes one `agent -p` invocation; stdout is the CLI's stream-json
with a few extra lines the brain's reader already understands (text deltas
and `tool_use` blocks). A stand-in binary passed as `BrainConfig.claude_path`
skips this and speaks that protocol itself — that is the test double, not a
second production backend.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import claude_env

# Override the binary. A name on PATH (`agent`) or an absolute path both work.
# Not a secret.
BIN_ENV = "JARVIS_CURSOR_AGENT"
_CANDIDATES = ("agent", "cursor-agent")

# Keys that must not decide how the CLI authenticates. Login lives in the
# user's Cursor config (HOME), which is passed through.
_SCRUB_KEYS = frozenset({"XAI_API_KEY", "CURSOR_API_KEY"})

_STDERR_CHARS = 2000


def resolve_executable(explicit: Optional[str] = None) -> str:
    """The Cursor CLI to spawn.

    `explicit`, else `JARVIS_CURSOR_AGENT`, else `agent` on PATH, else
    `cursor-agent`. The final fallback is the bare name `agent` so a missing
    install fails at spawn with a clear error instead of silently picking
    some other binary.
    """
    chosen = (explicit or os.environ.get(BIN_ENV) or "").strip()
    if chosen:
        path = Path(chosen)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = shutil.which(chosen)
        return found or chosen
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return "agent"


def child_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Environment for every Cursor CLI child.

    Starts from `claude_env.child_env` (drops `ANTHROPIC_*` / `CLAUDE_CODE_*`
    so a leftover Claude key cannot redirect a child) and also drops
    `XAI_API_KEY` and `CURSOR_API_KEY`. HOME, PATH and the rest pass through
    so the existing `agent` login session is visible.
    """
    env = claude_env.child_env(base)
    for key in list(env):
        if key in _SCRUB_KEYS or key.startswith("AIDER"):
            del env[key]
    return env


def split_executable(executable: str) -> list[str]:
    """`shlex.split` so a test double of `python script.py` stays two argv."""
    parts = shlex.split(executable)
    return parts or ["agent"]


def print_argv(executable: str, *, model: str, force: bool = True,
               resume: Optional[str] = None, partial: bool = False,
               approve_mcps: bool = False, workspace: Optional[str] = None,
               extra: Optional[list[str]] = None) -> list[str]:
    """Argv for one headless `agent -p` turn. The prompt is NOT included.

    The caller writes the prompt to stdin and closes it. That keeps long
    prompts out of the process table and matches print mode's piped-stdin
    path. `--trust` is always set: without it a headless run in an untrusted
    workspace fails or sits on a dialog nobody can answer. `--force` is the
    same idea for shell and file edits (JARVIS has no TTY).
    """
    cmd = split_executable(executable) + [
        "-p",
        "--output-format", "stream-json",
        "--trust",
        "--model", model,
    ]
    if partial:
        cmd.append("--stream-partial-output")
    if force:
        cmd.append("--force")
    if approve_mcps:
        cmd.append("--approve-mcps")
    if workspace:
        cmd += ["--workspace", workspace]
    if resume:
        cmd += ["--resume", resume]
    if extra:
        cmd += list(extra)
    return cmd


def supervise_argv(*, model: str, system_prompt: str,
                   agent: Optional[str] = None,
                   mcp_config: Optional[str] = None,
                   extra: Optional[list[str]] = None) -> list[str]:
    """Argv for the brain's long-lived child: this module's `supervise` mode.

    Invoked by path, not `python -m`. The brain's cwd is its home directory,
    which is not on `sys.path`, so `-m cursor_cli` would fail to import.
    Running the file puts the repo root on the child's `sys.path[0]`.
    """
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "supervise",
        "--model", model,
        "--append-system-prompt", system_prompt,
    ]
    if agent:
        cmd += ["--agent", agent]
    if mcp_config:
        cmd += ["--mcp-config", mcp_config]
    if extra:
        cmd += ["--", *extra]
    return cmd


def _parse_supervise(argv: list[str]) -> dict:
    out = {
        "model": "sonnet",
        "system_prompt": "",
        "agent": None,
        "mcp_config": None,
        "extra": [],
    }
    flags = {
        "--model": "model",
        "--append-system-prompt": "system_prompt",
        "--agent": "agent",
        "--mcp-config": "mcp_config",
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            out["extra"] = argv[i + 1:]
            break
        key = flags.get(arg)
        if key and i + 1 < len(argv):
            out[key] = argv[i + 1]
            i += 2
            continue
        i += 1
    return out


def _user_text(line: str) -> str:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(msg, dict):
        return line
    content = (msg.get("message") or {}).get("content", "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _write_event(obj: dict) -> None:
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
    sys.stdout.buffer.flush()


def _assistant_text(event: dict) -> str:
    message = event.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def _tool_name(event: dict) -> str:
    tc = event.get("tool_call")
    if not isinstance(tc, dict) or not tc:
        return "tool"
    fn = tc.get("function")
    if isinstance(fn, dict) and fn.get("name"):
        return str(fn["name"])
    key = next(iter(tc))
    if key.endswith("ToolCall"):
        return key[: -len("ToolCall")] or "tool"
    return str(key)


def _tool_input(event: dict) -> dict:
    tc = event.get("tool_call")
    if not isinstance(tc, dict) or not tc:
        return {}
    fn = tc.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("arguments"), dict):
        return fn["arguments"]
    body = tc.get(next(iter(tc)))
    if isinstance(body, dict) and isinstance(body.get("args"), dict):
        return body["args"]
    return {}


def _events_for_brain(event: dict, saw_delta: bool) -> tuple[list[dict], bool]:
    """Translate one Cursor stream-json event into lines the brain reads.

    Cursor's partial deltas are `assistant` events, not Claude
    `stream_event`s. The brain speaks from `content_block_delta`, so a new
    delta is also emitted in that shape. Buffered flushes (`model_call_id`
    set, or a final copy after deltas) are forwarded but not spoken twice.
    """
    kind = event.get("type")
    if kind == "assistant":
        if "model_call_id" in event:
            return [event], saw_delta
        fresh = ("timestamp_ms" in event) or not saw_delta
        text = _assistant_text(event) if fresh else ""
        out: list[dict] = []
        if text:
            out.append({
                "type": "stream_event",
                "session_id": event.get("session_id"),
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
            })
            saw_delta = True
        out.append(event)
        return out, saw_delta
    if kind == "tool_call" and event.get("subtype") == "started":
        return [
            {
                "type": "assistant",
                "session_id": event.get("session_id"),
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "name": _tool_name(event),
                        "input": _tool_input(event),
                    }],
                },
            },
            event,
        ], saw_delta
    return [event], saw_delta


def _install_mcp(src: Optional[str]) -> None:
    """Cursor reads `.cursor/mcp.json` from the workspace. JARVIS already
    wrote the server list for the brain; copy it into place. Failure here
    must not kill the session — the turn can still answer without MCP.
    """
    if not src:
        return
    try:
        data = Path(src).read_bytes()
    except OSError as e:
        sys.stderr.write(f"cursor_cli: could not read mcp config: {e}\n")
        return
    dest_dir = Path.cwd() / ".cursor"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "mcp.json"
        dest.write_bytes(data)
        dest.chmod(0o600)
    except OSError as e:
        sys.stderr.write(f"cursor_cli: could not install mcp config: {e}\n")


def _emit_error(text: str) -> None:
    _write_event({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    })
    _write_event({
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": text,
    })


def _run_one(agent: str, model: str, prompt: str, session_id: Optional[str],
             extra: list[str]) -> Optional[str]:
    """One `agent -p` turn. Returns the CLI session id if one was reported."""
    cmd = print_argv(
        agent, model=model, force=True, partial=True, approve_mcps=True,
        resume=session_id, workspace=os.getcwd() or None, extra=extra or None,
    )
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env(),
        )
    except OSError as e:
        _emit_error(f"could not start cursor agent: {e}")
        return session_id
    try:
        if proc.stdin is not None:
            proc.stdin.write(prompt.encode("utf-8", errors="replace"))
            proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    err_tail: list[str] = []

    def _drain() -> None:
        if proc.stderr is None:
            return
        data = proc.stderr.read()
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        err_tail.append(text[-_STDERR_CHARS:])
        sys.stderr.write(text)

    drainer = threading.Thread(target=_drain, daemon=True)
    drainer.start()

    saw_result = False
    saw_delta = False
    found = session_id
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("session_id"):
                found = str(event["session_id"])
            translated, saw_delta = _events_for_brain(event, saw_delta)
            for item in translated:
                _write_event(item)
            if event.get("type") == "result":
                saw_result = True
    except BrokenPipeError:
        proc.kill()
        raise
    finally:
        rc = proc.wait()
        drainer.join(timeout=2)
        if not saw_result:
            detail = (err_tail[0].strip() if err_tail else "") or f"cursor agent exited {rc}"
            _emit_error(detail[:_STDERR_CHARS])
    return found


def supervise(argv: list[str]) -> int:
    """Read brain user-messages on stdin and run `agent -p` for each one.

    Stays up until stdin closes. One bad turn emits an error result and the
    loop continues; the brain decides whether that is fatal. Never raises
    out of a turn — an exception here would look like the language systems
    dying with no result event.
    """
    opts = _parse_supervise(argv)
    _install_mcp(opts["mcp_config"])
    agent = resolve_executable(opts["agent"])
    session_id: Optional[str] = None
    first = True
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        text = _user_text(line)
        if first and opts["system_prompt"]:
            prompt = opts["system_prompt"] + "\n\n" + text
            first = False
        else:
            prompt = text
        try:
            session_id = _run_one(
                agent, opts["model"] or "sonnet", prompt, session_id, opts["extra"],
            )
        except BrokenPipeError:
            return 0
        except Exception as e:
            try:
                _emit_error(f"cursor agent turn failed: {e}")
            except BrokenPipeError:
                return 0
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "supervise":
        return supervise(argv[1:])
    sys.stderr.write("usage: cursor_cli.py supervise --model MODEL "
                     "--append-system-prompt TEXT [--agent PATH]\n")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BrokenPipeError:
        raise SystemExit(0)
