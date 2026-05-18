from __future__ import annotations

from dataclasses import dataclass
import json
import ssl
from typing import Any
from urllib import error, request


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPQueryResult:
    results: list[dict[str, Any]]
    total_rows: int
    truncated: bool


class SplunkMCPClient:
    def __init__(self, server_url: str, authorization: str, verify_ssl: bool = False, timeout: int = 60) -> None:
        self.server_url = server_url
        self.authorization = self._normalize_token(authorization)
        self.timeout = timeout
        self.context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "splunk-ai-incident-copilot", "version": "0.1"},
            },
        )
        self._initialized = True
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        return result.get("tools", [])

    def run_query(
        self,
        query: str,
        earliest_time: str = "-24h",
        latest_time: str = "now",
        row_limit: int = 100,
    ) -> MCPQueryResult:
        self._ensure_initialized()
        result = self._rpc(
            "tools/call",
            {
                "name": "splunk_run_query",
                "arguments": {
                    "query": query,
                    "earliest_time": earliest_time,
                    "latest_time": latest_time,
                    "row_limit": row_limit,
                },
            },
        )
        payload = result.get("structuredContent")
        if not payload:
            payload = self._payload_from_text(result)
        return MCPQueryResult(
            results=payload.get("results", []),
            total_rows=int(payload.get("total_rows", len(payload.get("results", [])))),
            truncated=bool(payload.get("truncated", False)),
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        req = request.Request(
            self.server_url,
            data=body,
            method="POST",
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with request.urlopen(req, context=self.context, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPError(f"MCP HTTP {exc.code}: {detail[:1200]}") from exc
        except error.URLError as exc:
            raise MCPError(f"Could not reach Splunk MCP Server at {self.server_url}: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP returned non-JSON response: {raw[:1200]}") from exc
        if payload.get("error"):
            raise MCPError(f"MCP error: {payload['error']}")
        return payload.get("result", {})

    @staticmethod
    def _payload_from_text(result: dict[str, Any]) -> dict[str, Any]:
        for item in result.get("content", []):
            if item.get("type") == "text" and item.get("text"):
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    continue
        return {"results": [], "total_rows": 0, "truncated": False}

    @staticmethod
    def _normalize_token(value: str) -> str:
        token = value.strip()
        if token.lower().startswith("authorization:"):
            token = token.split(":", 1)[1].strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

