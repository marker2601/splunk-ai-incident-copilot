# Splunk AI Incident Copilot Demo Script

This demo uses AI-generated narration.

Splunk AI Incident Copilot is an observability demo for the Splunk Agentic Ops Hackathon.
It uses Splunk MCP Server to investigate a production incident and OpenAI to summarize the evidence.

In this demo, we select the checkout API incident and run an investigation.
The backend calls Splunk MCP tools to run SPL across alerts, logs, deployment events, metrics, and service error trends.

The evidence is collected from the `ops_copilot` index.
It is not hardcoded in the report; the app uses Splunk results to ground the analysis.

The generated report identifies checkout API version 2.7.1 as the likely root cause.
It connects the deployment to PAYMENT_TIMEOUT and CACHE_STALE_WRITE errors, then recommends immediate mitigation.

The evidence cards show the exact SPL and results used by the copilot.
An incident commander can verify alert timing, trace IDs, latency, and service-level blast radius.

The MCP integration matters because the application is not scraping screenshots or relying on static sample text.
It is calling Splunk MCP tools, receiving structured search results, and preserving the SPL that produced each conclusion.

For a hackathon judge, the workflow is reproducible: load the dataset, open the app, run the checkout investigation, and verify the same Splunk-backed evidence.
The fallback path also keeps the app usable if an external service is temporarily unavailable.

The result is faster triage: a timeline, root-cause hypothesis, Splunk evidence, and next actions in one workflow.
