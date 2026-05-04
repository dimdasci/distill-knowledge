---
name: convert
description: >-
  Transcribe and extract knowledge from audio or video recordings — meetings,
  interviews, calls, voice notes, conference recordings. Produces a clean,
  speaker-labeled transcript and optionally structured topic documents with
  screenshots from screen-share. Use when the user has a recording and wants
  a transcript, meeting notes, speaker attribution, or a written summary of
  what was discussed — even if they just say "process this recording" or
  "what did we talk about in this call."
compatibility: Requires uv, ffmpeg, ffprobe, Python ≥3.10, and OPENAI_API_KEY (network access to OpenAI API)
---

# Convert Meeting Recording → Knowledge Markdown

Always emit `outbox/{meeting-slug}/transcript.md`; screenshots inline when useful; `summary.md` + `topics/{slug}.md` only on request. `{meeting-slug}` = `kebab-case-topic-YYYYMMDD`. Never touch `inbox/` or `knowledge/`.

References (load on demand): [output templates](references/output-templates.md) · [ffmpeg](references/ffmpeg.md) · [transcribe API](references/transcribe-api.md) · [transcribe CLI](references/transcribe-cli.md).

## Setup

Scripts run via [`uv`](https://docs.astral.sh/uv/) (PEP 723, no venv).

1. **`uv`:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Verify `ffmpeg` + `ffprobe`:**
   ```bash
   command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && ffmpeg -version | head -1
   ```
   Prints version → continue. Else **do not auto-install**; ask:
   > "ffmpeg required, not on PATH. Install for you, or yourself? (**auto** / **manual**)"

   **auto** — detect OS, confirm, run matching install, re-run detect, proceed only on success. See [ffmpeg reference](references/ffmpeg.md) for per-OS commands.

   **manual** — https://ffmpeg.org/download.html; on "done", re-run detect.
3. **`OPENAI_API_KEY`** (for transcription): read from process env, else from project `.env`. Either `export OPENAI_API_KEY=sk-...` (wins) or `cp .env.example .env` and paste (gitignored). Key at https://platform.openai.com/api-keys. Never paste in chat; never commit `.env`.

## Workflow

### Step 0: Intake (mandatory — before any preflight or API call)

Ask the user verbatim:

> "Before I process this, three quick things:
> 1. Language of the conversation? (e.g. en, ru, fr — used as `--language` hint)
> 2. How many speakers?
> 3. Topic / domain in one line, plus any proper names or specialized terms."

Record answers. Use sensible defaults if the user skips a field, but **never silently transcribe without asking**.

| Field | Diarize model | Non-diarize model |
|---|---|---|
| language | `--language` (required) | `--language` (required) |
| speakers | drives model choice + sample step | confirms no diarize needed |
| topic + terms | markdown header; sanity-check after | passed via `--prompt` |

### Steps 1–10

1. **Inventory + probe** inbox media + VTT.
2. **Gate 1** — findings, preprocessing plan, `{meeting-slug}`.
3. **Preprocess** what Gate 1 approved (convert, audio extract, VTT parse, re-transcribe + diarize, screen probe). Re-transcription uses [scripts/transcribe_diarize.py](scripts/transcribe_diarize.py); on non-zero exit follow [Error handling](#error-handling), surface verbatim, **wait before retrying**, never fall back silently. See [transcribe CLI](references/transcribe-cli.md) for full command examples.
4. **Speaker labelling** (after diarized transcription, before cleaned transcript):
   1. Run [scripts/render_transcript.py](scripts/render_transcript.py) `--samples <json>` — show the user the longest 1–2 substantive segments per detected speaker.
   2. User names speakers (or confirms `A`/`B`/`C` if no preference).
   3. Run [scripts/render_transcript.py](scripts/render_transcript.py) `<json> --speakers A=Name1,B=Name2 --out outbox/{meeting-slug}/transcript.md` — emits the cleaned transcript with speaker labels, dropping hallucinations and empty turns.
5. **Cleaned transcript (mandatory)** — produced by step 4.3 above. Cue: `**Alice** [0:00:12]: ...`. Faithful, never paraphrased.
6. **Screenshots inline** — skip if no screen content; else `timestamp + 2 s`, `-q:v 2`, inline at cue.
7. **Gate 2** — structured docs or transcript only?
8. **Plan structure** — topics, decisions, actions, open questions, pain points, proposals.
9. **Gate 3 + emit** `summary.md`, `topics/{slug}.md` (default/process), Mermaid for flow/decision shots.
10. **Report** + stop.

## Decision rules

| Situation | Decision |
|---|---|
| VTT speakers usable | Parse VTT, skip re-transcribe |
| VTT generic / garbled | Re-transcribe + diarize |
| Video unreadable / wrong container | Convert first |
| Probe: only faces | Zero screenshots |
| Probe: UI / slides / docs | Screenshots in scope |
| Meeting < 5 min | Summary only, skip topic split |
| Diagram / flowchart on screen | Screenshot **and** Mermaid |
| Data table on screen | Screenshot **and** markdown table |
| Non-English (FR/DE in LU) | Read VTT directly; auto detection won't fire |

### Transcription model choice

| Speakers | Model | `--prompt`? | `--language` | Diarize |
|---|---|---|---|---|
| 1 | `gpt-4o-transcribe` | yes (names + terms) | required | no |
| 2+ | `gpt-4o-transcribe-diarize` | rejected by API | required | yes |

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

**wait**: pause until "go", re-run same command (adjust only what user said). **cancel**: report, stop.

## Anti-patterns

- **Don't skip the cleaned transcript.** Never optional.
- **Don't paraphrase.** Clean punctuation, merge same-speaker runs; never reword.
- **Don't write outside `outbox/{meeting-slug}/`.**
- **Don't structure without approval** (Gate 2 + Gate 3).
- **Don't screenshot everything.** Visual must add what text doesn't.
- **Don't transcribe a usable VTT.** Cheapest source of truth.
- **Don't fabricate screen content.** Unclear → mark it.
- **Don't run the next skill.** Stop after Step 10.
- **Don't transcribe before intake** (language / speakers / topic / terms).
- **Don't write ad-hoc renderers** (jq / sed / awk / inline scripts) — use [scripts/render_transcript.py](scripts/render_transcript.py).
- **Don't paste the API key in chat or commit it.**
- **Don't request `diarized_json` from a non-diarize model** — rejected.
- **Don't pass `--prompt` to the diarize model** — unsupported.
- **Don't send files >25 MB** — split or transcode first.
- **Don't run with `python3`** — PEP 723 deps need `uv run --script`.
