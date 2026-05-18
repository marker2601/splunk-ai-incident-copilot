from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib import error, request
import wave

import imageio_ffmpeg
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo" / "output"
APP_URL = "http://127.0.0.1:5173"
FINAL_MP4 = OUT / "splunk_ai_incident_copilot_demo.mp4"
RAW_WEBM = OUT / "splunk_ai_incident_copilot_demo.webm"
NARRATION_TXT = OUT / "narration.txt"
NARRATION_WAV = OUT / "narration.wav"
NARRATION_SRT = OUT / "narration.srt"
NARRATION_SOURCE = OUT / "narration_source.txt"
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"

NARRATION = """This demo uses AI-generated narration.

Splunk AI Incident Copilot is an observability demo for the Splunk Agentic Ops Hackathon.
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

OPENAI_TTS_INSTRUCTIONS = (
    "Speak like a calm senior product engineer presenting a polished hackathon demo. "
    "Use natural pacing, clear articulation, measured energy, and short pauses between ideas. "
    "Avoid a sales voice. Sound confident, technical, and human."
)


def check_app() -> None:
    with request.urlopen(f"{APP_URL}/api/health", timeout=15) as response:
        health = json.loads(response.read().decode("utf-8"))
    if not health.get("splunk_ok"):
        raise RuntimeError(f"Splunk health check failed: {health}")


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_narration() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    NARRATION_TXT.write_text(NARRATION, encoding="utf-8")
    load_env()
    if os.environ.get("OPENAI_API_KEY"):
        try:
            write_openai_narration()
            write_srt(audio_duration_seconds(NARRATION_WAV))
            return
        except (OSError, TimeoutError, error.URLError, error.HTTPError) as exc:
            NARRATION_SOURCE.write_text(f"fallback:windows-system-speech:{type(exc).__name__}", encoding="utf-8")
    write_windows_narration()
    write_srt(audio_duration_seconds(NARRATION_WAV))


def write_openai_narration() -> None:
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.environ.get("OPENAI_TTS_VOICE", "cedar")
    payload = json.dumps(
        {
            "model": model,
            "voice": voice,
            "input": NARRATION,
            "instructions": OPENAI_TTS_INSTRUCTIONS,
            "response_format": "wav",
        }
    ).encode("utf-8")
    api_request = request.Request(
        OPENAI_SPEECH_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(api_request, timeout=180) as response:
        NARRATION_WAV.write_bytes(response.read())
    NARRATION_SOURCE.write_text(f"openai:{model}:{voice}", encoding="utf-8")


def write_windows_narration() -> None:
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


def audio_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / float(audio.getframerate())
            if 0 < duration < 600:
                return duration
    except wave.Error:
        pass
    return media_duration_seconds(path)


def media_duration_seconds(path: Path) -> float:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not read media duration for {path}")
    hours, minutes, seconds = match.groups()
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


def write_srt(duration_seconds: float) -> None:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", NARRATION.replace("\n", " "))
        if sentence.strip()
    ]
    total_words = sum(len(sentence.split()) for sentence in sentences) or 1
    cursor = 0.0
    cues = []
    for index, sentence in enumerate(sentences, start=1):
        share = len(sentence.split()) / total_words
        cue_duration = max(2.25, duration_seconds * share)
        end = duration_seconds if index == len(sentences) else min(duration_seconds, cursor + cue_duration)
        cues.append(f"{index}\n{srt_time(cursor)} --> {srt_time(end)}\n{wrap_caption(sentence)}\n")
        cursor = end
    NARRATION_SRT.write_text("\n".join(cues), encoding="utf-8")


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def wrap_caption(text: str, width: int = 54) -> str:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        next_line = f"{current} {word}".strip()
        if current and len(next_line) > width:
            lines.append(current)
            current = word
        else:
            current = next_line
    if current:
        lines.append(current)
    return "\n".join(lines)


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

        time.sleep(5)

        page.locator("#serviceInput").fill("checkout-api")
        page.locator("#windowInput").select_option("1440")
        time.sleep(3)

        page.locator("#runButton").click()
        time.sleep(3)

        page.wait_for_function(
            "() => document.getElementById('runButton') && !document.getElementById('runButton').disabled",
            timeout=150000,
        )

        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(10)

        page.evaluate("window.scrollTo({top: 360, behavior: 'smooth'})")
        time.sleep(10)

        page.evaluate("window.scrollTo({top: 760, behavior: 'smooth'})")
        time.sleep(10)

        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(8)

        video = page.video
        context.close()
        browser.close()
        raw_path = Path(video.path())

    target_path = RAW_WEBM
    if target_path.exists():
        try:
            target_path.unlink()
        except PermissionError:
            target_path = OUT / f"splunk_ai_incident_copilot_demo_{int(time.time())}.webm"
    shutil.move(str(raw_path), target_path)
    return target_path


def convert_to_mp4(raw_webm: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    audio_duration = audio_duration_seconds(NARRATION_WAV)
    video_duration = media_duration_seconds(raw_webm)
    if audio_duration > video_duration:
        media_filter = f"[0:v]tpad=stop_mode=clone:stop_duration={audio_duration - video_duration + 0.75:.2f}[v]"
        video_map = "[v]"
        audio_map = "1:a:0"
    elif video_duration > audio_duration:
        media_filter = "[1:a]apad[a]"
        video_map = "0:v:0"
        audio_map = "[a]"
    else:
        media_filter = None
        video_map = "0:v:0"
        audio_map = "1:a:0"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(raw_webm),
        "-i",
        str(NARRATION_WAV),
    ]
    if media_filter:
        command.extend(["-filter_complex", media_filter])
    command.extend([
        "-map",
        video_map,
        "-map",
        audio_map,
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
    ])
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
    print(f"Narration source {NARRATION_SOURCE.read_text(encoding='utf-8').strip()}")
    print(f"Optional subtitles {NARRATION_SRT}")


if __name__ == "__main__":
    main()
