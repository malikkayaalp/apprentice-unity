"""MCP Streamable HTTP transport (spec 2025-03-26 onwards), dependency free.

Some tool servers (e.g. game-engine bridges) run either as a stdio subprocess or as a local HTTP server. When the
editor already holds a live session, HTTP
is the better target: the editor is already attached, so there is no process to launch
and no risk of disturbing another client's stdio configuration.

Protocol notes that matter in practice:
  - Everything is POSTed to one endpoint (/mcp here).
  - The server may answer with either application/json or a text/event-stream, and
    FastMCP answers with SSE even for ordinary request/response calls, so both have to
    be parsed.
  - initialize returns an mcp-session-id header that every later request must echo.
  - MCP-Protocol-Version must be sent after initialization.

Exposes the same surface as MCPServer in client.py, so MCPPool takes either one.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Any

from mcpbridge.client import MCPError

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "gptoss-harness", "version": "0.1.0"}


def _parse_sse(body: str) -> list[dict]:
    """Pull JSON payloads out of an SSE stream."""
    out = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return out


class MCPHttpServer:
    def __init__(self, url: str, *, name: str = "", timeout: float = 300.0,
                 headers: dict | None = None):
        self.url = url
        self.name = name or url
        self.timeout = timeout
        self.extra_headers = headers or {}
        self.session_id: str | None = None
        self._id = 0
        self._server_info: dict = {}
        self._capabilities: dict = {}
        self._instructions: str = ""

    # ---------------------------------------------------------------- transport
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self.session_id:
            h["mcp-session-id"] = self.session_id
            h["MCP-Protocol-Version"] = PROTOCOL_VERSION
        h.update(self.extra_headers)
        return h

    def _send(self, payload: dict, timeout: float | None = None) -> tuple[str, dict]:
        req = urllib.request.Request(
            self.url, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            detail = e.read()[:400].decode("utf-8", "replace")
            raise MCPError("HTTP %s from %s: %s" % (e.code, self.url, detail)) from None
        except Exception as e:
            raise MCPError("%s: %s" % (type(e).__name__, e)) from None

    def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self._id += 1
        rid = self._id
        body, headers = self._send(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, timeout)
        sid = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        msgs = _parse_sse(body) if "text/event-stream" in \
            (headers.get("Content-Type") or headers.get("content-type") or "") \
            else [json.loads(body)] if body.strip() else []
        for m in msgs:
            if m.get("id") != rid:
                continue                      # server-initiated notification
            if "error" in m:
                e = m["error"]
                raise MCPError("%s: %s" % (e.get("code"), e.get("message")))
            return m.get("result", {})
        raise MCPError("no reply to %s (got %d message(s))" % (method, len(msgs)))

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---------------------------------------------------------------- api
    def start(self) -> dict:
        init = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
            "clientInfo": CLIENT_INFO})
        self._server_info = init.get("serverInfo", {})
        self._capabilities = init.get("capabilities", {})
        self._instructions = init.get("instructions", "") or ""
        self.notify("notifications/initialized", {})
        return init

    def list_tools(self) -> list[dict]:
        out, cursor = [], None
        while True:
            r = self.request("tools/list", {"cursor": cursor} if cursor else {})
            out.extend(r.get("tools", []))
            cursor = r.get("nextCursor")
            if not cursor:
                return out

    def call_tool(self, name: str, arguments: dict, timeout: float | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments},
                            timeout)

    def list_resources(self) -> list[dict]:
        try:
            return self.request("resources/list", {}).get("resources", [])
        except MCPError:
            return []

    def read_resource(self, uri: str) -> dict:
        return self.request("resources/read", {"uri": uri})

    def list_prompts(self) -> list[dict]:
        try:
            return self.request("prompts/list", {}).get("prompts", [])
        except MCPError:
            return []

    def stderr_tail(self, n: int = 25) -> str:
        return "(http transport: server logs live on the server side)"

    def stop(self) -> None:
        if not self.session_id:
            return
        try:                                   # best effort, spec-optional
            req = urllib.request.Request(self.url, headers=self._headers(),
                                         method="DELETE")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
        self.session_id = None

    @property
    def info(self) -> dict:
        return {"server": self._server_info, "capabilities": self._capabilities,
                "instructions_chars": len(self._instructions)}

    @property
    def instructions(self) -> str:
        return self._instructions
