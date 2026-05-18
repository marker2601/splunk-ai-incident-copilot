# Splunk AI Incident Copilot

AI Incident Copilot is a hackathon-ready observability app for the Splunk Agentic Ops Hackathon. It triages an active production incident by running SPL searches, assembling an evidence pack, and generating an incident commander report.

The default scenario simulates a checkout API regression after deployment `2.7.1`. The app shows the problem, the evidence, the SPL used, and the recommended operational response.

## Track

Observability

## Features

- Synthetic production incident dataset for a reliable demo.
- Splunk REST integration for alerts, logs, deployments, and latency evidence.
- Browser UI for running an investigation and reviewing SPL-backed evidence.
- Optional OpenAI Responses API summary.
- Optional Splunk MCP Server integration. For local demos, the backend calls the local MCP server and sends MCP-backed evidence to the AI model.
- Root-level architecture diagram in `ARCHITECTURE.md`.

## Project Structure

```text
ops_copilot/              Python backend and agent logic
scripts/load_sample_data.py
web/                      Static browser UI
ARCHITECTURE.md           Required architecture diagram
.env.example              Local configuration template
```

## Requirements

- Python 3.11 or newer.
- Splunk Enterprise running locally or remotely.
- A Splunk admin or service account that can create indexes, submit events, and run searches.
- Optional: OpenAI API key.
- Optional: Splunk MCP Server app installed and configured.

## Setup

Copy `.env.example` to `.env` and update values as needed.

For the local Windows Splunk trial used during development:

```text
SPLUNK_BASE_URL=https://localhost:8089
SPLUNK_USERNAME=admin
SPLUNK_PASSWORD=<your-splunk-password>
SPLUNK_VERIFY_SSL=false
SPLUNK_INDEX=ops_copilot
SPLUNK_DATASET_ID=demo-v1
```

Load sample data:

```powershell
python scripts/load_sample_data.py
```

Run the app:

```powershell
python -m ops_copilot.server
```

Open:

```text
http://127.0.0.1:5173
```

## AI Configuration

The app works without an API key by returning a deterministic local incident report. For the hackathon demo, set:

```text
OPENAI_API_KEY=<your key>
OPENAI_MODEL=gpt-5.5
```

The implementation uses the OpenAI Responses API. OpenAI docs for Responses and MCP tools:

- https://developers.openai.com/api/reference/responses/overview
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp

## Optional Splunk MCP Server

Install and configure the Splunk MCP Server app if your Splunk environment supports it. Splunk's setup guide describes the app install, token authentication, and role capabilities:

- https://help.splunk.com/en/splunk-enterprise/mcp-server-for-splunk-platform/1.0/configure-the-splunk-mcp-server
- https://help.splunk.com/en/splunk-enterprise/mcp-server-for-splunk-platform/1.0/connecting-to-the-mcp-server-and-settings

Then configure:

```text
SPLUNK_MCP_URL=<your Splunk MCP endpoint>
SPLUNK_MCP_AUTHORIZATION=<oauth or bearer token if required>
SPLUNK_MCP_ALLOWED_TOOLS=
```

When `SPLUNK_MCP_URL` and `SPLUNK_MCP_AUTHORIZATION` are present, the backend uses Splunk MCP Server's `splunk_run_query` tool for evidence collection. REST remains the fallback.

If the MCP endpoint is publicly reachable, the app can also expose it as a remote MCP tool to OpenAI. For local Splunk installs using `localhost`, OpenAI cannot reach the endpoint directly, so the backend performs the MCP calls locally and then sends the evidence pack to the model.

## Demo Script

1. Show Splunk running and the `ops_copilot` index.
2. Open the web app.
3. Select `Checkout API error surge`.
4. Run the investigation.
5. Show the incident report.
6. Expand the SPL evidence cards and point out:
   - active alert,
   - checkout deployment,
   - top `PAYMENT_TIMEOUT` errors,
   - checkout p95 latency,
   - service-level blast radius.
7. Explain how AI turns the Splunk evidence into an incident commander report.

## Submission Checklist

- Public open-source repository.
- Open-source license.
- `README.md` with setup and run instructions.
- `ARCHITECTURE.md` in the repository root.
- Demo video under 3 minutes.
- No copyrighted music or third-party trademarks in the video.
