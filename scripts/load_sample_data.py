from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops_copilot.config import get_config
from ops_copilot.splunk_client import SplunkClient


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_events(dataset_id: str = "demo-v1") -> list[dict[str, object]]:
    random.seed(42)
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=90)
    services = ["checkout-api", "payments-api", "inventory-api", "auth-service"]
    hosts = {
        "checkout-api": ["checkout-1", "checkout-2", "checkout-3"],
        "payments-api": ["payments-1", "payments-2"],
        "inventory-api": ["inventory-1", "inventory-2"],
        "auth-service": ["auth-1", "auth-2"],
    }
    versions = {
        "checkout-api": "2.7.0",
        "payments-api": "4.2.2",
        "inventory-api": "1.18.4",
        "auth-service": "3.4.1",
    }
    events: list[dict[str, object]] = []

    deploy_time = now - timedelta(minutes=38)
    events.append(
        {
            "event_time": iso(deploy_time),
            "event_type": "deploy",
            "service": "checkout-api",
            "version": "2.7.1",
            "deployed_by": "ci-bot",
            "change_id": "CHG-10492",
            "message": "Enabled new payment retry policy and checkout response cache.",
            "env": "prod",
        }
    )

    for minute in range(90):
        current = start + timedelta(minutes=minute)
        for service in services:
            in_incident = service == "checkout-api" and current >= deploy_time + timedelta(minutes=3)
            base_latency = {
                "checkout-api": 130,
                "payments-api": 180,
                "inventory-api": 70,
                "auth-service": 55,
            }[service]
            if in_incident:
                latency = int(random.gauss(780, 180))
            elif service == "payments-api" and current >= deploy_time:
                latency = int(random.gauss(260, 80))
            else:
                latency = int(random.gauss(base_latency, 22))
            latency = max(latency, 20)

            events.append(
                {
                    "event_time": iso(current),
                    "event_type": "metric",
                    "service": service,
                    "latency_ms": latency,
                    "env": "prod",
                    "host": random.choice(hosts[service]),
                    "version": versions[service],
                }
            )

            normal_count = 1 if service != "checkout-api" else 2
            for _ in range(normal_count):
                events.append(
                    {
                        "event_time": iso(current + timedelta(seconds=random.randint(0, 55))),
                        "event_type": "log",
                        "service": service,
                        "level": "INFO",
                        "message": "request completed",
                        "status_code": 200,
                        "latency_ms": latency,
                        "trace_id": f"tr-{service[:3]}-{minute:02d}-{random.randint(1000,9999)}",
                        "host": random.choice(hosts[service]),
                        "version": "2.7.1" if service == "checkout-api" and current >= deploy_time else versions[service],
                        "env": "prod",
                    }
                )

            if in_incident:
                for burst in range(random.randint(2, 5)):
                    code = random.choice(["PAYMENT_TIMEOUT", "CACHE_STALE_WRITE", "PAYMENT_TIMEOUT"])
                    events.append(
                        {
                            "event_time": iso(current + timedelta(seconds=8 + burst * 7)),
                            "event_type": "log",
                            "service": "checkout-api",
                            "level": "ERROR",
                            "message": (
                                "checkout failed while waiting for payment authorization"
                                if code == "PAYMENT_TIMEOUT"
                                else "checkout cache returned stale cart state"
                            ),
                            "error_code": code,
                            "status_code": 500,
                            "latency_ms": latency + random.randint(150, 500),
                            "trace_id": f"tr-cho-{minute:02d}-{burst}-{random.randint(1000,9999)}",
                            "host": random.choice(hosts["checkout-api"]),
                            "version": "2.7.1",
                            "env": "prod",
                        }
                    )

    events.append(
        {
            "event_time": iso(now - timedelta(minutes=22)),
            "event_type": "alert",
            "service": "checkout-api",
            "severity": "critical",
            "alert_name": "Checkout 5xx rate above threshold",
            "message": "Checkout API 5xx rate exceeded 8 percent for 10 minutes after deployment 2.7.1.",
            "runbook_url": "https://example.invalid/runbooks/checkout-api-5xx",
            "env": "prod",
        }
    )
    events.append(
        {
            "event_time": iso(now - timedelta(minutes=18)),
            "event_type": "alert",
            "service": "checkout-api",
            "severity": "warning",
            "alert_name": "Checkout p95 latency high",
            "message": "Checkout API p95 latency exceeded 900 ms.",
            "runbook_url": "https://example.invalid/runbooks/checkout-latency",
            "env": "prod",
        }
    )
    for index, event in enumerate(events, start=1):
        event["dataset_id"] = dataset_id
        event["event_uid"] = f"{dataset_id}-{index:04d}"
    return events


def main() -> None:
    config = get_config()
    splunk = SplunkClient(
        config.splunk_base_url,
        config.splunk_username,
        config.splunk_password,
        config.splunk_verify_ssl,
    )
    created = splunk.ensure_index(config.splunk_index)
    if created:
        print(f"Created Splunk index {config.splunk_index}; waiting for it to become searchable...")
        time.sleep(4)

    events = build_events(config.splunk_dataset_id)
    splunk.submit_events_stream(config.splunk_index, events)
    print(f"Loaded {len(events)} synthetic observability events into index={config.splunk_index}")


if __name__ == "__main__":
    main()
