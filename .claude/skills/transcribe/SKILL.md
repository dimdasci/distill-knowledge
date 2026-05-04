---
name: transcribe
description: Use when a user needs speech turned into text from an audio or video file — interviews, meetings, voice notes — including cases that need speaker labels (diarization), known-speaker identification, or a language hint. Backed by OpenAI speech-to-text models (`gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-4o-transcribe-diarize`).
---

# Audio Transcribe

OpenAI speech-to-text via the bundled CLI. Examples + output shapes: `references/cli-examples.md`. API: `references/api.md`.

## Setup

1. **`uv`:** `curl -LsSf https://astral.sh/uv/install.sh | sh` (verify `uv --version` ≥ 0.4).
2. **`OPENAI_API_KEY`:** read from process env, else from project `.env`. Either `export OPENAI_API_KEY=sk-...` (wins) or `cp .env.example .env` and paste (gitignored). Key at https://platform.openai.com/api-keys. Never paste in chat; never commit `.env`.

PEP 723 deps resolve on first `uv run --script`.

## Workflow

Collect inputs (paths, speaker-labels?, language, ≤4 known-speaker clips). Check `OPENAI_API_KEY` — missing → ask user to export locally (never accept raw key in chat). Pick model + format (Decision rules). Run CLI (`scripts/transcribe_diarize.py`). Validate; off → change one parameter, rerun. Save to caller path (`--out` / `--out-dir`); standalone default `tmp/transcribe/{job-id}/`.

## Decision rules

| Situation | Choice |
|---|---|
| Default fast text | `--model gpt-4o-mini-transcribe --response-format text` |
| Higher quality, no diarization | `--model gpt-4o-transcribe --response-format json` |
| Speaker labels | `--model gpt-4o-transcribe-diarize --response-format diarized_json` |
| Audio > ~30 s | Keep `--chunking-strategy auto` (default) |
| Identify named speakers | `--known-speaker NAME=path.wav` (≤4, diarize only) |
| Non-English | `--language fr` etc. |
| Video input >25 MB | Extract: `ffmpeg -i v.mp4 -vn -acodec libmp3lame -q:a 2 a.mp3` |

Constraints: 25 MB cap; `--prompt` unsupported on diarize; `diarized_json` diarize-only.

## Canonical example (single file, fast text)

```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  path/to/audio.wav --out transcript.txt
```

More examples (diarization, language hint, dry run, downstream callers): `references/cli-examples.md`.

## Error handling

CLI exits non-zero with stderr `Error [<category>]: <message>`. SDK already retried transient errors.

| Exit | Category, cause, action |
|---|---|
| 0 | success — continue |
| 1 | unknown — abort, surface stderr |
| 2 | input (missing / >25 MB / unreadable) — abort, ask user to fix |
| 10 | auth (401) — **Stop. Ask for valid key. Wait, re-run.** No silent retry. |
| 11 | permission (403/404) — **Stop. Quote failing model. Ask user to grant access or pick another. Wait, re-run.** |
| 12 | rate-limit (429) — link `platform.openai.com/usage`; ask: **wait+retry, or cancel?** |
| 20 | service (network / 5xx) — link `status.openai.com`; ask: **wait+retry, or cancel?** |
| 30 | bad-request (400) — abort, surface `Details:`, ask user to re-encode |

**Default on non-zero exit** — surface `Error [<category>]:` + `Details:`, then ask:

> "The transcribe step failed with `<category>`: \"<one-line summary>\". Should I wait while you fix it (then retry, possibly with adjusted parameters), or cancel the transcription job?"

**wait**: pause until "go", re-run same `uv run --script ...` (adjust only what user said). **cancel**: report, stop.

## Anti-patterns

- **Don't paste the API key in chat or commit it.**
- **Don't request `diarized_json` from a non-diarize model** — rejected.
- **Don't pass `--prompt` to the diarize model** — unsupported.
- **Don't send files >25 MB** — split or transcode first.
- **Don't reinvent the CLI inline** — it handles auth, validation, chunking, paths.
- **Don't run with `python3`** — PEP 723 deps need `uv run --script`.
- **Don't `pip install openai` into system Python** — drifts from uv cache.
- **Don't silently retry 10/11/30** — surface and wait.
