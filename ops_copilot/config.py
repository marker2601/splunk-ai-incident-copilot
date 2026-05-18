from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    splunk_base_url: str
    splunk_username: str
    splunk_password: str
    splunk_verify_ssl: bool
    splunk_index: str
    splunk_dataset_id: str
    openai_api_key: str
    openai_model: str
    splunk_mcp_url: str
    splunk_mcp_authorization: str
    splunk_mcp_allowed_tools: list[str]
    app_host: str
    app_port: int


def get_config() -> Config:
    _load_env_file()
    allowed_tools = [
        item.strip()
        for item in os.environ.get("SPLUNK_MCP_ALLOWED_TOOLS", "").split(",")
        if item.strip()
    ]
    return Config(
        splunk_base_url=os.environ.get("SPLUNK_BASE_URL", "https://localhost:8089"),
        splunk_username=os.environ.get("SPLUNK_USERNAME", "admin"),
        splunk_password=os.environ.get("SPLUNK_PASSWORD", ""),
        splunk_verify_ssl=_bool_env("SPLUNK_VERIFY_SSL", False),
        splunk_index=os.environ.get("SPLUNK_INDEX", "ops_copilot"),
        splunk_dataset_id=os.environ.get("SPLUNK_DATASET_ID", "demo-v1"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
        splunk_mcp_url=os.environ.get("SPLUNK_MCP_URL", ""),
        splunk_mcp_authorization=os.environ.get("SPLUNK_MCP_AUTHORIZATION", ""),
        splunk_mcp_allowed_tools=allowed_tools,
        app_host=os.environ.get("APP_HOST", "127.0.0.1"),
        app_port=int(os.environ.get("APP_PORT", "5173")),
    )
