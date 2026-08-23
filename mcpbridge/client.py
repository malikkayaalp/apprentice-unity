"""Minimal dependency-free MCP client (stdio, JSON-RPC 2.0).

Written from scratch rather than pulling the SDK so the wire traffic stays inspectable
and the harness has no install step. Speaks enough of the protocol for real servers:
initialize / initialized / tools list / tools call / prompts / resources.

Usage:
    srv = MCPServer("uv", ["run", "server.py"], cwd="...")
    srv.start()
    tools = srv.list_tools()                     # MCP tool defs
    ollama_tools = to_ollama_tools(tools)        # converted schemas
    out = srv.call_tool("unity_create_gameobject", {"name": "Cube"})
"""
from __future__ import annotations
import json, os, queue, subprocess, sys, threading, time
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "gptoss-harness", "version": "0.1.0"}


class MCPError(RuntimeError):
    pass


class MCPServer:
    def __init__(self, command: str, args: list[str] | None = None, *,
                 cwd: str | None = None, env: dict | None = None,
                 name: str = "", timeout: float = 60.0):
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env
        self.name = name or os.path.basename(command)
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        self._id = 0
        self._server_info: dict = {}
        self._capabilities: dict = {}

    # ---------------------------------------------------------------- process
    def start(self) -> dict:
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self.env:
            env.update(self.env)
        self.proc = subprocess.Popen(
            [self.command] + self.args, cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        init = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
            "clientInfo": CLIENT_INFO})
        self._server_info = init.get("serverInfo", {})
        self._capabilities = init.get("capabilities", {})
        self.notify("notifications/initialized", {})
        return init

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                self._stderr.append("[non-json stdout] " + line[:400])

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())
            if len(self._stderr) > 800:
                del self._stderr[:400]

    def stderr_tail(self, n: int = 25) -> str:
        return "\n".join(self._stderr[-n:])

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self.proc = None

    # ---------------------------------------------------------------- rpc
    def _send(self, obj: dict) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("server not running")
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + (timeout or self.timeout)
        pending: list[dict] = []
        while time.time() < deadline:
            try:
                msg = self._q.get(timeout=0.25)
            except queue.Empty:
                if self.proc and self.proc.poll() is not None:
                    raise MCPError("server exited (%s)\n%s" %
                                   (self.proc.returncode, self.stderr_tail()))
                continue
            if msg.get("id") != rid:
                pending.append(msg)      # server request or out-of-order reply
                continue
            for p in pending:
                self._q.put(p)
            if "error" in msg:
                e = msg["error"]
                raise MCPError("%s: %s" % (e.get("code"), e.get("message")))
            return msg.get("result", {})
        raise MCPError("timeout waiting for " + method + "\n" + self.stderr_tail())

    # ---------------------------------------------------------------- api
    def list_tools(self) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"cursor": cursor} if cursor else {}
            r = self.request("tools/list", params)
            out.extend(r.get("tools", []))
            cursor = r.get("nextCursor")
            if not cursor:
                return out

    def call_tool(self, name: str, arguments: dict, timeout: float | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout)

    def list_resources(self) -> list[dict]:
        try:
            return self.request("resources/list", {}).get("resources", [])
        except MCPError:
            return []

    def list_prompts(self) -> list[dict]:
        try:
            return self.request("prompts/list", {}).get("prompts", [])
        except MCPError:
            return []

    @property
    def info(self) -> dict:
        return {"server": self._server_info, "capabilities": self._capabilities}


# -------------------------------------------------------------------- adapters
_ALLOWED_KEYS = {"type", "properties", "required", "items", "enum", "description",
                 "additionalProperties", "anyOf", "oneOf", "default", "minimum",
                 "maximum", "minItems", "maxItems", "format"}


def _resolve_ref(ref: str, root: dict) -> dict | None:
    """Resolve a local JSON pointer such as #/$defs/Vec3."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def sanitize_schema(node: Any, root: dict | None = None, depth: int = 0) -> Any:
    """Flatten a JSON Schema into what gpt-oss renders reliably.

    Resolves local $ref/$defs (pydantic-generated MCP schemas are full of them),
    collapses anyOf/oneOf unions to their first concrete branch, merges allOf, and
    drops keywords the harmony tool renderer ignores. An unresolved $ref silently
    turns an array parameter into an object, which corrupts arguments, so resolution
    matters more than it looks.
    """
    if not isinstance(node, dict):
        return node
    if root is None:
        root = node
    if depth > 8:
        return {"type": "string", "description": node.get("description", "Nested value")}

    if "$ref" in node:
        target = _resolve_ref(node["$ref"], root)
        if target is None:
            return {"type": "object", "properties": {},
                    "description": node.get("description", "Nested object")}
        merged = dict(target)
        if node.get("description"):
            merged["description"] = node["description"]
        return sanitize_schema(merged, root, depth + 1)

    if "allOf" in node and isinstance(node["allOf"], list):
        combined: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for branch in node["allOf"]:
            b = sanitize_schema(branch, root, depth + 1)
            if isinstance(b, dict):
                combined["properties"].update(b.get("properties") or {})
                combined["required"].extend(b.get("required") or [])
        if node.get("description"):
            combined["description"] = node["description"]
        combined["required"] = sorted(set(combined["required"]))
        return combined

    for union in ("anyOf", "oneOf"):
        if isinstance(node.get(union), list):
            concrete = [b for b in node[union]
                        if isinstance(b, dict) and b.get("type") != "null"]
            if concrete:
                merged = sanitize_schema(concrete[0], root, depth + 1)
                if isinstance(merged, dict) and node.get("description"):
                    merged.setdefault("description", node["description"])
                return merged

    out: dict[str, Any] = {}
    for k, v in node.items():
        if k not in _ALLOWED_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: sanitize_schema(pv, root, depth + 1) for pk, pv in v.items()}
        elif k == "items":
            out[k] = sanitize_schema(v, root, depth + 1)
        else:
            out[k] = v
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


def to_ollama_tools(mcp_tools: list[dict], *, prefix: str = "",
                    max_desc: int = 320) -> list[dict]:
    """Convert MCP tool definitions into Ollama / OpenAI function schemas."""
    out = []
    for t in mcp_tools:
        schema = sanitize_schema(t.get("inputSchema") or {"type": "object", "properties": {}})
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        desc = (t.get("description") or "").strip().replace("\n", " ")
        if len(desc) > max_desc:
            desc = desc[:max_desc - 3] + "..."
        out.append({"type": "function", "function": {
            "name": prefix + t["name"], "description": desc, "parameters": schema}})
    return out


def content_to_text(result: dict, max_chars: int = 100000) -> str:
    """Flatten an MCP tools/call result into text for the model."""
    if result.get("structuredContent") is not None:
        return json.dumps(result["structuredContent"], ensure_ascii=False)[:max_chars]
    parts = []
    for c in result.get("content", []) or []:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "image":
            parts.append("[image %s, %d bytes base64]" %
                         (c.get("mimeType", "?"), len(c.get("data", ""))))
        elif c.get("type") == "resource":
            r = c.get("resource", {})
            parts.append(r.get("text") or ("[resource " + str(r.get("uri", "")) + "]"))
        else:
            parts.append(json.dumps(c, ensure_ascii=False))
    text = "\n".join(parts)[:max_chars]
    if result.get("isError"):
        return "TOOL ERROR: " + text
    return text


class MCPPool:
    """Several MCP servers behind one dispatch function, with name prefixing."""

    def __init__(self):
        self.servers: dict[str, MCPServer] = {}
        self.route: dict[str, tuple[MCPServer, str]] = {}
        self.tools: list[dict] = []

    def add(self, key: str, server: MCPServer, *, prefix: bool = True) -> list[dict]:
        server.start()
        self.servers[key] = server
        pre = (key + "_") if prefix else ""
        raw = server.list_tools()
        conv = to_ollama_tools(raw, prefix=pre)
        for t, r in zip(conv, raw):
            self.route[t["function"]["name"]] = (server, r["name"])
        self.tools.extend(conv)
        return conv

    def dispatch(self, name: str, args: dict) -> Any:
        hit = self.route.get(name)
        if hit is None:
            return {"error": "unknown tool " + repr(name),
                    "available_prefixes": sorted({k for k in self.servers})}
        server, real = hit
        try:
            res = server.call_tool(real, args)
        except MCPError as e:
            return {"error": "mcp call failed: " + str(e)}
        return content_to_text(res)

    def stop_all(self) -> None:
        for s in self.servers.values():
            s.stop()
