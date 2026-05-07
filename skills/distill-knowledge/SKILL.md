---
name: distill-knowledge
description: >-
  Transcribe existing audio/video recordings into speaker-labeled markdown
  transcripts. Handles meetings, interviews, calls, voice notes. Optionally
  extracts screenshots from screen-share and produces structured topic
  documents. Use when user has a recording file and wants a transcript, notes,
  or summary — even if they just say "process this" or drop a file. Not for
  audio editing, format conversion, or live captions.
compatibility: Requires uv, ffmpeg, ffprobe, Python ≥3.10, and OPENAI_API_KEY (network access to OpenAI API)
license: MIT
metadata:
  author: Dim Kharitonov <dimds@fastmail.com> (https://github.com/dimdasci)
  version: "1.0.0"
---

# Convert Recording → Knowledge Markdown

Emit `outbox/{meeting-slug}/transcript.md`; screenshots inline when useful; structured docs only on request. `{meeting-slug}` = `kebab-case-topic-YYYYMMDD`. Never touch `inbox/` or `knowledge/`.

References (load on demand): [setup](references/setup.md) · [output templates](references/output-templates.md) · [ffmpeg](references/ffmpeg.md) · [transcribe CLI](references/transcribe-cli.md) · [prep audio CLI](references/prep-audio-cli.md) · [chunked transcription](references/chunked-transcription.md) · [structured docs](references/structured-docs.md) · spot-check: [`scripts/extract_clip.py`](scripts/extract_clip.py).

Scripts run via `uv run --script` (PEP 723). All support `--help`. On first run verify [setup prerequisites](references/setup.md).

## Workflow

### Step 0 — Intake (mandatory, before any API call)

Ask verbatim:

> "Before I process this, three quick things:
> 1. Language of the conversation? (e.g. en, ru, fr — used as `--language` hint)
> 2. How many speakers?
> 3. Topic / domain in one line, plus any proper names or specialized terms."

Record answers; sensible defaults if user skips a field. **Never silently transcribe without asking.**

Technical / multilingual / mumbled audio → VTT-aligned path strongly preferred (if VTT available). Without VTT, diarize fallback with 8-min chunks; warn user about quality.

### Steps 1–6

1. **Inventory + probe** — `ls` inbox, `ffprobe` media. VTT present → parse via [parse_vtt.py](scripts/parse_vtt.py) → `tmp/prep/<slug>/vtt_cues.json`; sample cues, assess quality (speaker count, garble, gaps, proper-noun fidelity). Non-English VTTs: screen-reference detection won't fire — read cues directly.

2. **Gate 1** — present findings + plan + `{meeting-slug}`. Determine transcription path:

   | Scenario | Path |
   |---|---|
   | VTT good quality | Render VTT directly; skip prep + API |
   | VTT exists, text garbled | **VTT-aligned retranscription**: VTT as skeleton (speakers + timestamps) + `gpt-4o-transcribe` for text quality → agent aligns |
   | No VTT, single speaker | `gpt-4o-transcribe` directly |
   | No VTT, multi-speaker | Diarize fallback: `gpt-4o-transcribe-diarize` at 8-min chunks (known unstable — warn user) |

3. **Preprocess + transcribe** — run [prep_audio.py](scripts/prep_audio.py) on input (audio or video; extracts audio in-pass; source video retained for screenshots).

   **VTT-aligned path** (primary for retranscription):
   - VTT provides speaker labels + turn timestamps; transcription provides clean text
   - Run `gpt-4o-transcribe` on `stripped.ogg` (or per-chunk if >8 min) with `--prompt` (vocab + 1-line topic only)
   - Agent aligns clean text to VTT turns — this is **language work you perform directly**. Match transcribed text to VTT turn boundaries using VTT text as positional guide. Preserve VTT speaker labels and timestamps. See [VTT-aligned merge](references/chunked-transcription.md#vtt-aligned-merge).

   **Single-speaker path:**
   - Run `gpt-4o-transcribe` on `stripped.ogg` (or per-chunk if >8 min) with `--prompt`
   - Output is the transcript directly; no alignment needed

   **Diarize fallback** (no VTT, multi-speaker):
   - Chunks at 8 min max (diarize model unstable on longer audio)
   - Per-chunk: `transcribe_diarize.py --manifest --chunk-index N`; then `merge_chunks.py`
   - Warn user: diarization quality is unreliable; may need manual correction
   - See [chunked transcription](references/chunked-transcription.md)

   All paths: `--language` required. On non-zero exit → surface stderr `Error [<category>]:`, ask wait/cancel. See [exit codes](references/transcribe-cli.md#exit-codes).

4. **Speaker labelling** —
   - **VTT-aligned:** speakers come from VTT; confirm with user (VTT labels may be generic like "Speaker 1").
   - **Diarize fallback:** `render_transcript.py --samples <json>` → user names speakers.
   - **Single-speaker:** user provides name or default.
   - Then render via `render_transcript.py --speakers ... --out outbox/{slug}/transcript.md`.
   - For diarize long path: cleanup pass as **language work** on `merged.json` → `polished.json`. See [Cleanup Pass](references/chunked-transcription.md#cleanup-pass-step-44).

5. **Transcript** (mandatory artifact) — produced by step 4. For exact markdown shape see [output templates § transcript.md](references/output-templates.md#step-4--transcriptmd-shape). Faithful to **meaning**; repair recoverable garble; never invent. See [Fidelity rule](#fidelity-rule).

6. **Screenshots** — skip if no screen content (faces only → zero screenshots). Take frame at `timestamp + 2s`, `-q:v 2`. Source video from `manifest.json` `source` field. For format see [output templates § screenshots](references/output-templates.md#step-5--screenshots--inline-link-shape).
   - UI / slides / docs → screenshots in scope
   - Diagram on screen → screenshot **and** Mermaid
   - Data table → screenshot **and** markdown table

### Steps 7–10 — Structured docs (conditional)

**Gate 2** — ask: structured docs or transcript only? If transcript only → report + stop.

Otherwise → [structured docs reference](references/structured-docs.md): plan topics, emit `summary.md` + `topics/{slug}.md`, report, stop.

## Fidelity rule

Transcript captures **what was said and meant**, not the literal sound stream. In priority order:

1. **Preserve every substantive turn** — decisions, claims, questions, objections, reactions. If spoken, it appears.
2. **Repair recoverable garble** — when ASR returns gibberish and intent is recoverable from parallel clean pass or context, replace with faithful version. Selecting better evidence ≠ paraphrasing.
3. **Drop fabrications** — sentences introducing concepts absent from any source signal (prompted model hallucinations during silence).
4. **Never invent** — don't fill silences with plausible speech.

When two transcripts agree on meaning → faithful. When they disagree and neither is recoverable → mark unclear.

## Anti-patterns

- **Don't fabricate.** Inventing dialog is the worst failure mode — worse than garble. See [fidelity rule](#fidelity-rule).
- **Don't write language-processing scripts.** No `difflib`, regex tables, word-overlap heuristics, jq/sed/awk for cleanup. The cleanup pass is **language work you perform directly**. Scripts = I/O plumbing only.
- **Don't load rich `--prompt`** on non-diarize model. Prompts leak as fabrications. Vocab list + 1-line topic max. See [prompt-hallucination warning](references/transcribe-cli.md#prompt-hallucination-warning).
- **Don't auto-pick VTT decisions.** Always surface assessment; user confirms at Gate 1.
- **Don't write outside `outbox/{meeting-slug}/`.** Temp files → `tmp/`; finals → `outbox/`.
