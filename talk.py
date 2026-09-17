"""Hold a spoken kitchen conversation with pulled, one real turn at a time.

Nothing on the assistant side is scripted. For each line the person says:

    1. a neural voice speaks it to a WAV file
    2. Whisper transcribes that audio, and only the transcript goes on
    3. Claude receives the transcript, decides by itself which pulled tool to
       call over MCP (stdio), and answers
    4. the answer is spoken by a second voice

Claude keeps one session across turns, so a follow-up such as a flavour name
lands on the question the server asked a turn earlier.

    python talk.py                    run and write take/transcript.json

Needs `edge-tts`, `faster-whisper`, ffmpeg on the path and the `claude` command
line client, and none of it is a dependency of the server. Two of those reach
the network. edge-tts sends every line to Microsoft's online speech service,
and the client talks to its model provider. The recall feeds are the only other
traffic.

The client starts in a fresh temporary directory holding only its MCP config,
with no settings, project instructions or memory loaded and its built-in tools
switched off, so it can reach nothing but the three pulled tools. It still
receives whatever context the logged-in account adds, and it keeps its own
session log of each take in its projects folder.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
from faster_whisper import WhisperModel

HERE = Path(__file__).resolve().parent
TAKE = HERE / "take"

PERSON_VOICE = "en-US-AvaNeural"
ASSISTANT_VOICE = "en-US-AndrewNeural"

LINES = [
    "Hey, just so you know, my son is allergic to peanuts and my wife can't have milk.",
    "I'm holding a bag of dark chocolate coconut almond bites. Is it safe?",
    "What about this tub of Loard's ice cream?",
    "It says peanut butter fudge.",
    "And these cheddar crackers from the corner shop?",
]

VOICE_RULES = (
    "You are the voice of a kitchen assistant, and everything you write is read "
    "aloud by a speech engine to someone standing at the counter with the food in "
    "their hand. Use the pulled tools for anything about recalls or allergies, "
    "never your own memory. Answer in at most three short spoken sentences. No "
    "lists, no markdown, no symbols, no dashes, no lot code strings. If a tool "
    "hands you a question for the person, ask exactly that question and stop."
)

TOOLS = "mcp__pulled__check_item mcp__pulled__recent_recalls mcp__pulled__set_allergens"
CLIENT = shutil.which("claude")


async def speak(text: str, voice: str, path: Path) -> None:
    mp3 = path.with_suffix(".mp3")
    await edge_tts.Communicate(text, voice).save(str(mp3))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                    "-ar", "16000", "-ac", "1", str(path)], check=True)
    mp3.unlink()


def server_config(household: Path) -> Path:
    """An MCP config that starts this checkout of pulled on stdio.

    The household file lives in a fresh directory, so a take never inherits
    allergens from the one before it.
    """
    launch = (f"import sys; sys.path.insert(0, {str(HERE)!r}); "
              "from pulled.server import server; server.run('stdio')")
    config = {"mcpServers": {"pulled": {
        "command": sys.executable, "args": ["-c", launch],
        "env": {"PULLED_HOME": str(household)}}}}
    path = household / "mcp.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def ask_claude(transcript: str, session: str | None, config: Path) -> dict:
    # The transcript goes in on stdin. On Windows the client is a batch file,
    # and an ampersand or a percent sign in an argument is read by cmd.exe.
    command = [CLIENT, "-p", "--setting-sources", "", "--tools", "",
               "--settings", json.dumps({"autoMemoryEnabled": False}),
               "--mcp-config", str(config), "--strict-mcp-config",
               "--allowedTools", TOOLS, "--model", "sonnet",
               "--append-system-prompt", VOICE_RULES,
               "--output-format", "stream-json", "--verbose"]
    if session:
        command += ["--resume", session]
    started = time.monotonic()
    run = subprocess.run(command, input=transcript, capture_output=True, text=True,
                         encoding="utf-8", cwd=config.parent, timeout=600,
                         env={**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    turn = {"calls": [], "reply": "", "session": session,
            "seconds": round(time.monotonic() - started, 1)}
    pending = {}
    for raw in run.stdout.splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            turn["session"] = event.get("session_id")
        elif kind == "assistant":
            for block in event["message"]["content"]:
                if block["type"] == "tool_use" and block["name"].startswith("mcp__pulled__"):
                    call = {"tool": block["name"].removeprefix("mcp__pulled__"),
                            "arguments": block["input"], "answer": None}
                    pending[block["id"]] = call
                    turn["calls"].append(call)
                elif block["type"] == "text":
                    turn["reply"] = block["text"].strip()
        elif kind == "user":
            for block in event["message"]["content"]:
                if isinstance(block, dict) and block.get("tool_use_id") in pending:
                    body = block.get("content")
                    if isinstance(body, list):
                        body = "".join(part.get("text", "") for part in body)
                    try:
                        body = json.loads(body)
                    except (TypeError, ValueError):
                        pass
                    pending[block["tool_use_id"]]["answer"] = body
        elif kind == "result":
            turn["session"] = event.get("session_id", turn["session"])
    if not turn["reply"]:
        raise RuntimeError("no spoken reply, stderr: " + run.stderr[-600:])
    return turn


def main() -> int:
    if not CLIENT or not shutil.which("ffmpeg"):
        raise SystemExit("talk.py needs the claude command line client and ffmpeg on the path")
    household = Path(tempfile.mkdtemp(prefix="pulled-"))
    TAKE.mkdir(exist_ok=True)
    try:
        config = server_config(household)
        whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
        session = None
        turns = []
        for number, line in enumerate(LINES, 1):
            heard_wav = TAKE / f"{number:02d}-person.wav"
            asyncio.run(speak(line, PERSON_VOICE, heard_wav))
            segments, _ = whisper.transcribe(str(heard_wav), language="en")
            heard = " ".join(segment.text.strip() for segment in segments)
            turn = ask_claude(heard, session, config)
            session = turn["session"]
            asyncio.run(speak(turn["reply"], ASSISTANT_VOICE, TAKE / f"{number:02d}-assistant.wav"))
            kept = {k: v for k, v in turn.items() if k != "session"}
            turns.append({"number": number, "said": line, "heard": heard, **kept})
            # Written after every turn, so a failure at the fourth keeps three.
            (TAKE / "transcript.json").write_text(
                json.dumps(turns, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"[{number}] heard: {heard}")
            for call in turn["calls"]:
                answer = call["answer"] if isinstance(call["answer"], dict) else {}
                print(f"    -> {call['tool']}({json.dumps(call['arguments'])}) "
                      f"outcome={answer.get('outcome')}")
            print(f"    says ({turn['seconds']}s): {turn['reply']}")
    finally:
        shutil.rmtree(household, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
