# Audio — Spacecraft Stories Narration

Card-by-card narration audio for the *Spacecraft Stories* collection:
**20 stories × 3 cards = 60 MP3 files**, one file per card, so each card can
play its own clip.

| | |
|---|---|
| Voice | `en-US-AndrewNeural` (Microsoft Edge TTS) |
| Rate | `+15%` |
| Format | MP3, 24 kHz mono |
| Source text | [`stories/spacecraft_stories_cards.txt`](stories/spacecraft_stories_cards.txt) |

## File layout

```
audio/
  01-eagle-descent-stage/
    card-1-of-3.mp3
    card-2-of-3.mp3
    card-3-of-3.mp3
  02-laser-ranging-retroreflector/
    ...
  manifest.json          # voice settings + every clip, with duration
cards/                   # plain-text source for each card (one file per card)
  01-eagle-descent-stage/card-1-of-3.txt
scripts/
  parse_cards.py         # source text -> cards/
  generate_audio.py      # cards/ -> audio/ via edge-tts
```

Story folders are numbered in the original order. `audio/manifest.json` lists
every clip with its byte size and duration, so a player can build its card list
without scanning the filesystem.

## Regenerating the audio

```bash
pip install edge-tts
python scripts/parse_cards.py          # refresh cards/ from the source text
python scripts/generate_audio.py       # renders any missing MP3s
python scripts/generate_audio.py --force --only 01 14   # re-render specific stories
```

The script skips cards whose MP3 already exists, so it is safe to re-run. Use
`--dry-run` to see the plan without rendering.

### GitHub Actions

`.github/workflows/generate-audio.yml` runs the same two scripts on a
GitHub-hosted runner and commits the MP3s back to the branch. Trigger it from
the **Actions → Generate narration audio → Run workflow** button. Tick *force*
to re-render everything; otherwise only missing cards are made.

## Editing a story

Change the text in `stories/spacecraft_stories_cards.txt`, keeping the
`N. Title` / `Card N of 3` structure, then re-run the workflow. Paragraphs are
never split across cards — the parser keeps every paragraph whole and
`parse_cards.py` fails loudly if a story does not have exactly three cards.
