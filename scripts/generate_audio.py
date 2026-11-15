#!/usr/bin/env python3
"""Render every card to MP3 with Microsoft Edge TTS (en-US-AndrewNeural).

Reads ``cards/<story>/card-N-of-3.txt`` (produced by ``parse_cards.py``) and
writes ``audio/<story>/card-N-of-3.mp3`` plus ``audio/manifest.json``.

Requires network access to Microsoft's speech endpoint -- run this from a
normal machine, or trigger the ``Generate narration audio`` GitHub workflow
which does the same thing on a GitHub-hosted runner.

Usage::

    python scripts/generate_audio.py              # render missing files only
    python scripts/generate_audio.py --force      # re-render everything
    python scripts/generate_audio.py --only 01 14 # just those stories
    python scripts/generate_audio.py --dry-run    # show the plan
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
CARDS_DIR = REPO_ROOT / "cards"
AUDIO_DIR = REPO_ROOT / "audio"
MANIFEST = AUDIO_DIR / "manifest.json"

VOICE = "en-US-AndrewNeural"
RATE = "+15%"
VOLUME = "+0%"
PITCH = "+0Hz"
MAX_ATTEMPTS = 4


def discover_cards(only: set[str] | None = None) -> list[dict]:
    """Return a sorted list of card jobs found on disk."""
    jobs: list[dict] = []
    for story_dir in sorted(p for p in CARDS_DIR.iterdir() if p.is_dir()):
        story_prefix = story_dir.name.split("-", 1)[0]
        if only and story_prefix not in only and story_dir.name not in only:
            continue
        for txt in sorted(story_dir.glob("card-*.txt")):
            card_name = txt.stem  # card-1-of-3
            jobs.append(
                {
                    "story_slug": story_dir.name,
                    "card": card_name,
                    "text_path": txt,
                    "mp3_path": AUDIO_DIR / story_dir.name / f"{card_name}.mp3",
                }
            )
    return jobs


async def synth(job: dict, force: bool) -> dict:
    """Render one card with edge-tts, retrying transient network failures."""
    text = job["text_path"].read_text(encoding="utf-8").strip()
    out: Path = job["mp3_path"]
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists() and out.stat().st_size > 0 and not force:
        return {**job, "status": "skipped", "bytes": out.stat().st_size}

    import edge_tts  # imported lazily so --dry-run works without the package

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            tmp = out.with_suffix(".mp3.part")
            communicate = edge_tts.Communicate(text, VOICE, rate=RATE, volume=VOLUME, pitch=PITCH)
            await communicate.save(str(tmp))
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("edge-tts wrote an empty file")
            tmp.replace(out)
            return {**job, "status": "ok", "bytes": out.stat().st_size}
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last_error = exc
            tmp = out.with_suffix(".mp3.part")
            if tmp.exists():
                tmp.unlink()
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}", file=sys.stderr)
            await asyncio.sleep(3 * attempt)

    return {**job, "status": "failed", "error": str(last_error)}


def probe_duration(path: Path) -> float | None:
    """Read MP3 duration in seconds via ffprobe, when available."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return round(float(result.stdout.strip()), 2)
    except Exception:  # noqa: BLE001 - ffprobe is optional
        return None


def write_manifest(results: list[dict]) -> None:
    entries = []
    for res in results:
        if res["status"] == "failed":
            continue
        mp3: Path = res["mp3_path"]
        mp3 = mp3 if mp3.is_absolute() else REPO_ROOT / mp3
        rel = mp3.relative_to(REPO_ROOT).as_posix()
        entries.append(
            {
                "story": res["story_slug"],
                "card": res["card"],
                "file": rel,
                "bytes": res.get("bytes", mp3.stat().st_size if mp3.exists() else 0),
                "duration_seconds": probe_duration(mp3),
            }
        )

    entries.sort(key=lambda e: (e["story"], e["card"]))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
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
    print(f"rendering {len(jobs)} card(s) with concurrency {concurrency}\n")

    semaphore = asyncio.Semaphore(concurrency)
    finished = 0

    async def worker(job: dict) -> dict:
        nonlocal finished
        async with semaphore:
            res = await synth(job, force)
            finished += 1
            label = f"{job['story_slug']}/{job['card']}"
            if res["status"] == "ok":
                print(f"[{finished}/{len(jobs)}] ok      {label}  ({res['bytes']:,} bytes)")
            elif res["status"] == "skipped":
                print(f"[{finished}/{len(jobs)}] skip    {label}  (already exists)")
            else:
                print(f"[{finished}/{len(jobs)}] FAILED  {label}  ({res.get('error')})")
            return res

    results = await asyncio.gather(*(worker(job) for job in jobs))
    write_manifest(list(results))

    failed = [r for r in results if r["status"] == "failed"]
    ok = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    print(f"\ndone: {len(ok)} rendered, {len(skipped)} skipped, {len(failed)} failed")
    if failed:
        for r in failed:
            print(f"  failed: {r['story_slug']}/{r['card']}: {r['error']}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-render even if the MP3 exists")
    parser.add_argument("--only", nargs="+", metavar="STORY", help="story numbers, e.g. 01 14")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel requests (default 4)")
    args = parser.parse_args()

    if not CARDS_DIR.exists():
        print("error: cards/ not found -- run scripts/parse_cards.py first", file=sys.stderr)
        return 1

    only = {s.zfill(2) for s in args.only} if args.only else None
    jobs = discover_cards(only)
    if not jobs:
        print("error: no cards matched", file=sys.stderr)
        return 1

    if args.dry_run:
        for job in jobs:
            print(f"{job['story_slug']}/{job['card']}.txt -> "
                  f"{job['mp3_path'].relative_to(REPO_ROOT)}")
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
