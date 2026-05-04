---
name: transcribe
description: Use when a user needs speech turned into text from an audio or video file — interviews, meetings, voice notes — including cases that need speaker labels (diarization), known-speaker identification, or a language hint. Backed by OpenAI speech-to-text models (`gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-4o-transcribe-diarize`).
---

# Audio Transcribe

Transcribe audio (or the audio track of a video) using OpenAI speech-to-text models, with optional speaker diarization. Always go through the bundled CLI for deterministic, repeatable runs.

## Setup (one-time per machine)

1. **Install `uv`** (Python script runner; manages the per-script venv automatically):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   Verify: `uv --version` prints a version ≥0.4.

2. **Provide `OPENAI_API_KEY`.** The script reads it from the process environment first, and falls back to a project-root `.env` file if unset. Pick one:
   - **Shell export** (precedence: wins over `.env`):
     ```bash
     export OPENAI_API_KEY=sk-...
     ```
   - **`.env` fallback** (convenient for local dev — the file is gitignored):
     ```bash
     cp .env.example .env
     # then edit .env and paste your key after OPENAI_API_KEY=
     ```
   Get a key at https://platform.openai.com/api-keys. Never paste the key into chat, and never commit `.env`.

That's it — no `pip install`, no venv. The script declares its own deps via PEP 723; `uv run --script` builds and caches an isolated environment on first run.

## Preflight (run before first invocation)

```bash
uv --version                                              # uv installed?
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py --help  # deps resolve?
```

If `uv --version` fails → run the Setup step above. If the `--help` invocation fails with "openai not installed", report the error verbatim — do not try to `pip install` manually, that defeats the point of PEP 723.

## Workflow

1. **Collect inputs.** Audio/video path(s); whether speaker labels are needed; optional language hint; up to 4 known-speaker reference clips if speaker identity matters.
2. **Check `OPENAI_API_KEY`.** If missing, ask the user to export it locally — never ask for the raw key in chat.
3. **Pick the right model + format** (see Decision rules below).
4. **Run the bundled CLI** (`scripts/transcribe_diarize.py`).
5. **Validate the output** — transcription quality, speaker labels, segment boundaries. If something looks off, change one parameter and rerun.
6. **Save outputs** to a path the caller controls (`--out` for a single file, `--out-dir` for multiple). When invoked standalone with no destination provided, default to `tmp/transcribe/{job-id}/`.

## Decision rules

| Situation | Choice |
|-----------|--------|
| Default fast text transcription | `--model gpt-4o-mini-transcribe --response-format text` |
| Higher-quality non-diarized transcription | `--model gpt-4o-transcribe --response-format json` |
| Speaker labels / diarization wanted | `--model gpt-4o-transcribe-diarize --response-format diarized_json` |
| Audio longer than ~30 seconds | Keep `--chunking-strategy auto` (the default) |
| Identify specific named speakers | Add `--known-speaker NAME=path/to/sample.wav` (up to 4) — diarize model only |
| Non-English audio | Pass `--language` (e.g. `--language fr`) when known |
| Input is a video file | Either pass it directly (mp4/webm/m4a are accepted) **or** extract audio first with `ffmpeg -i video.mp4 -vn -acodec libmp3lame -q:a 2 audio.mp3` if the file is over 25 MB |

Constraints:
- Per-request file size cap: **25 MB**. Larger files need to be split or compressed before sending.
- `--prompt` is **not supported** with `gpt-4o-transcribe-diarize`.
- `diarized_json` is only valid with `gpt-4o-transcribe-diarize`.

## CLI quick start

The script lives at `.claude/skills/transcribe/scripts/transcribe_diarize.py`, relative to the project root. Invoke with `uv run --script` (the script declares its deps via PEP 723).

**Single file, fast text:**
```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  path/to/audio.wav \
  --out transcript.txt
```

**Diarization with known speakers:**
```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  meeting.m4a \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --known-speaker "Alice=refs/alice.wav" \
  --known-speaker "Bob=refs/bob.wav" \
  --out-dir tmp/transcribe/meeting
```

**Plain text with language hint:**
```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  interview.mp3 \
  --response-format text \
  --language en \
  --out interview.txt
```

**Dry run** (validate args + print payload, no API call):
```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  audio.wav --dry-run
```

Run the CLI with `--help` for the full flag list.

## Output shapes

- `text`: plain UTF-8 transcript, no timestamps.
- `json`: `{"text": "..."}` plus model metadata.
- `diarized_json`: `segments[]` with `speaker`, `start`, `end`, `text` fields. **This is the format to use whenever speaker attribution matters** (e.g. when feeding the `convert` skill).

## Dependencies

The script declares its own dependencies via PEP 723 inline metadata. `uv run --script` resolves and caches them automatically in an isolated environment — there is nothing to install manually.

If you need to inspect or pre-warm the cache:
```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py --help
```

## Environment

`OPENAI_API_KEY` is required for live API calls. See the Setup section above for shell-export and `.env` options.

## Calling from other skills

When the `convert` skill (or any caller) needs diarized output for downstream processing, use:

```bash
uv run --script .claude/skills/transcribe/scripts/transcribe_diarize.py \
  "$AUDIO" \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --out-dir "$OUT_DIR"
```

The diarized JSON has its own `segments[]` schema — do not pipe it through `parse_vtt.py`.

## Reference

- `references/api.md` — supported input formats, size limits, response formats, known-speaker payload notes.

## Error handling

When the CLI exits non-zero, the first stderr line is `Error [<category>]: <message>` and the exit code is category-specific. The OpenAI SDK already auto-retries transient connection / 5xx / rate-limit errors before the script exits, so anything reaching you has already failed once and is worth surfacing to the user.

| Exit | Category | Cause | What the agent should do |
|------|----------|-------|--------------------------|
| 0 | — | success | continue |
| 1 | unknown | unexpected exception | abort the job; surface stderr verbatim; ask the user how to proceed |
| 2 | input | audio file missing / >25 MB / unreadable | abort; ask the user to fix the input (split, re-encode, or supply a valid path) |
| 10 | auth | invalid / revoked `OPENAI_API_KEY` (HTTP 401) | **Stop. Tell the user the key was rejected. Ask them to set a valid key (shell or `.env`). Wait for their confirmation, then re-run the same command.** Do not silently retry with the same key. |
| 11 | permission | model access denied or model not found (HTTP 403/404) | **Stop. Quote the failing model name. Ask the user to either grant model access on their OpenAI project or pick a different model. Wait for confirmation, then re-run with the user-chosen model.** |
| 12 | rate-limit | rate / quota exceeded (HTTP 429) | Tell the user, link `https://platform.openai.com/usage`. Ask explicitly: **wait + retry, or cancel?** Do not auto-wait. |
| 20 | service | network / timeout / 5xx after SDK retries | Tell the user, link `https://status.openai.com`. Ask: **wait + retry, or cancel?** |
| 30 | bad-request | audio format / payload rejected (HTTP 400) | Abort; surface the `Details:` line; ask the user to re-encode the audio or change parameters |

**Default agent behaviour on any non-zero exit** — do not silently retry, fall back to a different model, or skip the step. Surface the `Error [<category>]:` line plus the `Details:` line to the user, then ask exactly:

> "The transcribe step failed with `<category>`: \"<one-line summary>\". Should I wait while you fix it (then retry the same command), or cancel the transcription job?"

On **wait**: pause for the user to say "go", then re-run the exact same `uv run --script ...` invocation. On **cancel**: report the failure clearly and stop the job.

## Anti-patterns

- **Don't paste the API key into chat or commit it.** Export it in the shell, period.
- **Don't request `diarized_json` from a non-diarize model** — the CLI will reject it.
- **Don't pass `--prompt` to `gpt-4o-transcribe-diarize`** — unsupported.
- **Don't send files >25 MB** — split or transcode first.
- **Don't reinvent the CLI inline.** The script handles auth, validation, chunking, and output paths consistently. Use it.
- **Don't run with raw `python3`.** Deps are declared in PEP 723 metadata; only `uv run --script` resolves them. Using `python3` directly will fail with `ImportError: openai`.
- **Don't `pip install openai` into the system Python.** The PEP 723 cache is managed by uv; manual installs drift and create silent-failure modes.
- **Don't silently retry on auth/permission/bad-request errors.** Exit codes 10, 11, and 30 mean the user has to do something. Surface the failure and wait — re-running the same command without a fix only burns time and confuses the conversation.
