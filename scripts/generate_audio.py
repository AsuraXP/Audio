#!/usr/bin/env python3
"""Render every story card to MP3 with Microsoft Edge TTS.

Voice: en-US-AndrewNeural, rate +15%.

Layout -- one folder per story, one subfolder per card::

    audio/01-eagle-descent-stage/card-1/script.txt
    audio/01-eagle-descent-stage/card-1/narration.mp3

``script.txt`` is written by ``parse_cards.py``; this script adds the MP3 and a
small per-card ``meta.json``, then refreshes ``audio/manifest.json``.

You can also point it straight at a single text file:

    python3 scripts/generate_audio.py --text "hello there" --out /tmp/test.mp3

Requires network access to Microsoft's speech endpoint.

Usage::

    python3 scripts/generate_audio.py                # render cards missing an MP3
    python3 scripts/generate_audio.py --force        # re-render everything
    python3 scripts/generate_audio.py --only 01 14   # just those stories
    python3 scripts/generate_audio.py --dry-run      # print the plan
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
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
MAX_ATTEMPTS = 4


def discover_cards(only: set[str] | None = None) -> list[dict]:
    """Return a sorted list of card jobs found under audio/<story>/<card>/."""
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
                }
            )
    return jobs


async def synthesize(text: str, out: Path, force: bool = False) -> str:
    """Render one clip. Returns 'ok', 'skipped' or raises after retries."""
    if out.exists() and out.stat().st_size > 0 and not force:
        return "skipped"

    import edge_tts  # imported lazily so --dry-run works without the package

    out.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        tmp = out.with_suffix(".part")
        try:
            communicate = edge_tts.Communicate(text, VOICE, rate=RATE, volume=VOLUME, pitch=PITCH)
            await communicate.save(str(tmp))
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("edge-tts wrote an empty file")
            tmp.replace(out)
            return "ok"
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last_error = exc
            tmp.unlink(missing_ok=True)
            print(f"    attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(3 * attempt)

    raise RuntimeError(f"could not synthesize {out.name}: {last_error}")


def probe_duration(path: Path) -> float | None:
    """Read MP3 duration in seconds via ffprobe, when available."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return round(float(result.stdout.strip()), 2)
    except Exception:  # noqa: BLE001 - optional
        return None


def write_card_meta(job: dict) -> dict:
    mp3: Path = job["mp3"]
    duration = probe_duration(mp3)
    words = len(job["script"].read_text(encoding="utf-8").split())
    meta = {
        "story": job["story"],
        "card": job["card"],
        "audio": mp3.relative_to(REPO_ROOT).as_posix(),
        "script": job["script"].relative_to(REPO_ROOT).as_posix(),
        "voice": VOICE,
        "rate": RATE,
        "format": "mp3",
        "bytes": mp3.stat().st_size if mp3.exists() else 0,
        "duration_seconds": duration,
        "words": words,
    }
    (mp3.parent / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def write_manifest(results: list[dict]) -> None:
    entries = []
    for res in results:
        if res["status"] == "failed":
            continue
        entries.append(write_card_meta(res))

    entries.sort(key=lambda e: (e["story"], e["card"]))
    MANIFEST.write_text(
        json.dumps(
            {
                "voice": VOICE,
                "rate": RATE,
                "volume": VOLUME,
                "pitch": PITCH,
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


async def run(jobs: list[dict], force: bool, concurrency: int) -> int:
    print(f"voice={VOICE} rate={RATE} volume={VOLUME} pitch={PITCH}")
    print(f"rendering {len(jobs)} card(s), concurrency {concurrency}\n")

    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def worker(job: dict) -> dict:
        nonlocal done
        async with semaphore:
            label = f"{job['story']}/{job['card']}"
            text = job["script"].read_text(encoding="utf-8").strip()
            try:
                status = await synthesize(text, job["mp3"], force)
                done += 1
                if status == "skipped":
                    print(f"[{done}/{len(jobs)}] skip    {label}  (exists)")
                else:
                    print(f"[{done}/{len(jobs)}] ok      {label}  ({job['mp3'].stat().st_size:,} bytes)")
                return {**job, "status": status}
            except Exception as exc:  # noqa: BLE001
                done += 1
                print(f"[{done}/{len(jobs)}] FAILED  {label}  ({exc})")
                return {**job, "status": "failed", "error": str(exc)}

    results = await asyncio.gather(*(worker(job) for job in jobs))
    write_manifest(list(results))

    failed = [r for r in results if r["status"] == "failed"]
    print(
        f"\ndone: {sum(r['status'] == 'ok' for r in results)} rendered, "
        f"{sum(r['status'] == 'skipped' for r in results)} skipped, {len(failed)} failed"
    )
    for r in failed:
        print(f"  failed: {r['story']}/{r['card']}: {r['error']}", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-render even if the MP3 exists")
    parser.add_argument("--only", nargs="+", metavar="STORY", help="story numbers, e.g. 01 14")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel requests (default 4)")
    parser.add_argument("--text", help="synthesize this literal text instead of the cards")
    parser.add_argument("--out", help="output MP3 path for --text (default: out.mp3)")
    args = parser.parse_args()

    if args.text:
        out = Path(args.out or "out.mp3").expanduser()
        try:
            asyncio.run(synthesize(args.text, out, force=True))
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {out} ({out.stat().st_size:,} bytes)")
        return 0

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
        print(f"\n{len(jobs)} card(s); voice={VOICE} rate={RATE}")
        return 0

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("error: edge-tts is not installed. Run: pip install edge-tts", file=sys.stderr)
        return 1

    return asyncio.run(run(jobs, args.force, args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
