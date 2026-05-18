from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from .agent import IncidentTriageAgent
from .config import get_config
from .splunk_client import SplunkClient


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"


class App:
    def __init__(self) -> None:
        self.config = get_config()
        self.splunk = SplunkClient(
            self.config.splunk_base_url,
            self.config.splunk_username,
            self.config.splunk_password,
            self.config.splunk_verify_ssl,
        )
        self.agent = IncidentTriageAgent(self.config, self.splunk)


APP = App()


class Handler(BaseHTTPRequestHandler):
    server_version = "OpsCopilot/0.1"

    def log_message(self, format: str, *args: object) -> None:
        print("%s - - %s" % (self.address_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json_response(self._health())
            return
        if parsed.path == "/api/scenarios":
            self._json_response({"scenarios": APP.agent.scenarios()})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/investigate":
            body = self._read_json()
            service = str(body.get("service") or "checkout-api")
            question = str(body.get("question") or "")
            window_minutes = int(body.get("window_minutes") or 1440)
            self._json_response(APP.agent.investigate(service, question, window_minutes))
            return
        if parsed.path == "/api/search":
            body = self._read_json()
            spl = str(body.get("spl") or "")
            if not spl.strip():
                self._json_response({"error": "Missing SPL query."}, HTTPStatus.BAD_REQUEST)
                return
            result = APP.splunk.run_search(spl, count=int(body.get("count") or 50))
            self._json_response({"sid": result.sid, "results": result.results})
            return
        self._json_response({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def _health(self) -> dict[str, object]:
        try:
            splunk = APP.splunk.health()
            splunk_ok = True
            error = ""
        except Exception as exc:
            splunk = {}
            splunk_ok = False
            error = str(exc)
        return {
            "app": "ok",
            "splunk_ok": splunk_ok,
            "splunk": splunk,
            "splunk_error": error,
            "index": APP.config.splunk_index,
            "dataset_id": APP.config.splunk_dataset_id,
            "ai_mode": "openai" if APP.config.openai_api_key else "local-summary",
            "mcp_configured": bool(APP.config.splunk_mcp_url),
            "mcp_endpoint_host": APP.config.splunk_mcp_url.split("/")[2] if APP.config.splunk_mcp_url else "",
        }

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _json_response(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else url_path.lstrip("/")
        path = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in path.parents and path != WEB_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    config = APP.config
    server = ThreadingHTTPServer((config.app_host, config.app_port), Handler)
    print(f"Ops Copilot running at http://{config.app_host}:{config.app_port}")
    print(f"Splunk API: {config.splunk_base_url} index={config.splunk_index}")
    server.serve_forever()


if __name__ == "__main__":
    main()
