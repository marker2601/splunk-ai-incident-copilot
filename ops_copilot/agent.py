from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from .config import Config
from .mcp_client import SplunkMCPClient
from .splunk_client import SplunkClient


@dataclass(frozen=True)
class SearchSpec:
    title: str
    spl: str
    count: int = 25


def _splunk_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class IncidentTriageAgent:
    def __init__(self, config: Config, splunk: SplunkClient) -> None:
        self.config = config
        self.splunk = splunk
        self.mcp = None
        if config.splunk_mcp_url and config.splunk_mcp_authorization:
            self.mcp = SplunkMCPClient(
                config.splunk_mcp_url,
                config.splunk_mcp_authorization,
                config.splunk_verify_ssl,
            )

    def scenarios(self) -> list[dict[str, str]]:
        return [
            {
                "id": "checkout-api",
                "service": "checkout-api",
                "title": "Checkout API error surge",
                "description": "HTTP 500s and payment timeouts after a checkout deployment.",
            },
            {
                "id": "payments-api",
                "service": "payments-api",
                "title": "Payments dependency pressure",
                "description": "Investigate elevated latency and upstream timeout contribution.",
            },
            {
                "id": "inventory-api",
                "service": "inventory-api",
                "title": "Inventory baseline check",
                "description": "Compare a healthy service against the active incident.",
            },
        ]

    def build_searches(self, service: str) -> list[SearchSpec]:
        index = _splunk_quote(self.config.splunk_index)
        dataset = _splunk_quote(self.config.splunk_dataset_id)
        service_value = _splunk_quote(service)
        base = f'search index="{index}" dataset_id="{dataset}" | dedup event_uid'
        service_filter = f'| search service="{service_value}"'
        return [
            SearchSpec(
                "Active alerts",
                f'{base} | search event_type="alert" | sort 0 - event_time '
                "| table event_time service severity alert_name message runbook_url",
                20,
            ),
            SearchSpec(
                "Recent service events",
                f"{base} {service_filter} | sort 0 - event_time "
                "| table event_time event_type service level message status_code latency_ms error_code version trace_id | head 40",
                40,
            ),
            SearchSpec(
                "Top error signatures",
                f'{base} {service_filter} | search event_type="log" level="ERROR" '
                "| stats count as occurrences values(status_code) as status_codes values(trace_id) as trace_ids by error_code message "
                "| sort - occurrences",
                20,
            ),
            SearchSpec(
                "Deployment timeline",
                f'{base} | search event_type="deploy" | sort 0 - event_time '
                "| table event_time service version deployed_by message change_id",
                20,
            ),
            SearchSpec(
                "Latency by service",
                f'{base} | search event_type="metric" '
                "| stats count as samples avg(latency_ms) as avg_latency perc95(latency_ms) as p95_latency max(latency_ms) as max_latency by service "
                "| sort - p95_latency",
                20,
            ),
            SearchSpec(
                "Error trend by service",
                f'{base} | search event_type="log" level="ERROR" '
                "| stats count as errors by service error_code | sort - errors",
                20,
            ),
        ]

    def investigate(self, service: str, question: str = "", window_minutes: int = 120) -> dict[str, Any]:
        searches = self.build_searches(service)

        def run_spec(spec: SearchSpec) -> dict[str, Any]:
            try:
                if self.mcp:
                    result = self.mcp.run_query(
                        spec.spl,
                        earliest_time=f"-{window_minutes}m",
                        latest_time="now",
                        row_limit=spec.count,
                    )
                    sid = "mcp:splunk_run_query"
                    rows = result.results
                    source = "mcp"
                else:
                    rest_result = self.splunk.run_search(
                        spec.spl,
                        earliest_time=f"-{window_minutes}m",
                        latest_time="now",
                        count=spec.count,
                    )
                    sid = rest_result.sid
                    rows = rest_result.results
                    source = "rest"
                return {
                    "title": spec.title,
                    "spl": spec.spl,
                    "sid": sid,
                    "source": source,
                    "results": rows,
                    "error": "",
                }
            except Exception as exc:
                return {
                    "title": spec.title,
                    "spl": spec.spl,
                    "sid": "",
                    "source": "mcp" if self.mcp else "rest",
                    "results": [],
                    "error": str(exc),
                }

        with ThreadPoolExecutor(max_workers=min(6, len(searches))) as executor:
            evidence = list(executor.map(run_spec, searches))

        ai_note = ""
        report = ""
        ai_used = False
        if self.config.openai_api_key:
            try:
                report = self._openai_report(service, question, evidence)
                ai_used = True
            except Exception as exc:
                ai_note = f"OpenAI call failed, using local summary: {exc}"

        if not report:
            report = self._local_report(service, evidence, ai_note)

        return {
            "service": service,
            "question": question,
            "window_minutes": window_minutes,
            "ai_used": ai_used,
            "mcp_configured": bool(self.config.splunk_mcp_url),
            "mcp_used_for_evidence": bool(self.mcp) and all(item.get("source") == "mcp" for item in evidence if not item.get("error")),
            "report": report,
            "evidence": evidence,
        }

    def _openai_report(self, service: str, question: str, evidence: list[dict[str, Any]]) -> str:
        prompt = {
            "service": service,
            "operator_question": question or "Triage the active incident and produce an operations-ready report.",
            "splunk_evidence": evidence,
            "output_contract": {
                "sections": [
                    "Executive summary",
                    "Likely root cause",
                    "Timeline",
                    "Evidence from Splunk",
                    "Immediate next actions",
                    "SPL runbook",
                ],
                "rules": [
                    "Ground every claim in the supplied Splunk evidence or an MCP tool result.",
                    "Name the SPL searches that support each conclusion.",
                    "Be concise enough for an incident commander.",
                    "Do not invent infrastructure or teams that are not in the evidence.",
                ],
            },
        }
        body: dict[str, Any] = {
            "model": self.config.openai_model,
            "instructions": (
                "You are an expert SRE incident commander. Produce a practical incident triage report "
                "using Splunk evidence. Prefer concrete hypotheses, confidence levels, and next actions."
            ),
            "input": json.dumps(prompt, indent=2),
        }

        if self.config.splunk_mcp_url and self._is_public_mcp_url(self.config.splunk_mcp_url):
            mcp_tool: dict[str, Any] = {
                "type": "mcp",
                "server_label": "splunk",
                "server_description": "Splunk MCP Server for searching operational data and Splunk resources.",
                "server_url": self.config.splunk_mcp_url,
                "require_approval": "never",
            }
            if self.config.splunk_mcp_authorization:
                mcp_tool["authorization"] = self._normalize_mcp_token(self.config.splunk_mcp_authorization)
            if self.config.splunk_mcp_allowed_tools:
                mcp_tool["allowed_tools"] = self.config.splunk_mcp_allowed_tools
            body["tools"] = [mcp_tool]

        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail[:1200]}") from exc

        text = data.get("output_text")
        if text:
            return text

        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        if chunks:
            return "\n".join(chunks)
        return json.dumps(data, indent=2)[:4000]

    def _local_report(self, service: str, evidence: list[dict[str, Any]], note: str = "") -> str:
        top_errors = self._results(evidence, "Top error signatures")
        deploys = self._results(evidence, "Deployment timeline")
        alerts = self._results(evidence, "Active alerts")
        latency = self._results(evidence, "Latency by service")
        trend = self._results(evidence, "Error trend by service")

        primary_error = top_errors[0] if top_errors else {}
        related_deploys = [item for item in deploys if self._value(item, "service") == service]
        deploy = related_deploys[0] if related_deploys else {}
        service_latency = next((item for item in latency if self._value(item, "service") == service), {})
        service_trend = next((item for item in trend if self._value(item, "service") == service), {})

        alert_line = "No active alert was found in the current window."
        if alerts:
            alert = alerts[0]
            alert_line = (
                f"{self._value(alert, 'severity', 'unknown')} alert on "
                f"{self._value(alert, 'service')}: {self._value(alert, 'message')}"
            )

        root_cause = "The strongest hypothesis is an application regression in the selected service."
        if deploy:
            root_cause = (
                f"The strongest hypothesis is a regression after deployment {self._value(deploy, 'version', 'unknown')} "
                f"for {service}. The deployment appears in the same investigation window as the error surge."
            )
        if self._value(primary_error, "error_code"):
            root_cause += f" The leading error signature is {self._value(primary_error, 'error_code')}."

        note_block = f"\n\n> {note}\n" if note else ""
        return (
            f"## Executive summary\n"
            f"{alert_line} Splunk evidence shows {service} is the main service to inspect. "
            f"The current local summary is deterministic; set `OPENAI_API_KEY` to enable model-written analysis.\n"
            f"{note_block}\n"
            f"## Likely root cause\n"
            f"{root_cause}\n\n"
            f"## Timeline\n"
            f"- Latest related deploy: {self._value(deploy, 'event_time', 'not found')} "
            f"{self._value(deploy, 'version')} {self._value(deploy, 'message')}\n"
            f"- Top error: {self._value(primary_error, 'occurrences', '0')} occurrences of "
            f"{self._value(primary_error, 'error_code', 'unknown')} - {self._value(primary_error, 'message', 'not found')}\n"
            f"- Latency: avg={self._value(service_latency, 'avg_latency', 'n/a')}, "
            f"p95={self._value(service_latency, 'p95_latency', 'n/a')}, max={self._value(service_latency, 'max_latency', 'n/a')}\n\n"
            f"## Evidence from Splunk\n"
            f"- `Top error signatures` identifies the dominant failure mode and sample trace IDs.\n"
            f"- `Deployment timeline` checks whether a code or config change aligns with the alert.\n"
            f"- `Latency by service` compares blast radius across services.\n"
            f"- `Error trend by service` shows whether failures are isolated or systemic.\n\n"
            f"## Immediate next actions\n"
            f"1. Roll back or disable the latest {service} change if the error rate is still elevated.\n"
            f"2. Inspect the sample traces listed in `Top error signatures`.\n"
            f"3. Check payment dependency health before retrying the deploy.\n"
            f"4. Keep the incident open until p95 latency and 5xx counts return to baseline.\n\n"
            f"## SPL runbook\n"
            f"Use the SPL panels below to reproduce every conclusion from this report."
        )

    @staticmethod
    def _results(evidence: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
        for item in evidence:
            if item.get("title") == title:
                return item.get("results", [])
        return []

    @staticmethod
    def _value(row: dict[str, Any], key: str, default: str = "") -> str:
        value = row.get(key, default)
        if isinstance(value, list):
            if not value:
                return default
            return str(value[0])
        if value is None:
            return default
        return str(value)

    @staticmethod
    def _normalize_mcp_token(value: str) -> str:
        token = value.strip()
        if token.lower().startswith("authorization:"):
            token = token.split(":", 1)[1].strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    @staticmethod
    def _is_public_mcp_url(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host not in {"localhost", "127.0.0.1", "::1", ""}
