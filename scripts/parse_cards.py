#!/usr/bin/env python3
"""Parse the card-split stories source into one plain-text file per card.

Source format::

    Spacecraft Stories: Card Split
    <intro lines>

    1. Eagle Descent Stage
    Moon  |  Apollo 11 lunar module, lower half
    Card 1 of 3
    <paragraph>
    <paragraph>

    Card 2 of 3
    <paragraph>

    ...

Output::

    cards/nn-slug/card-n-of-3.txt

Usage:  python scripts/parse_cards.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "stories" / "spacecraft_stories_cards.txt"
CARDS_DIR = REPO_ROOT / "cards"

STORY_RE = re.compile(r"^(\d{1,2})\.\s+(.+?)\s*$")
CARD_RE = re.compile(r"^Card\s+(\d+)\s+of\s+(\d+)\s*$")


def slugify(text: str) -> str:
    """Turn a story title into a filesystem- and URL-friendly slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def parse(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

    stories: list[dict] = []
    story = None
    card = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        story_match = STORY_RE.match(line)
        if story_match and not CARD_RE.match(line):
            story = {
                "number": int(story_match.group(1)),
                "title": story_match.group(2),
                "slug": slugify(story_match.group(2)),
                "meta": "",
                "cards": [],
            }
            stories.append(story)
            card = None
            continue

        if story is None:
            continue  # header block before the first numbered story

        card_match = CARD_RE.match(line)
        if card_match:
            index, total = int(card_match.group(1)), int(card_match.group(2))
            card = {"index": index, "total": total, "paragraphs": []}
            story["cards"].append(card)
            continue

        if card is None:
            # First non-card line after the title is the "Moon | description" meta line.
            if not story["meta"]:
                story["meta"] = line
            continue

        card["paragraphs"].append(line)

    return stories


def card_text(card: dict) -> str:
    return "\n\n".join(card["paragraphs"])


def validate(stories: list[dict]) -> list[str]:
    errors = []
    if len(stories) != 20:
        errors.append(f"expected 20 stories, found {len(stories)}")
    for story in stories:
        if len(story["cards"]) != 3:
            errors.append(f"{story['number']}. {story['title']}: expected 3 cards, found {len(story['cards'])}")
        for card in story["cards"]:
            if not card["paragraphs"]:
                errors.append(f"{story['number']}. {story['title']} card {card['index']}: no text")
            if card["total"] != 3:
                errors.append(f"{story['number']}. {story['title']} card {card['index']}: total {card['total']} != 3")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()

    if not SOURCE.exists():
        print(f"error: source not found: {SOURCE}", file=sys.stderr)
        return 1

    stories = parse(SOURCE.read_text(encoding="utf-8-sig"))
    errors = validate(stories)
    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    total_cards = 0
    for story in stories:
        for card in story["cards"]:
            total_cards += 1
            if args.check:
                continue
            folder = CARDS_DIR / f"{story['number']:02d}-{story['slug']}"
            folder.mkdir(parents=True, exist_ok=True)
            out = folder / f"card-{card['index']}-of-{card['total']}.txt"
            out.write_text(card_text(card) + "\n", encoding="utf-8")

    print(f"parsed {len(stories)} stories, {total_cards} cards"
          + (" (validated only)" if args.check else f" -> {CARDS_DIR}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
