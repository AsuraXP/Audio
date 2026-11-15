# Audio — Spacecraft Stories Narration

Card-by-card narration for the *Spacecraft Stories* collection:
**20 stories × 3 cards = 60 clips**, one file per card, each in its own folder
so a website can map story → card → audio with a straight path.

| | |
|---|---|
| Voice | `en-US-AndrewNeural` (Microsoft Edge TTS) |
| Rate | `+15%` |
| Format | MP3 + word-level timings |
| Source text | [`stories/spacecraft_stories_cards.txt`](stories/spacecraft_stories_cards.txt) |

## Layout: one folder per story, one subfolder per card

```
audio/
  01-eagle-descent-stage/
    card-1/
      script.txt        <- narration text for this card
      narration.mp3     <- generated audio
      timings.json      <- every word with start/end time
      words.vtt         <- same timings as karaoke WebVTT
      meta.json         <- duration, word count, coverage
    card-2/
    card-3/
  02-laser-ranging-retroreflector/
    card-1/ ...
  ...
  manifest.json         <- every clip in one index
stories/
  spacecraft_stories_cards.txt   <- the source text
  stories.json                   <- story/card index (titles, paths)
scripts/
  parse_cards.py        <- source text -> audio/<story>/<card>/script.txt
  generate_audio.py     <- script.txt -> narration.mp3 via edge-tts
```

Story folders are numbered in the original order. Left-most digits are the
story number, so `audio/07-viking-1-lander/card-2/narration.mp3` is story 7,
card 2.

## Generate the audio

```bash
pip install edge-tts
python3 scripts/parse_cards.py        # writes audio/<story>/<card>/script.txt
python3 scripts/generate_audio.py     # writes narration.mp3 for each card
```

That's it — 60 MP3s plus word timings, one set per card. Useful flags:

```bash
python3 scripts/generate_audio.py --force            # re-render everything
python3 scripts/generate_audio.py --only 01 14       # only stories 01 and 14
python3 scripts/generate_audio.py --dry-run          # show the plan, render nothing
python3 scripts/generate_audio.py --text "hello" --out test.mp3   # quick voice test
```

The script skips cards that already have an MP3, so re-running is cheap and it
resumes where it left off. Failures retry automatically.

## After generating

`audio/manifest.json` and each `meta.json` are refreshed with byte size,
duration, word count and timing coverage. Commit everything:

```bash
git add audio/ stories/stories.json
git commit -m "Add narration audio (60 cards)"
git push
```

## Highlighting the words as they are spoken

Each card has `timings.json`, which maps **every word of `script.txt`** to a
start and end time in seconds:

```json
{
  "duration": 25.32,
  "word_count": 89,
  "coverage": 0.9775,
  "onset_compensation": 0.056,
  "words": [
    { "i": 0, "text": "Hello.", "start": 0.154, "end": 0.415, "matched": true },
    { "i": 1, "text": "You",    "start": 0.773, "end": 0.849, "matched": true }
  ]
}
```

Words are in script order, so `words[i].text` lines up with the `i`-th word of
the narration. `start`/`end` are seconds from the beginning of `narration.mp3`.

`words.vtt` holds the same data as karaoke-style WebVTT — one cue per
paragraph with inline `<timestamp>` tags — so a plain `<track>` element gives
word-by-word highlighting for free:

```html
<audio id="card" src="audio/01-eagle-descent-stage/card-1/narration.mp3"></audio>
<video id="overlay" src="audio/01-eagle-descent-stage/card-1/narration.mp3">
  <track kind="captions" src="audio/01-eagle-descent-stage/card-1/words.vtt" default>
</video>
```

Or drive your own highlighter from `timings.json`:

```js
const words = (await (await fetch(timingsUrl)).json()).words;
const audio = document.querySelector('audio');
audio.addEventListener('timeupdate', () => {
  const t = audio.currentTime;
  const i = words.findIndex(w => t >= w.start && t < w.end);
  highlight(i); // -1 between words / before the first word
});
```

**Accuracy.** `start`/`end` come from the synthesiser's own word-boundary
events, aligned to the script (96.5% of words matched individually; the rest —
mostly numbers like `1969` and symbols — are interpolated between neighbours
and flagged `"matched": false`). A fixed +56 ms compensation corrects a
measured bias in those events, verified against real speech energy: residual
offset is now 0 ms, so highlighting lands on the word as it is spoken.

## For the website

`stories/stories.json` is the index to import:

```json
{
  "stories": [
    {
      "number": 1,
      "title": "Eagle Descent Stage",
      "meta": "Moon  |  Apollo 11 lunar module, lower half",
      "folder": "01-eagle-descent-stage",
      "cards": [
        {
          "card": 1,
          "of": 3,
          "folder": "card-1",
          "audio": "audio/01-eagle-descent-stage/card-1/narration.mp3",
          "script": "audio/01-eagle-descent-stage/card-1/script.txt",
          "timings": "audio/01-eagle-descent-stage/card-1/timings.json",
          "vtt": "audio/01-eagle-descent-stage/card-1/words.vtt",
          "words": 89
        }
      ]
    }
  ]
}
```

Each `audio` path is repo-root relative, so it drops straight into an
`<audio src>` or a build step.

## Editing a story

Change the text in `stories/spacecraft_stories_cards.txt`, keeping the
`N. Title` / `Card N of 3` structure, then re-run the two commands. The parser
keeps every paragraph whole (never split across cards) and stops with an error
if a story does not have exactly three cards. Delete the affected
`narration.mp3` (or use `--force --only NN`) to re-render just that story.

## Optional: GitHub Actions

`.github/workflows/generate-audio.yml` runs the same two scripts on a
GitHub-hosted runner and commits the MP3s. It is manual-only
(**Actions → Generate narration audio → Run workflow**), so it never
overwrites audio unexpectedly.
