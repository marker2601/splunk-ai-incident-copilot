from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import ssl
import time
from typing import Any
from urllib import error, parse, request


class SplunkError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    sid: str
    results: list[dict[str, Any]]


class SplunkClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        token = f"{username}:{password}".encode("utf-8")
        self.auth_header = "Basic " + base64.b64encode(token).decode("ascii")
        self.timeout = timeout
        self.context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | str | bytes | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        query = parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {"Authorization": self.auth_header}
        if extra_headers:
            headers.update(extra_headers)
        body: bytes | None = None
        if isinstance(data, dict):
            body = parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, str):
            body = data.encode("utf-8")
            headers["Content-Type"] = "text/plain; charset=utf-8"
        elif isinstance(data, bytes):
            body = data
            headers["Content-Type"] = "application/octet-stream"

        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.timeout, context=self.context) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise SplunkError(f"Splunk HTTP {exc.code}: {raw[:1200]}") from exc
        except error.URLError as exc:
            raise SplunkError(f"Could not reach Splunk at {self.base_url}: {exc}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def health(self) -> dict[str, Any]:
        data = self.request(
            "GET",
            "/services/server/info",
            params={"output_mode": "json"},
        )
        content = data["entry"][0]["content"]
        return {
            "version": content.get("version"),
            "build": content.get("build"),
            "health": content.get("health_info"),
            "license": content.get("activeLicenseGroup"),
            "host": content.get("host"),
        }

    def ensure_index(self, index_name: str) -> bool:
        path = f"/services/data/indexes/{parse.quote(index_name)}"
        try:
            self.request("GET", path, params={"output_mode": "json"})
            return False
        except SplunkError as exc:
            if "HTTP 404" not in str(exc):
                raise

        self.request(
            "POST",
            "/services/data/indexes",
            data={"name": index_name, "datatype": "event"},
            params={"output_mode": "json"},
        )
        return True

    def submit_event(
        self,
        index_name: str,
        event: dict[str, Any],
        sourcetype: str = "ops:json",
        host: str = "synthetic-shop",
    ) -> None:
        self.request(
            "POST",
            "/services/receivers/simple",
            data=json.dumps(event, separators=(",", ":")),
            params={"index": index_name, "sourcetype": sourcetype, "host": host},
        )

    def submit_events_stream(
        self,
        index_name: str,
        events: list[dict[str, Any]],
        sourcetype: str = "ops:json",
        host: str = "synthetic-shop",
    ) -> None:
        payload = "\n".join(json.dumps(event, separators=(",", ":")) for event in events) + "\n"
        self.request(
            "POST",
            "/services/receivers/stream",
            data=payload,
            params={"index": index_name, "sourcetype": sourcetype, "host": host},
            extra_headers={"x-splunk-input-mode": "streaming"},
        )

    def run_search(
        self,
        spl: str,
        earliest_time: str = "-24h",
        latest_time: str = "now",
        count: int = 100,
        timeout_seconds: int = 30,
    ) -> SearchResult:
        search = spl.strip()
        if not search.startswith("search ") and not search.startswith("|"):
            search = "search " + search

        created = self.request(
            "POST",
            "/services/search/jobs",
            data={
                "search": search,
                "earliest_time": earliest_time,
                "latest_time": latest_time,
                "exec_mode": "normal",
                "output_mode": "json",
            },
            params={"output_mode": "json"},
        )
        sid = created.get("sid")
        if not sid:
            raise SplunkError(f"Search did not return a SID: {created}")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            job = self.request(
                "GET",
                f"/services/search/jobs/{parse.quote(sid)}",
                params={"output_mode": "json"},
            )
            content = job["entry"][0]["content"]
            if str(content.get("isDone", "0")).lower() in {"1", "true"}:
                break
            time.sleep(0.35)
        else:
            raise SplunkError(f"Search timed out after {timeout_seconds}s: {sid}")

        results = self.request(
            "GET",
            f"/services/search/jobs/{parse.quote(sid)}/results",
            params={"output_mode": "json", "count": count},
        )
        return SearchResult(sid=sid, results=results.get("results", []))
