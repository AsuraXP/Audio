#!/usr/bin/env python3
"""Render every story card to MP3 with Microsoft Edge TTS, plus word timings.

Voice: en-US-AndrewNeural, rate +15%.

Layout -- one folder per story, one subfolder per card::

    audio/01-eagle-descent-stage/card-1/script.txt      narration text
    audio/01-eagle-descent-stage/card-1/narration.mp3   audio
    audio/01-eagle-descent-stage/card-1/timings.json    word-by-word timings
    audio/01-eagle-descent-stage/card-1/words.vtt       same, as WebVTT
    audio/01-eagle-descent-stage/card-1/meta.json       summary

``timings.json`` maps every word of ``script.txt`` to a start/end time so a
player can highlight the word being spoken::

    {"duration": 25.32, "coverage": 0.99, "word_count": 89,
     "words": [{"i": 0, "text": "Hello.", "start": 0.0, "end": 0.32,
                "matched": true}, ...]}

Usage::

    python3 scripts/generate_audio.py                # render cards missing files
    python3 scripts/generate_audio.py --force        # re-render everything
    python3 scripts/generate_audio.py --only 01 14   # just those stories
    python3 scripts/generate_audio.py --dry-run      # print the plan
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = REPO_ROOT / "audio"
MANIFEST = AUDIO_DIR / "manifest.json"

VOICE = "en-US-AndrewNeural"
RATE = "+15%"
VOLUME = "+0%"
PITCH = "+0Hz"
AUDIO_NAME = "narration.mp3"
SCRIPT_NAME = "script.txt"
TIMINGS_NAME = "timings.json"
VTT_NAME = "words.vtt"
MAX_ATTEMPTS = 4
TICKS_PER_SECOND = 10_000_000  # edge-tts offsets are in 100-nanosecond ticks

WORD_RE = re.compile(r"[^\w']+", re.UNICODE)


# --------------------------------------------------------------------------
# alignment: TTS word events -> words of script.txt
# --------------------------------------------------------------------------

def normalize(token: str) -> str:
    """Lowercase and strip punctuation so 'Hello.' matches 'hello'."""
    return WORD_RE.sub("", token.lower())


def fill_gaps(tokens: list[str], times: list[tuple[float, float] | None]) -> set[int]:
    """Give unaligned tokens a proportional slice of the gap around them.

    Returns the set of token indexes that had to be interpolated.
    """
    filled: set[int] = set()
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        prev_end = times[i - 1][1] if i > 0 else 0.0
        next_start = times[j][0] if j < n else prev_end
        span = max(next_start - prev_end, 0.0)
        weights = [max(len(tokens[k]), 1) for k in range(i, j)]
        total = sum(weights) or 1
        acc = prev_end
        for k in range(i, j):
            dur = span * weights[k - i] / total
            times[k] = (round(acc, 3), round(acc + dur, 3))
            acc += dur
            filled.add(k)
        i = j
    return filled


def align(script: str, spoken: list[dict], fallback_duration: float = 0.0) -> dict:
    """Align edge-tts WordBoundary events to the words of ``script``.

    Every token in the script gets a start/end time. Words the service did not
    report individually (numbers, symbols, odd spellings) are interpolated
    between their neighbours and flagged ``"matched": false``.
    """
    tokens = script.split()
    if not tokens:
        return {"words": [], "coverage": 0.0, "matched": 0,
                "interpolated": 0, "duration": 0.0}

    a = [normalize(t) for t in tokens]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    matched = 0

    if spoken:
        b = [normalize(w["text"]) for w in spoken]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False
        ).get_opcodes():
            if tag == "equal" or (tag == "replace" and (i2 - i1) == (j2 - j1)):
                # equal, or same count spelled differently (e.g. "1969")
                for k in range(i2 - i1):
                    times[i1 + k] = (spoken[j1 + k]["start"], spoken[j1 + k]["end"])
                    matched += 1

    interpolated = fill_gaps(tokens, times)

    # Nothing usable came back: spread evenly so the file is still valid
    # (flagged by coverage 0.0).
    if len(interpolated) == len(tokens) and fallback_duration > 0:
        weights = [max(len(t), 1) for t in tokens]
        total = sum(weights)
        acc = 0.0
        for idx, w in enumerate(weights):
            dur = fallback_duration * w / total
            times[idx] = (round(acc, 3), round(acc + dur, 3))
            acc += dur

    words = [
        {
            "i": idx,
            "text": tokens[idx],
            "start": times[idx][0] if times[idx] else 0.0,
            "end": times[idx][1] if times[idx] else 0.0,
            "matched": idx not in interpolated,
        }
        for idx in range(len(tokens))
    ]

    return {
        "words": words,
        "coverage": round(matched / len(tokens), 4),
        "matched": matched,
        "interpolated": len(interpolated),
        "duration": round(max((w["end"] for w in words), default=0.0), 3),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

async def render(text: str, out: Path) -> list[dict]:
    """Synthesize one card; return the word events reported by the service."""
    import edge_tts

    communicate = edge_tts.Communicate(
        text, VOICE, rate=RATE, volume=VOLUME, pitch=PITCH, boundary="WordBoundary"
    )
    spoken: list[dict] = []
    tmp = out.with_suffix(".part")
    with open(tmp, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / TICKS_PER_SECOND
                spoken.append(
                    {
                        "text": chunk["text"],
                        "start": round(start, 3),
                        "end": round(start + chunk["duration"] / TICKS_PER_SECOND, 3),
                    }
                )
    if not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("edge-tts wrote an empty file")
    tmp.replace(out)
    return spoken


async def synthesize(job: dict, force: bool) -> dict:
    """Render (or reuse) one card, then (re)write its timing files."""
    text = job["script"].read_text(encoding="utf-8").strip()
    have_all = job["mp3"].exists() and job["mp3"].stat().st_size > 0 and job["timings"].exists()
    if have_all and not force:
        return {**job, "status": "skipped"}

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            spoken = await render(text, job["mp3"])
            elapsed = time.monotonic() - started
            duration = probe_duration(job["mp3"]) or 0.0
            aligned = align(text, spoken, fallback_duration=duration)
            duration = duration or aligned["duration"]
            write_timings(job, text, aligned, duration)
            return {
                **job,
                "status": "ok",
                "seconds": round(elapsed, 2),
                "bytes": job["mp3"].stat().st_size,
                "duration": duration,
                "coverage": aligned["coverage"],
                "words": len(aligned["words"]),
                "interpolated": aligned["interpolated"],
            }
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last_error = exc
            job["mp3"].with_suffix(".part").unlink(missing_ok=True)
            print(f"    attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(3 * attempt)

    return {**job, "status": "failed", "error": str(last_error)}


# --------------------------------------------------------------------------
# output files
# --------------------------------------------------------------------------

def vtt_timestamp(seconds: float) -> str:
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_vtt(path: Path, text: str, words: list[dict], duration: float) -> None:
    """WebVTT with inline per-word timestamps (karaoke), one cue per paragraph."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    cues: list[list[dict]] = []
    cursor = 0
    for para in paragraphs:
        n = len(para.split())
        cues.append(words[cursor:cursor + n])
        cursor += n

    lines = ["WEBVTT", ""]
    for idx, cue_words in enumerate(cues, start=1):
        if not cue_words:
            continue
        start = cue_words[0]["start"]
        end = cue_words[-1]["end"]
        if idx == len(cues):
            end = max(duration, end)
        lines.append(str(idx))
        lines.append(f"{vtt_timestamp(start)} --> {vtt_timestamp(end)}")
        lines.append(" ".join(f"<{vtt_timestamp(w['start'])}>{w['text']}" for w in cue_words))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_timings(job: dict, text: str, aligned: dict, duration: float) -> None:
    job["timings"].write_text(
        json.dumps(
            {
                "story": job["story"],
                "card": job["card"],
                "audio": AUDIO_NAME,
                "voice": VOICE,
                "rate": RATE,
                "duration": round(duration, 3),
                "word_count": len(aligned["words"]),
                "matched_words": aligned["matched"],
                "coverage": aligned["coverage"],
                "words": aligned["words"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_vtt(job["vtt"], text, aligned["words"], duration)


def probe_duration(path: Path) -> float | None:
    """Read MP3 duration in seconds via ffprobe, when available."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return round(float(result.stdout.strip()), 3)
    except Exception:  # noqa: BLE001 - optional
        return None


def write_card_meta(job: dict) -> dict:
    mp3: Path = job["mp3"]
    duration = words = coverage = None
    if job["timings"].exists():
        data = json.loads(job["timings"].read_text(encoding="utf-8"))
        duration = data.get("duration")
        words = data.get("word_count")
        coverage = data.get("coverage")
    if duration is None:
        duration = probe_duration(mp3)

    meta = {
        "story": job["story"],
        "card": job["card"],
        "audio": mp3.relative_to(REPO_ROOT).as_posix(),
        "script": job["script"].relative_to(REPO_ROOT).as_posix(),
        "timings": job["timings"].relative_to(REPO_ROOT).as_posix(),
        "vtt": job["vtt"].relative_to(REPO_ROOT).as_posix(),
        "voice": VOICE,
        "rate": RATE,
        "format": "mp3",
        "bytes": mp3.stat().st_size if mp3.exists() else 0,
        "duration_seconds": duration,
        "words": words,
        "coverage": coverage,
    }
    (mp3.parent / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def write_manifest(results: list[dict]) -> None:
    entries = sorted(
        (write_card_meta(r) for r in results if r["status"] != "failed"),
        key=lambda e: (e["story"], e["card"]),
    )
    MANIFEST.write_text(
        json.dumps(
            {
                "voice": VOICE,
                "rate": RATE,
                "volume": VOLUME,
                "pitch": PITCH,
                "timings": "word-level (timings.json per card)",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "clip_count": len(entries),
                "clips": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST.relative_to(REPO_ROOT)} ({len(entries)} clips)")


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def discover_cards(only: set[str] | None = None) -> list[dict]:
    jobs: list[dict] = []
    for story_dir in sorted(p for p in AUDIO_DIR.iterdir() if p.is_dir()):
        story_prefix = story_dir.name.split("-", 1)[0]
        if only and story_prefix not in only and story_dir.name not in only:
            continue
        for card_dir in sorted(p for p in story_dir.iterdir() if p.is_dir()):
            script = card_dir / SCRIPT_NAME
            if not script.exists():
                continue
            jobs.append(
                {
                    "story": story_dir.name,
                    "card": card_dir.name,
                    "script": script,
                    "mp3": card_dir / AUDIO_NAME,
                    "timings": card_dir / TIMINGS_NAME,
                    "vtt": card_dir / VTT_NAME,
                }
            )
    return jobs


async def run(jobs: list[dict], force: bool, concurrency: int) -> int:
    print(f"voice={VOICE} rate={RATE} pitch={PITCH} -- word-level timings")
    print(f"rendering {len(jobs)} card(s), concurrency {concurrency}\n")

    semaphore = asyncio.Semaphore(concurrency)
    done = 0
    wall_start = time.monotonic()

    async def worker(job: dict) -> dict:
        nonlocal done
        async with semaphore:
            label = f"{job['story']}/{job['card']}"
            res = await synthesize(job, force)
            done += 1
            if res["status"] == "ok":
                print(f"[{done}/{len(jobs)}] ok      {label}  "
                      f"({res['bytes']:,} B, {res['duration']}s, {res['words']} words, "
                      f"coverage {res['coverage']:.0%}, {res['interpolated']} interpolated, "
                      f"{res['seconds']}s render)")
            elif res["status"] == "skipped":
                print(f"[{done}/{len(jobs)}] skip    {label}  (exists)")
            else:
                print(f"[{done}/{len(jobs)}] FAILED  {label}  ({res.get('error')})")
            return res

    results = list(await asyncio.gather(*(worker(job) for job in jobs)))
    wall = time.monotonic() - wall_start
    write_manifest(results)

    failed = [r for r in results if r["status"] == "failed"]
    ok = [r for r in results if r["status"] == "ok"]
    print(f"\ndone: {len(ok)} rendered, "
          f"{sum(r['status'] == 'skipped' for r in results)} skipped, {len(failed)} failed")
    if ok:
        print(f"average word coverage: {sum(r['coverage'] for r in ok) / len(ok):.1%}"
              f"   wall time: {wall:.1f}s")
    for r in failed:
        print(f"  failed: {r['story']}/{r['card']}: {r['error']}", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--force", action="store_true", help="re-render even if files exist")
    parser.add_argument("--only", nargs="+", metavar="STORY", help="story numbers, e.g. 01 14")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel requests (default 4)")
    args = parser.parse_args()

    if not AUDIO_DIR.exists():
        print("error: audio/ not found -- run scripts/parse_cards.py first", file=sys.stderr)
        return 1

    only = {s.zfill(2) for s in args.only} if args.only else None
    jobs = discover_cards(only)
    if not jobs:
        print("error: no cards matched -- run scripts/parse_cards.py first", file=sys.stderr)
        return 1

    if args.dry_run:
        for job in jobs:
            print(f"{job['script'].relative_to(REPO_ROOT)} -> {job['mp3'].relative_to(REPO_ROOT)}")
        print(f"\n{len(jobs)} card(s); voice={VOICE} rate={RATE} word-level timings")
        return 0

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("error: edge-tts is not installed. Run: pip install edge-tts", file=sys.stderr)
        return 1

    return asyncio.run(run(jobs, args.force, args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
