from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from urllib import request

import imageio_ffmpeg
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo" / "output"
APP_URL = "http://127.0.0.1:5173"
FINAL_MP4 = OUT / "splunk_ai_incident_copilot_demo.mp4"
RAW_WEBM = OUT / "splunk_ai_incident_copilot_demo.webm"
NARRATION_TXT = OUT / "narration.txt"
NARRATION_WAV = OUT / "narration.wav"

NARRATION = """Splunk AI Incident Copilot is an observability demo for the Splunk Agentic Ops Hackathon.
It uses Splunk MCP Server to investigate a production incident and OpenAI to summarize the evidence.

In this demo, we select the checkout API incident and run an investigation.
The backend calls Splunk MCP tools to run SPL across alerts, logs, deployment events, metrics, and service error trends.

The evidence is collected from the ops copilot index.
It is not hardcoded in the report; the app uses Splunk results to ground the analysis.

The generated report identifies checkout API version 2.7.1 as the likely root cause.
It connects the deployment to PAYMENT TIMEOUT and CACHE STALE WRITE errors, then recommends immediate mitigation.

The evidence cards show the exact SPL and results used by the copilot.
An incident commander can verify alert timing, trace IDs, latency, and service level blast radius.

The MCP integration matters because the application is not scraping screenshots or relying on static sample text.
It is calling Splunk MCP tools, receiving structured search results, and preserving the SPL that produced each conclusion.

For a hackathon judge, the workflow is reproducible: load the dataset, open the app, run the checkout investigation, and verify the same Splunk backed evidence.
The fallback path also keeps the app usable if an external service is temporarily unavailable.

The result is faster triage: a timeline, root cause hypothesis, Splunk evidence, and next actions in one workflow.
"""


def check_app() -> None:
    with request.urlopen(f"{APP_URL}/api/health", timeout=15) as response:
        health = json.loads(response.read().decode("utf-8"))
    if not health.get("splunk_ok"):
        raise RuntimeError(f"Splunk health check failed: {health}")


def write_narration() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    NARRATION_TXT.write_text(NARRATION, encoding="utf-8")
    ps = f"""
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = 1
$speaker.Volume = 95
$speaker.SetOutputToWaveFile('{str(NARRATION_WAV)}')
$text = Get-Content -Raw -Path '{str(NARRATION_TXT)}'
$speaker.Speak($text)
$speaker.Dispose()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        cwd=ROOT,
    )


def set_caption(page, text: str) -> None:
    page.evaluate(
        """text => {
            const el = document.getElementById('demoCaption');
            if (el) el.textContent = text;
        }""",
        text,
    )


def install_caption_overlay(page) -> None:
    page.add_style_tag(
        content="""
        #demoCaption {
          position: fixed;
          left: 28px;
          right: 28px;
          bottom: 24px;
          z-index: 999999;
          padding: 16px 20px;
          border-radius: 8px;
          background: rgba(12, 22, 18, 0.92);
          color: #ffffff;
          font: 700 24px/1.35 Inter, Arial, sans-serif;
          box-shadow: 0 16px 50px rgba(0,0,0,0.28);
          border: 1px solid rgba(255,255,255,0.16);
        }
        """
    )
    page.evaluate(
        """() => {
            if (!document.getElementById('demoCaption')) {
              const el = document.createElement('div');
              el.id = 'demoCaption';
              document.body.appendChild(el);
            }
        }"""
    )


def record_browser_demo() -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 900},
            record_video_dir=str(OUT),
            record_video_size={"width": 1600, "height": 900},
        )
        page = context.new_page()
        page.goto(APP_URL, wait_until="networkidle")
        page.wait_for_selector("#runButton", timeout=15000)
        install_caption_overlay(page)

        set_caption(page, "Splunk AI Incident Copilot: AI triage grounded in Splunk evidence")
        time.sleep(4)

        page.locator("#serviceInput").fill("checkout-api")
        page.locator("#windowInput").select_option("1440")
        set_caption(page, "Select the checkout API incident and keep the reliable Last 24 hours window")
        time.sleep(4)

        set_caption(page, "Run investigation: the backend calls Splunk MCP Server and executes SPL searches")
        page.locator("#runButton").click()
        time.sleep(4)

        set_caption(page, "Collecting alerts, logs, deploy events, latency metrics, and error trends from Splunk MCP")
        page.wait_for_function(
            "() => document.getElementById('runButton') && !document.getElementById('runButton').disabled",
            timeout=150000,
        )

        set_caption(page, "OpenAI turns the Splunk evidence pack into an incident commander report")
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(8)

        set_caption(page, "The report identifies checkout-api 2.7.1 and PAYMENT_TIMEOUT as the likely root cause")
        page.evaluate("window.scrollTo({top: 360, behavior: 'smooth'})")
        time.sleep(8)

        set_caption(page, "Evidence cards show the exact SPL and returned Splunk rows behind every conclusion")
        page.evaluate("window.scrollTo({top: 760, behavior: 'smooth'})")
        time.sleep(8)

        set_caption(page, "Result: faster triage with a timeline, hypothesis, evidence, and next actions")
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(12)

        video = page.video
        context.close()
        browser.close()
        raw_path = Path(video.path())

    if RAW_WEBM.exists():
        RAW_WEBM.unlink()
    shutil.move(str(raw_path), RAW_WEBM)
    return RAW_WEBM


def convert_to_mp4(raw_webm: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(raw_webm),
        "-i",
        str(NARRATION_WAV),
        "-filter_complex",
        "[1:a]apad[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(FINAL_MP4),
    ]
    try:
        subprocess.run(command, check=True, cwd=ROOT)
    except subprocess.CalledProcessError:
        fallback = command.copy()
        fallback[fallback.index("libx264")] = "mpeg4"
        subprocess.run(fallback, check=True, cwd=ROOT)


def main() -> None:
    check_app()
    write_narration()
    raw_webm = record_browser_demo()
    convert_to_mp4(raw_webm)
    print(f"Created {FINAL_MP4}")
    print(f"Raw browser recording {RAW_WEBM}")


if __name__ == "__main__":
    main()
