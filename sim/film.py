"""Play a recorded take of talk.py on a simulated Alexa+ kitchen display.

The display is `device.html`. This script drives it turn by turn from
`take/transcript.json`, the same take whose audio sits beside it, and films it:

    python talk.py              record a real spoken take first
    python sim/film.py          write sim/out/pulled-device.mp4

The caption, the spoken reply, what the result card says, every tool call in
the MCP panel and every voice in the conversation come from the take. What the
simulation adds is the device around them, and one thing it removes, the
seconds the model spent deciding, which are replaced by a fixed pause and said
so in the opening narration.

Nothing listens on a port. The page is opened from disk in a headless browser,
whose own recorder makes the picture, and ffmpeg lays the take's audio under it
at the moments the page was told to show each turn. The recorder starts well
over a second after the page exists, by an amount that changes between runs,
so the page first flashes white and the clock is set on that frame. Needs `playwright` with
Chromium, `edge-tts` for the two narration lines, and ffmpeg on the path.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import edge_tts
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TAKE = HERE.parent / "take"
OUT = HERE / "out"
SIZE = {"width": 1600, "height": 900}

NARRATOR = "en-US-BrianNeural"
DECIDING = 1.4
LIMIT = 179.0

OPENING = (
    "pulled answers one kitchen question out loud. Has this food been recalled, "
    "and does it matter to the people in this house. This is a simulated Alexa plus "
    "display playing a real recorded take. A voice speaks, Whisper transcribes it, "
    "a language model picks the pulled tool over MCP, and the reply is read back. "
    "Only the model's thinking time is cut."
)
CLOSING = (
    "When the label is not enough, pulled asks one question instead of guessing, "
    "because a wrong all clear and a wrong alarm both hurt. And a clear answer is "
    "never a promise that the food is safe. The server, this simulation and the "
    "take are open source."
)


def seconds(path: Path) -> float:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(probe.stdout)


def narrate(text: str, path: Path) -> None:
    asyncio.run(edge_tts.Communicate(text, NARRATOR).save(str(path)))


def card(call: dict) -> dict:
    """What the screen shows under the spoken reply, read from the tool answer."""
    answer = call["answer"]
    if call["tool"] == "set_allergens":
        return {"kind": "stored", "label": "Household saved",
                "title": "Allergens, " + " and ".join(answer["allergens"]), "facts": []}
    outcome = answer["outcome"]
    if outcome == "recalled":
        say = answer["say"]
        title = re.split(r" was (?:recalled|covered) ", say)[0]
        title = re.sub(r" from [^.]*$", "", title)
        reason = re.search(r"The reason given is (.*?)\.", say)
        when = re.search(r" on (\d{1,2} \w+ \d{4})", say)
        grade = re.search(r"Class [IV]+", say)
        facts = [("Reason", reason.group(1) if reason else ""),
                 ("Recalled", when.group(1) if when else ""),
                 ("Severity", grade.group(0) if grade else ""),
                 ("Recall", answer["recall_number"])]
        return {"kind": "recalled", "label": "Recalled", "title": title,
                "facts": [pair for pair in facts if pair[1]]}
    if outcome == "unclear":
        many = re.search(r"I found (\d+) recalls", answer["ask"])
        facts = [("Possible matches", many.group(1))] if many else []
        return {"kind": "unclear", "label": "Not sure yet, one question", "title": answer["ask"],
                "facts": facts}
    return {"kind": "clear", "label": "No recall found", "title": answer["say"], "facts": []}


def wire(call: dict) -> dict:
    answer = call["answer"]
    outcome = answer.get("outcome", "stored")
    mark = {"recalled": "r", "unclear": "u", "clear": "c"}.get(outcome, "s")
    return {"tool": call["tool"], "arguments": call["arguments"], "outcome": outcome, "mark": mark}


def film(turns: list[dict], opening: Path, closing: Path) -> tuple[Path, float, list[tuple[float, Path]]]:
    """Drive the page and return the raw video, when the flash was shown, and
    when each sound starts, all on the script's clock."""
    raw = OUT / "raw"
    shutil.rmtree(raw, ignore_errors=True)
    sounds: list[tuple[float, Path]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw), record_video_size=SIZE)
        page = context.new_page()
        start = time.monotonic()
        page.goto((HERE / "device.html").as_uri())
        page.wait_for_timeout(1500)
        page.evaluate("""() => {
            const white = document.createElement('div');
            white.id = 'sync';
            white.style.cssText = 'position:fixed;inset:0;background:#fff;z-index:9';
            document.body.appendChild(white);
        }""")
        flash = time.monotonic() - start
        page.wait_for_timeout(200)
        page.evaluate("document.getElementById('sync').remove()")

        def at(path: Path) -> None:
            sounds.append((time.monotonic() - start, path))

        def hold(span: float) -> None:
            page.wait_for_timeout(span * 1000)

        page.evaluate("([t, b, s]) => slate(t, b, s)",
                      ["pulled", "Has this food been recalled, and does it matter in this house?",
                       "Simulated Alexa+ display, real recorded take"])
        hold(0.8)
        at(opening)
        hold(seconds(opening) + 0.6)
        page.evaluate("unslate()")
        hold(1.2)

        for turn in turns:
            number = f"{turn['number']:02d}"
            person, assistant = TAKE / f"{number}-person.wav", TAKE / f"{number}-assistant.wav"
            page.evaluate("([t, s]) => listen(t, s)", [turn["heard"], seconds(person)])
            at(person)
            hold(seconds(person) + 0.3)
            page.evaluate("calls => think(calls)", [wire(c) for c in turn["calls"]])
            hold(DECIDING)
            page.evaluate("([r, c]) => speak(r, c)", [turn["reply"], card(turn["calls"][-1])])
            at(assistant)
            hold(seconds(assistant) + 0.4)
            page.evaluate("rest()")
            hold(1.6)

        page.evaluate("([t, b, s]) => slate(t, b, s)",
                      ["Asks, never guesses",
                       "Three outcomes, recalled, unclear or clear. FDA and USDA recall feeds, "
                       "read live. MCP 2025-11-25 over Streamable HTTP.",
                       "github.com/thibaudlepan77-svg/pulled"])
        hold(0.8)
        at(closing)
        hold(seconds(closing) + 1.5)
        video = Path(page.video.path())
        context.close()
        browser.close()
    return video, flash, sounds


def flash_frame(video: Path) -> float:
    """When the white frame shows in the recording, in seconds."""
    rate = 50
    grey = subprocess.run(["ffmpeg", "-loglevel", "error", "-t", "8", "-i", str(video),
                           "-vf", f"fps={rate},scale=16:9", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, check=True).stdout
    for index in range(len(grey) // 144):
        frame = grey[index * 144:(index + 1) * 144]
        if sum(frame) / 144 > 200:
            return index / rate
    raise SystemExit("no sync flash in the first eight seconds of the recording")


def mix(video: Path, flash: float, sounds: list[tuple[float, Path]], target: Path) -> None:
    seen = flash_frame(video)
    cut = seen + 0.4
    inputs, chains = ["-ss", f"{cut:.3f}", "-i", str(video)], []
    for index, (offset, path) in enumerate(sounds, start=1):
        inputs += ["-i", str(path)]
        delay = int((offset - flash + seen - cut) * 1000)
        chains.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"adelay={delay}|{delay}[a{index}]")
    labels = "".join(f"[a{i}]" for i in range(1, len(sounds) + 1))
    graph = ";".join(chains) + f";{labels}amix=inputs={len(sounds)}:normalize=0[sound]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
                    "-map", "0:v", "-map", "[sound]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-shortest",
                    str(target)], check=True)


def main() -> None:
    turns = json.loads((TAKE / "transcript.json").read_text(encoding="utf-8"))
    missing = [f"{t['number']:02d}-{who}.wav" for t in turns for who in ("person", "assistant")
               if not (TAKE / f"{t['number']:02d}-{who}.wav").exists()]
    if missing:
        sys.exit(f"the take has no audio for {', '.join(missing)}, run talk.py first")
    OUT.mkdir(exist_ok=True)
    opening, closing = OUT / "opening.mp3", OUT / "closing.mp3"
    narrate(OPENING, opening)
    narrate(CLOSING, closing)
    video, flash, sounds = film(turns, opening, closing)
    target = OUT / "pulled-device.mp4"
    mix(video, flash, sounds, target)
    length = seconds(target)
    print(f"{target} {length:.1f} s")
    if length > LIMIT:
        sys.exit(f"{length:.1f} s is over the three minute limit")


if __name__ == "__main__":
    main()
