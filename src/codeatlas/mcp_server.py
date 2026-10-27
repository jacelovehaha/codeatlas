"""A minimal stdio MCP server exposing an atlas as tools.

Speaks newline-delimited JSON-RPC 2.0: ``initialize``, ``ping``,
``tools/list`` and ``tools/call``. No third-party dependencies.
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "search_symbols",
        "description": "Search atlas symbols by substring over ids and docstrings.",
        "inputSchema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
        },
    },
    {
        "name": "callers_of",
        "description": "List symbols that call the given symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "callees_of",
        "description": "List symbols called by the given symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "module_deps",
        "description": "Show what a module imports and what imports it.",
        "inputSchema": {
            "type": "object",
            "properties": {"module": {"type": "string"}},
            "required": ["module"],
        },
    },
]


def _call_tool(atlas, name: str, arguments: dict):
    if name == "search_symbols":
        term = arguments.get("term") or arguments.get("query") or ""
        return [
            {"id": n["id"], "kind": n["kind"], "file": n["file"], "line": n["line"]}
            for n in atlas.search(term)
        ]
    if name == "callers_of":
        return atlas.callers_of(arguments.get("symbol", ""))
    if name == "callees_of":
        return atlas.callees_of(arguments.get("symbol", ""))
    if name == "module_deps":
        return atlas.module_deps(arguments.get("module") or arguments.get("symbol", ""))
    raise ValueError(f"unknown tool: {name}")


def handle_message(atlas, message: dict):
    """Handle one JSON-RPC message; return a response dict or None."""
    method = message.get("method", "")
    msg_id = message.get("id")
    is_notification = msg_id is None

    def result(value):
        return {"jsonrpc": "2.0", "id": msg_id, "result": value}

    def error(code, text):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        return result(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codeatlas", "version": "0.1.0"},
            }
        )
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return result({})
    if method == "tools/list":
        return result({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            value = _call_tool(atlas, params.get("name", ""), params.get("arguments") or {})
        except ValueError as exc:
            if is_notification:
                return None
            return error(-32602, str(exc))
        text = json.dumps(value, ensure_ascii=False)
        return result({"content": [{"type": "text", "text": text}], "isError": False})
    if is_notification:
        return None
    return error(-32601, f"method not found: {method}")


def serve(atlas, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(atlas, message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
