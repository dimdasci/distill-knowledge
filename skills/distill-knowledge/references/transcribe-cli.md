# CLI examples

The script lives at `scripts/transcribe_diarize.py` (relative to the skill root). Always invoke with `uv run --script` (the script declares its deps via PEP 723). Run with `--help` for the full flag list.

## Single file, fast text

```bash
uv run --script scripts/transcribe_diarize.py \
  path/to/audio.wav \
  --out transcript.txt
```

## Diarization with known speakers

```bash
uv run --script scripts/transcribe_diarize.py \
  meeting.m4a \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --known-speaker "Alice=refs/alice.wav" \
  --known-speaker "Bob=refs/bob.wav" \
  --out-dir tmp/transcribe/meeting
```

## Plain text with language hint

```bash
uv run --script scripts/transcribe_diarize.py \
  interview.mp3 \
  --response-format text \
  --language en \
  --out interview.txt
```

## Dry run (validate args + print payload, no API call)

```bash
uv run --script scripts/transcribe_diarize.py \
  audio.wav --dry-run
```

## Calling from another skill (diarized JSON for downstream processing)

```bash
uv run --script scripts/transcribe_diarize.py \
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

## Prompt-hallucination warning

The non-diarize model (`gpt-4o-transcribe`) accepts `--prompt` and produces noticeably more fluent, term-correct text — at a cost. **Anything in the prompt may be regurgitated as fabricated dialog when the audio is silent, mumbled, or unclear.** This is a known failure mode, not a bug.

Observed leakage from a meeting test where the prompt mentioned domain terms (`payroll`, `EasyBiz`, `RDS`, `Supabase`, `Petya`) and a one-paragraph topic summary:

| Prompt content | Fabricated output |
|---|---|
| "Names: …, Petya, …" | "**Хороший вопрос, Петя.**" (no Petya in the audio) |
| "…modules including payroll…" | "**А что у нас с payroll?**" (payroll never discussed) |
| "Postgres via RDS, Supabase, Neon" | "**Да, мы работаем с NestJS и Fastify, используя Postgres через RDS, Supabase и Neon.**" (formulaic regurgitation) |
| "5 migration concerns: monorepo, infra, …" | "**Мы перейдем к обсуждению как перевести наши системы на модульную архитектуру.**" (boilerplate) |

The model uses prompt content as a fallback distribution during low-confidence audio. The richer the prompt, the more material it has to invent from.

### Rules of thumb

- **Vocabulary list + 1-line topic only.** No paragraph summaries, no lists of every participant, no example phrases of "what was likely said".
- **Names are dangerous.** If you list 7 people in the prompt, expect 1–2 to appear in fabricated turns. Limit to the 2–3 main speakers.
- **Run a verification pass against a parallel diarize transcription** (the [two-pass flow](chunked-transcription.md#two-pass-text-quality-flow)). The agent's cleanup pass drops sentences that introduce concepts absent from the diarize signal — fabrications are detectable because they don't appear on both sides.
- **Never use a prompt-only single-pass run as the final transcript.** Always merge against an unprompted source.

### Diarize model rejects `--prompt`

The diarize model (`gpt-4o-transcribe-diarize`) rejects `--prompt` at the API level. This is a constraint, not a workaround opportunity — there is no "diarize + prompted text" single call. For prompted-text quality with speaker labels, use the two-pass flow.

## Preflight

```bash
uv --version                                              # uv installed?
uv run --script scripts/transcribe_diarize.py --help  # deps resolve?
```

If `uv --version` fails → run Setup. If `--help` fails with `openai not installed`, surface verbatim — do not `pip install` manually; that defeats PEP 723.

## Timeout and resilience flags

```bash
# Override read timeout (default 450s) — useful for known-slow endpoints
uv run --script scripts/transcribe_diarize.py \
  audio.wav --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --timeout 600

# Override wall-clock limit (default 600s) — hard kill if server streams
# bytes without ever completing. Use when API hangs indefinitely.
uv run --script scripts/transcribe_diarize.py \
  audio.wav --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --max-wall 900

# Skip pre-flight model check (offline tests, already verified)
uv run --script scripts/transcribe_diarize.py \
  audio.wav --skip-preflight --dry-run

# Chunked transcription with manifest tracking
uv run --script scripts/transcribe_diarize.py \
  tmp/prep/meeting/chunks/chunk_00.ogg \
  --model gpt-4o-transcribe-diarize \
  --response-format diarized_json \
  --language fr \
  --manifest tmp/prep/meeting/manifest.json \
  --chunk-index 0 \
  --out-dir tmp/prep/meeting/transcripts
```

### Stderr signals

Before each API call:
```
[request] X-Client-Request-Id: 550e8400-e29b-41d4-a716-446655440000
```

After success:
```
[done] elapsed_s=127.3 request_id=550e8400-e29b-41d4-a716-446655440000
```

### Exit codes

| Exit | Category | Meaning |
|---|---|---|
| 0 | success | Transcript written |
| 1 | unknown | Unexpected error |
| 2 | input | File missing / >25 MB / unreadable |
| 10 | auth | Invalid API key (401) |
| 11 | permission | No model access (403/404) |
| 12 | rate-limit | Quota exceeded (429) |
| 20 | service | Network / 5xx — connection failed |
| 21 | timeout | Request accepted, no response within `--timeout` (read gap) or `--max-wall` (total elapsed) |
| 30 | bad-request | Invalid parameters or audio format (400) |

## Error-handling prompt (verbatim — used at runtime)

On non-zero exit, surface the `Error [<category>]:` line plus the `Details:` line, then ask the user:

> "The transcribe step failed with `<category>`: \"<one-line summary>\". Should I wait while you fix it (then retry, possibly with adjusted parameters), or cancel the transcription job?"

On **wait**: pause for the user to say "go", then re-run the same `uv run --script ...` invocation — adjusting parameters (e.g. model name on code 11) only as the user specified, otherwise unchanged. On **cancel**: report the failure clearly and stop the job.

The OpenAI SDK already auto-retries transient connection / 5xx / rate-limit errors before the script exits, so anything reaching the agent has already failed once.
