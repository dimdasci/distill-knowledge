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
metadata:
  author: easybiz
  version: "1.0"
---

# Convert Meeting Recording → Knowledge Markdown

Always emit `outbox/{meeting-slug}/transcript.md`; screenshots inline when useful; `summary.md` + `topics/{slug}.md` only on request. `{meeting-slug}` = `kebab-case-topic-YYYYMMDD`. Never touch `inbox/` or `knowledge/`.

References (load on demand): [output templates](references/output-templates.md) · [ffmpeg](references/ffmpeg.md) · [transcribe API](references/transcribe-api.md) · [transcribe CLI](references/transcribe-cli.md) · [prep audio CLI](references/prep-audio-cli.md) · [chunked transcription](references/chunked-transcription.md) · spot-check helper [`scripts/extract_clip.py`](scripts/extract_clip.py).

## Setup

Scripts run via [`uv`](https://docs.astral.sh/uv/) (PEP 723, no venv). All scripts support `--help` for full flag docs (e.g. `uv run --script scripts/merge_chunks.py --help`).

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

If the audio is **technical / multilingual / mumbled** (engineering call, mixed-language with heavy English jargon, fast-paced cross-talk, thick accents), flag this at Gate 1 and propose the [two-pass text-quality flow](references/chunked-transcription.md#two-pass-text-quality-flow). The diarize-only path produces unusable text on this kind of audio.

| Field | Diarize model | Non-diarize model |
|---|---|---|
| language | `--language` (required) | `--language` (required) |
| speakers | drives model choice + sample step | confirms no diarize needed |
| topic + terms | markdown header; sanity-check after | passed via `--prompt` (keep minimal — see [prompt-hallucination warning](references/transcribe-cli.md#prompt-hallucination-warning)) |

### Steps 1–10

1. **Inventory + probe** inbox media + VTT. When a VTT exists, parse it via [scripts/parse_vtt.py](scripts/parse_vtt.py) into `tmp/prep/<slug>/vtt_cues.json`. Sample cues across the duration and write a short assessment: speaker count vs intake, garble examples, coverage gaps, proper-noun fidelity.
2. **Gate 1** — findings, preprocessing plan, `{meeting-slug}`. When a VTT assessment exists, recommend one of three VTT outcomes (user confirms):

   | Outcome | Step 3 effect | Cleanup-pass effect |
   |---|---|---|
   | **VTT-only** | render VTT directly; skip prep + API | not invoked |
   | **Re-transcribe + VTT reference** | full API path; `merge_chunks.py --vtt` | reads `cross_check_cues`; per-span restore + spelling preference |
   | **Re-transcribe, ignore VTT** | full API path; no `--vtt` | standard |

   Also at Gate 1 — propose **single-pass** (diarize only) or **two-pass** (diarize skeleton + non-diarize clean text on full audio + LLM merge). Default to single-pass for clear conversational audio; switch to [two-pass](references/chunked-transcription.md#two-pass-text-quality-flow) if intake flagged technical / multilingual / mumbled.

3. **Preprocess + transcribe.** Run [scripts/prep_audio.py](scripts/prep_audio.py) on the input file (audio or video — it extracts the audio track in-pass via `-vn`; the source video is preserved for Step 6 screenshots). See [prep audio CLI](references/prep-audio-cli.md).

   - **Short (≤18 min stripped):** single `transcribe_diarize.py` call on `stripped.ogg`.
   - **Long (>18 min stripped):** per-chunk loop — invoke `transcribe_diarize.py --manifest --chunk-index N` for each chunk; report progress to user between chunks ("chunk 2/3 done in 251 s, ~4 min remaining"). Then `merge_chunks.py` (with `--vtt` iff Gate 1 chose "Re-transcribe + VTT reference"). See [chunked transcription](references/chunked-transcription.md).

   On non-zero exit follow [Error handling](#error-handling), surface verbatim, **wait before retrying**, never fall back silently. See [transcribe CLI](references/transcribe-cli.md) for full command examples.

4. **Speaker labelling** (after diarized transcription, before cleaned transcript):
   1. Run [scripts/render_transcript.py](scripts/render_transcript.py) `--samples <json>` — show the user the longest 1–2 substantive segments per detected speaker.
   2. User names speakers (or confirms `A`/`B`/`C` if no preference).
   3. **Short path:** Run [scripts/render_transcript.py](scripts/render_transcript.py) `<json> --speakers A=Name1,B=Name2 --out outbox/{meeting-slug}/transcript.md` — emits the cleaned transcript with speaker labels, dropping hallucinations and empty turns.
   4. **Long path (after `merge_chunks.py`):** Cleanup pass — **you do this directly as language work**, not a Python script. Read `merged.json` (and, in two-pass mode, the parallel `clean_full.txt`) and write `polished.json` yourself in one pass. See [Cleanup Pass](references/chunked-transcription.md#cleanup-pass-step-44). Then render `polished.json` via `render_transcript.py`.
5. **Cleaned transcript (mandatory)** — produced by step 4.3 or 4.4 above. For the exact markdown shape, see [output templates § transcript.md](references/output-templates.md#step-4--transcriptmd-shape). Faithful to **meaning**, not to ASR letters: repair garbled spans where the speaker's intent is recoverable from context or a parallel clean pass; never invent content. See [fidelity rule](#fidelity-rule).
6. **Screenshots inline** — skip if no screen content; else `timestamp + 2 s`, `-q:v 2`, inline at cue. Source video path from `manifest.json` `source` field. For inline link format, see [output templates § screenshots](references/output-templates.md#step-5--screenshots--inline-link-shape).
7. **Gate 2** — structured docs or transcript only?
8. **Plan structure** — topics, decisions, actions, open questions, pain points, proposals.
9. **Gate 3 + emit** `summary.md`, `topics/{slug}.md` (default/process), Mermaid for flow/decision shots.
10. **Report** + stop.

## Decision rules

| Situation | Decision |
|---|---|
| VTT exists + Gate 1 → VTT-only | Parse VTT, render directly, skip prep + API |
| VTT exists + Gate 1 → Re-transcribe + VTT reference | Full API path; `merge_chunks.py --vtt` |
| VTT exists + Gate 1 → Re-transcribe, ignore VTT | Full API path; no `--vtt` |
| Audio is technical / multilingual / mumbled | [Two-pass flow](references/chunked-transcription.md#two-pass-text-quality-flow): diarize per chunk (skeleton) + non-diarize on full `stripped.ogg` (clean text) + LLM merge |
| Stripped duration >18 min | Diarize pass: split into balanced chunks ≤18 min each. Two-pass text pass: full audio (no chunking — one continuous output) |
| Stripped audio >25 MB | Re-encode to lower bitrate before sending to API (Opus 32k mono ≈ 240 KB/min, so 25 MB ≈ 100 min) |
| Inbox is video, transcription needed | Run `prep_audio.py` on the video file directly; audio track extracted in-pass; original video retained for Step 6 |
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
| 1 | `gpt-4o-transcribe` | yes (vocab list + 1-line topic only — see [prompt-hallucination warning](references/transcribe-cli.md#prompt-hallucination-warning)) | required | no |
| 2+ | `gpt-4o-transcribe-diarize` | rejected by API | required | yes |
| 2+, technical/mumbled | both: diarize for skeleton + `gpt-4o-transcribe` (full audio, minimal prompt) for text + LLM merge | minimal prompt only on text pass | required | skeleton only |

## Error handling

CLI exits non-zero with stderr `Error [<category>]: <message>`. SDK already retried transient errors. For the full exit-code table and per-category recovery actions, see [transcribe CLI § exit codes](references/transcribe-cli.md#exit-codes).

**Default on non-zero exit** — surface `Error [<category>]:` + `Details:`, then ask:

> "The transcribe step failed with `<category>`: \"<one-line summary>\". Should I wait while you fix it (then retry, possibly with adjusted parameters), or cancel the transcription job?"

**wait**: pause until "go", re-run same command (adjust only what user said). **cancel**: report, stop.

## Fidelity rule

The transcript captures **what was said and meant**, not the literal sound stream. Apply in this order:

1. **Preserve every substantive turn** — every claim, decision, question, objection, reaction. If the speaker said it, it must appear (even if you reword for readability).
2. **Repair recoverable ASR garble** — when the diarize ASR returns gibberish ("вот эта разрастение прям конфет", "Артагамария", "Раил университет") and the speaker's intent is recoverable from a parallel clean pass or surrounding context, replace it with the faithful version. This is selecting the better evidence, not paraphrasing.
3. **Drop fabrications** — non-diarize models with `--prompt` may invent content during silent / unclear stretches (formulaic sentences, names from the prompt, AI-style summaries). If a sentence introduces a concept absent from any source's signal, drop it.
4. **Never invent.** Don't fill silences with plausible-sounding speech, even if it would smooth the read.

When in doubt: when two transcripts of the same audio agree on the meaning, that meaning is faithful even if neither is verbatim. When they disagree and neither is recoverable, mark the span unclear rather than guessing.

## Anti-patterns

- **Don't fabricate.** Inventing dialog the speaker didn't say is the worst failure mode of this skill — worse than a garbled transcript. Repairing recoverable garble is fine; inventing is not. See [fidelity rule](#fidelity-rule).
- **Don't write language-processing scripts or ad-hoc renderers.** When you find yourself reaching for `difflib.SequenceMatcher`, word-overlap thresholds, regex tables, jq, sed, or awk to do the cleanup pass or render output — stop. The cleanup pass is **language work that you perform directly**. Rendering goes through [scripts/render_transcript.py](scripts/render_transcript.py). Python scripts in this skill are I/O plumbing only — never semantic work.
- **Don't load a rich `--prompt` on the non-diarize model.** Anything in the prompt may surface as fabricated dialog during silent / unclear audio. Keep prompts to a vocabulary list + a 1-line topic. See [prompt-hallucination warning](references/transcribe-cli.md#prompt-hallucination-warning).
- **Don't auto-pick VTT decisions or override API speaker labels.** Always surface VTT assessment and let the user confirm at Gate 1. VTT text may restore gaps, but VTT speaker labels never override API-assigned ones.
- **Don't write outside `outbox/{meeting-slug}/`.** Temporary files go in `tmp/`; final artifacts go in `outbox/`.
