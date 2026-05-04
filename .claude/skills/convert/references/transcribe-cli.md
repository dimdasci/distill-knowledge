# CLI examples

The script lives at `.claude/skills/convert/scripts/transcribe_diarize.py`, relative to the project root. Always invoke with `uv run --script` (the script declares its deps via PEP 723). Run with `--help` for the full flag list.

## Single file, fast text

```bash
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py \
  path/to/audio.wav \
  --out transcript.txt
```

## Diarization with known speakers

```bash
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py \
  meeting.m4a \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --known-speaker "Alice=refs/alice.wav" \
  --known-speaker "Bob=refs/bob.wav" \
  --out-dir tmp/transcribe/meeting
```

## Plain text with language hint

```bash
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py \
  interview.mp3 \
  --response-format text \
  --language en \
  --out interview.txt
```

## Dry run (validate args + print payload, no API call)

```bash
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py \
  audio.wav --dry-run
```

## Calling from another skill (diarized JSON for downstream processing)

```bash
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py \
  "$AUDIO" \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --out-dir "$OUT_DIR"
```

The diarized JSON has its own `segments[]` schema — do not pipe it through `parse_vtt.py`.

## Output shapes

- `text`: plain UTF-8 transcript, no timestamps.
- `json`: `{"text": "..."}` plus model metadata.
- `diarized_json`: `segments[]` with `speaker`, `start`, `end`, `text` fields. Use this whenever speaker attribution matters (e.g. when feeding the `convert` skill).

## Preflight

```bash
uv --version                                              # uv installed?
uv run --script .claude/skills/convert/scripts/transcribe_diarize.py --help  # deps resolve?
```

If `uv --version` fails → run Setup. If `--help` fails with `openai not installed`, surface verbatim — do not `pip install` manually; that defeats PEP 723.

## Error-handling prompt (verbatim — used at runtime)

On non-zero exit, surface the `Error [<category>]:` line plus the `Details:` line, then ask the user:

> "The transcribe step failed with `<category>`: \"<one-line summary>\". Should I wait while you fix it (then retry, possibly with adjusted parameters), or cancel the transcription job?"

On **wait**: pause for the user to say "go", then re-run the same `uv run --script ...` invocation — adjusting parameters (e.g. model name on code 11) only as the user specified, otherwise unchanged. On **cancel**: report the failure clearly and stop the job.

The OpenAI SDK already auto-retries transient connection / 5xx / rate-limit errors before the script exits, so anything reaching the agent has already failed once.
