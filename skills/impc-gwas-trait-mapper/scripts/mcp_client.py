"""Minimal Streamable-HTTP MCP client (stdlib only).

Used by the bundled scripts to call hosted MCP servers (OLS, IMPC orthology)
when the agent's own client does not have them installed, or when a step needs
many calls (pairwise similarity) that are cheaper to run in one process.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class McpClient:
    def __init__(self, url: str, timeout: int = 120, protocol: str = "2025-03-26"):
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._id = 0
        self._post({
            "jsonrpc": "2.0", "id": self._next(), "method": "initialize",
            "params": {"protocolVersion": protocol, "capabilities": {},
                       "clientInfo": {"name": "impc-gwas-trait-mapper", "version": "0.1"}},
        })
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except urllib.error.HTTPError:
            pass  # some servers answer 202/204 or reject notifications; harmless

    def _next(self) -> int:
        self._id += 1
        return self._id

    def _post(self, body: dict) -> list[dict]:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.session_id = r.headers.get("Mcp-Session-Id") or self.session_id
            raw = r.read().decode()
        msgs = []
        for line in raw.splitlines():  # SSE framing
            if line.startswith("data:"):
                try:
                    msgs.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
        if not msgs and raw.strip():  # plain JSON framing
            msgs = [json.loads(raw)]
        return msgs

    def list_tools(self) -> list[dict]:
        msgs = self._post({"jsonrpc": "2.0", "id": self._next(), "method": "tools/list", "params": {}})
        return msgs[-1].get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict, retries: int = 2) -> str:
        """Call a tool and return its concatenated text content."""
        body = {"jsonrpc": "2.0", "id": self._next(), "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}
        for attempt in range(retries + 1):
            try:
                msgs = self._post(body)
                res = msgs[-1]
                if "error" in res:
                    raise RuntimeError(f"{name}: {res['error']}")
                out = res.get("result", {})
                text = "".join(c.get("text", "") for c in out.get("content", []) if c.get("type") == "text")
                if out.get("isError"):
                    raise RuntimeError(f"{name} isError: {text[:300]}")
                return text
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == retries:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("unreachable")

    def call_json(self, name: str, arguments: dict):
        return json.loads(self.call(name, arguments))
