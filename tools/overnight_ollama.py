#!/usr/bin/env python3
"""
ollama_agent.py - A local, agentic coding assistant backed by Ollama.

Unlike overnight_ollama.py (which asks a model fixed questions and saves
essays), this is an actual agent: it can read files, write/edit files, list
directories, search text, and run shell commands, looping until the task is
done or it gives up. Runs fully locally against an Ollama server.

Safety model:
- File writes are shown as a diff and require confirmation, unless --yolo.
- Shell commands are shown before running and require confirmation, unless
  --yolo or --auto-approve-shell.
- All file operations are confined to --workdir (default: current directory).
  The agent cannot read or write outside that tree.

Requires: Ollama server running (`ollama serve`), and a tool-calling-capable
model pulled (qwen2.5-coder:7b or qwen2.5-coder:3b recommended; both support
Ollama's native tool-calling API). Stdlib only - nothing to pip install.

Usage:
    python ollama_agent.py                          # interactive chat loop
    python ollama_agent.py -p "add a .gitignore"     # single task, then exit
    python ollama_agent.py -p "..." --yolo           # no confirmations (careful)
    python ollama_agent.py --model qwen2.5-coder:3b
    python ollama_agent.py --workdir /path/to/repo
"""

import argparse
import difflib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:11434"
MODEL_PREFS = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "deepseek-r1:7b", "llama3.2:latest"]
MAX_TOOL_ROUNDS = 25          # hard stop so a confused model can't loop forever
MAX_FILE_READ_BYTES = 200_000  # don't blow the context window on one huge file

SYSTEM_PROMPT = """You are a careful local coding agent working inside a single \
project directory on the user's machine. You have tools to read files, write \
files, list directories, search text, and run shell commands.

Rules:
- Always read a file before editing it, so your edit is based on its real content.
- Prefer small, targeted edits over rewriting whole files.
- Explain what you're about to do in one short sentence before calling a tool.
- After file writes or shell commands, check the result before claiming success.
- If a shell command fails, read the actual error and fix the real cause -
  don't guess or claim it worked if it didn't.
- When the task is genuinely complete, say so plainly in a final message with
  no further tool calls. Don't pad with unnecessary extra actions.
- You cannot access anything outside the project directory you were given.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file's contents, relative to the project root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative file path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file with new content. Shown as a diff and confirmed before writing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "Full new file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories at a relative path (non-recursive).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative directory path, '.' for root"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search for a literal substring across text files under the project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "Relative dir to search under, default '.'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command inside the project root. Shown and confirmed before running.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to execute"}},
                "required": ["command"],
            },
        },
    },
]

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pio", ".freebuff"}


# --------------------------------------------------------------------------
# Ollama API plumbing
# --------------------------------------------------------------------------

def api(path: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models() -> list:
    try:
        return [m["name"] for m in api_get("/api/tags").get("models", [])]
    except (urllib.error.URLError, OSError) as e:
        print(f"FATAL: cannot reach Ollama at {API}: {e}", file=sys.stderr)
        print("Start it with: ollama serve", file=sys.stderr)
        sys.exit(1)


def api_get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_model(override: str, models: list) -> str:
    if override:
        if not any(m == override or m.split(":")[0] == override for m in models):
            print(f"FATAL: model '{override}' not pulled. Available: {models}", file=sys.stderr)
            sys.exit(1)
        return override
    for pref in MODEL_PREFS:
        if pref in models:
            return pref
    if models:
        print(f"No preferred model found; falling back to {models[0]}")
        return models[0]
    print("FATAL: no models pulled. Run: ollama pull qwen2.5-coder:7b", file=sys.stderr)
    sys.exit(1)


def chat(model: str, messages: list, num_ctx: int) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": num_ctx},
    }
    resp = api("/api/chat", payload, timeout=600)
    return resp.get("message", {})


# --------------------------------------------------------------------------
# Sandboxed filesystem tools
# --------------------------------------------------------------------------

class Sandbox:
    """Confines every file/shell operation to a single root directory."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _resolve(self, rel_path: str) -> str:
        full = os.path.abspath(os.path.join(self.root, rel_path))
        if not (full == self.root or full.startswith(self.root + os.sep)):
            raise PermissionError(f"path '{rel_path}' escapes the project root")
        return full

    def read_file(self, path: str) -> str:
        full = self._resolve(path)
        if not os.path.isfile(full):
            return f"ERROR: no such file: {path}"
        size = os.path.getsize(full)
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_FILE_READ_BYTES)
        if size > MAX_FILE_READ_BYTES:
            text += f"\n\n[TRUNCATED: file is {size} bytes, showed first {MAX_FILE_READ_BYTES}]"
        return text

    def write_file(self, path: str, content: str, yolo: bool) -> str:
        full = self._resolve(path)
        old = ""
        if os.path.isfile(full):
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()

        diff = "\n".join(difflib.unified_diff(
            old.splitlines(), content.splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        ))
        print(f"\n--- proposed write: {path} ---")
        print(diff if diff.strip() else "(no textual diff - identical or new file)")
        print("--- end diff ---\n")

        if not yolo:
            ans = input(f"Apply this write to {path}? [y/N] ").strip().lower()
            if ans != "y":
                return "WRITE CANCELLED by user."

        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: wrote {len(content)} bytes to {path}"

    def list_dir(self, path: str) -> str:
        full = self._resolve(path)
        if not os.path.isdir(full):
            return f"ERROR: no such directory: {path}"
        entries = sorted(os.listdir(full))
        entries = [e for e in entries if e not in SKIP_DIRS]
        return "\n".join(entries) if entries else "(empty)"

    def search_text(self, query: str, path: str = ".") -> str:
        full = self._resolve(path)
        hits = []
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                fpath = os.path.join(dirpath, name)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if query in line:
                                rel = os.path.relpath(fpath, self.root)
                                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                                if len(hits) >= 100:
                                    return "\n".join(hits) + "\n[truncated at 100 hits]"
                except OSError:
                    continue
        return "\n".join(hits) if hits else "no matches"

    def run_command(self, command: str, yolo: bool, auto_shell: bool) -> str:
        print(f"\n--- proposed command (cwd={self.root}) ---\n{command}\n--- end command ---")
        if not (yolo or auto_shell):
            ans = input("Run this command? [y/N] ").strip().lower()
            if ans != "y":
                return "COMMAND CANCELLED by user."
        try:
            result = subprocess.run(
                command, shell=True, cwd=self.root,
                capture_output=True, text=True, timeout=300,
            )
            out = (result.stdout or "") + (result.stderr or "")
            out = out[-8000:]  # keep the tail; that's usually where errors are
            return f"exit={result.returncode}\n{out}"
        except subprocess.TimeoutExpired:
            return "ERROR: command timed out after 300s"


def dispatch_tool(sandbox: Sandbox, name: str, args: dict, yolo: bool, auto_shell: bool) -> str:
    try:
        if name == "read_file":
            return sandbox.read_file(args["path"])
        if name == "write_file":
            return sandbox.write_file(args["path"], args["content"], yolo)
        if name == "list_dir":
            return sandbox.list_dir(args.get("path", "."))
        if name == "search_text":
            return sandbox.search_text(args["query"], args.get("path", "."))
        if name == "run_command":
            return sandbox.run_command(args["command"], yolo, auto_shell)
        return f"ERROR: unknown tool '{name}'"
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001 - must not crash the agent loop
        return f"ERROR: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# Agent loop
# --------------------------------------------------------------------------

def run_task(model: str, sandbox: Sandbox, task: str, num_ctx: int, yolo: bool, auto_shell: bool):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for round_i in range(1, MAX_TOOL_ROUNDS + 1):
        msg = chat(model, messages, num_ctx)
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        if content.strip():
            print(f"\n[agent] {content.strip()}\n")

        if not tool_calls:
            # Model gave a final answer with no further tool calls - done.
            return

        messages.append(msg)
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            print(f"[tool] {name}({', '.join(f'{k}=...' for k in args)})")
            result = dispatch_tool(sandbox, name, args, yolo, auto_shell)
            messages.append({"role": "tool", "content": result})

    print(f"\n[agent] stopped after {MAX_TOOL_ROUNDS} tool-call rounds (safety limit). "
          f"Re-run with a more specific task if it didn't finish.")


def main():
    ap = argparse.ArgumentParser(description="Local agentic coding assistant backed by Ollama")
    ap.add_argument("-p", "--prompt", help="Single task to run, then exit. Omit for interactive chat.")
    ap.add_argument("--model", help="Ollama model (default: auto-pick a coding model)")
    ap.add_argument("--workdir", default=".", help="Project root the agent is confined to (default: cwd)")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--yolo", action="store_true", help="Skip ALL confirmations (writes and commands). Use with care.")
    ap.add_argument("--auto-approve-shell", action="store_true", help="Skip confirmation for shell commands only")
    args = ap.parse_args()

    sandbox = Sandbox(args.workdir)
    print(f"Project root: {sandbox.root}")

    models = list_models()
    model = pick_model(args.model, models)
    print(f"Using model: {model}")
    if args.yolo:
        print("YOLO MODE: writes and commands will run WITHOUT confirmation.")

    if args.prompt:
        run_task(model, sandbox, args.prompt, args.num_ctx, args.yolo, args.auto_approve_shell)
        return

    print("Interactive mode. Type a task and press Enter twice (blank line) to submit.")
    print("Type 'exit' alone to quit.\n")
    while True:
        lines = []
        try:
            first = input("task> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if first.strip().lower() in ("exit", "quit"):
            break
        lines.append(first)
        # Keep reading lines until a blank line (so pasted multi-line tasks
        # don't get split into separate, incoherent single-line prompts).
        try:
            while True:
                line = input("...   ")
                if line.strip() == "":
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print()

        task = "\n".join(lines).strip()
        if not task:
            continue
        run_task(model, sandbox, task, args.num_ctx, args.yolo, args.auto_approve_shell)


if __name__ == "__main__":
    main()