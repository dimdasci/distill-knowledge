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
  author: dim-kharitonov
  version: "1.0"
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

Technical / multilingual / mumbled audio (engineering calls, mixed-language, thick accents, fast cross-talk) → flag at Gate 1, propose [two-pass flow](references/chunked-transcription.md#two-pass-text-quality-flow).

### Steps 1–6

1. **Inventory + probe** — `ls` inbox, `ffprobe` media. VTT present → parse via [parse_vtt.py](scripts/parse_vtt.py) → `tmp/prep/<slug>/vtt_cues.json`; sample cues, assess quality (speaker count, garble, gaps, proper-noun fidelity). Non-English VTTs: screen-reference detection won't fire — read cues directly.

2. **Gate 1** — present findings + plan + `{meeting-slug}`. VTT assessment → user confirms one of:

   | VTT outcome | Effect |
   |---|---|
   | VTT-only | Render VTT directly; skip prep + API |
   | Re-transcribe + VTT reference | Full API path; `merge_chunks.py --vtt` |
   | Re-transcribe, ignore VTT | Full API path; no `--vtt` |

   Also decide: **single-pass** (diarize only; default for clear audio) or **two-pass** (diarize skeleton + non-diarize clean text + LLM merge; for technical/mumbled). See [two-pass](references/chunked-transcription.md#two-pass-text-quality-flow).

3. **Preprocess + transcribe** — run [prep_audio.py](scripts/prep_audio.py) on input (audio or video; extracts audio in-pass; source video retained for screenshots).
   - ≤18 min stripped → single `transcribe_diarize.py` call on `stripped.ogg`
   - \>18 min → per-chunk loop with `--manifest --chunk-index N`; report progress between chunks; then `merge_chunks.py` (+ `--vtt` iff Gate 1). See [chunked transcription](references/chunked-transcription.md).
   - \>25 MB stripped → re-encode lower bitrate first (Opus 32k mono ≈ 240 KB/min)

   Model choice:

   | Speakers | Model | `--prompt` | Diarize |
   |---|---|---|---|
   | 1 | `gpt-4o-transcribe` | vocab + 1-line topic only | no |
   | 2+ | `gpt-4o-transcribe-diarize` | rejected by API | yes |
   | 2+, technical/mumbled | both: diarize skeleton + `gpt-4o-transcribe` full audio (minimal prompt) + LLM merge | text pass only | skeleton |

   `--language` required on every call. On non-zero exit → surface stderr `Error [<category>]:`, ask wait/cancel. See [exit codes](references/transcribe-cli.md#exit-codes).

4. **Speaker labelling** —
   - `render_transcript.py --samples <json>` → show longest segments per speaker → user names them.
   - **Short path:** `render_transcript.py <json> --speakers A=Name1,B=Name2 --out outbox/{slug}/transcript.md`
   - **Long path (after merge_chunks.py):** cleanup pass — **you do this directly as language work**, not a script. Read `merged.json` (+ `clean_full.txt` in two-pass) and emit `polished.json`. See [Cleanup Pass](references/chunked-transcription.md#cleanup-pass-step-44). Then render via `render_transcript.py`.

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
