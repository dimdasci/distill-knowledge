# Chunked Transcription Reference

## Overview

When `prep_audio.py` splits a recording into chunks (stripped duration > 18 min), the pipeline becomes:

1. `prep_audio.py` → `stripped.ogg` + `chunks/*.ogg` + `manifest.json`
2. Per-chunk loop: `transcribe_diarize.py --manifest` (agent reports progress between chunks)
3. `merge_chunks.py` → `merged.json`
4. **Cleanup pass — you do this directly as language work.** Read `merged.json` (and, for two-pass jobs, the parallel clean text) and emit the corrected JSON yourself in one pass. Not a Python script. See [Cleanup Pass](#cleanup-pass-step-44).
5. `render_transcript.py` → `transcript.md`

For technical / multilingual / mumbled audio where the diarize model alone produces unusable text, see [Two-pass text-quality flow](#two-pass-text-quality-flow).

## Resume / retry contract

A chunk is "needs work" iff its manifest `status != "done"`. Possible values
written by `transcribe_diarize.py`:

| `status` | Meaning |
|---|---|
| `pending` | Set by `prep_audio.py`. Never transcribed. |
| `in_progress` | Transcription started; the script exited before writing `done` (success path) — likely an error. The chunk's `request_id` is set. |
| `done` | Transcript written and `transcript_file` populated. |

On any failure the script exits with the matching error code (see
[transcribe-cli.md](transcribe-cli.md)) and **does not** write `failed` to the
manifest — the stderr `Error [<category>]:` line is the source of truth. To
resume after a failure, the agent re-invokes `transcribe_diarize.py
--manifest --chunk-index N` for every chunk where `status != "done"`. Already
`done` chunks are not re-transcribed.

`transcript_file` paths in the manifest are stored **relative to the manifest's parent directory** so the working dir is portable. `merge_chunks.py` resolves them against `manifest_path.parent`.

## merge_chunks.py CLI

```bash
uv run --script scripts/merge_chunks.py \
  --manifest tmp/prep/<slug>/manifest.json \
  --intake '{"speaker_count":2,"speaker_names":["Alice","Bob"],"topic":"Onboarding review","terms":["payroll","PandaDoc"]}' \
  --out tmp/prep/<slug>/merged.json

# With VTT cross-check (when Gate 1 chose "Re-transcribe + VTT reference"):
uv run --script scripts/merge_chunks.py \
  --manifest tmp/prep/<slug>/manifest.json \
  --intake '{"speaker_count":2,"speaker_names":["Alice","Bob"],"topic":"...","terms":[]}' \
  --vtt tmp/prep/<slug>/vtt_cues.json \
  --out tmp/prep/<slug>/merged.json
```

## Timestamp convention

All `start` / `end` fields in `merged.json` are **absolute seconds on the
global timeline** (not chunk-relative). `merge_chunks.py` rewrites the
chunk-relative timestamps from `transcribe_diarize.py` outputs into absolute
values during merge. The cleanup pass MUST preserve this convention in
`polished.json` so `render_transcript.py` produces correct global timestamps.

## merged.json schema

```json
{
  "version": 1,
  "language": "fr",
  "intake_context": {
    "speaker_count": 2,
    "speaker_names": ["Alice", "Bob"],
    "topic": "Onboarding flow review",
    "terms": ["payroll", "Maude", "PandaDoc"]
  },
  "segments": [
    {
      "start": 12.4,
      "end": 18.7,
      "speaker": "A",
      "text": "...",
      "source_chunk": 0,
      "in_overlap": null
    }
  ],
  "chunk_boundaries": [
    {"index": 0, "core_end_s": 974.0, "shared_region": [944.0, 1004.0]}
  ],
  "overlap_windows": [
    {
      "boundary_idx": 0,
      "shared_region": [944.0, 1004.0],
      "left": [/* chunk 0 segments in shared region */],
      "right": [/* chunk 1 segments in shared region */]
    }
  ],
  "cross_check_cues": [/* present only with --vtt */]
}
```

## Cleanup Pass (Step 4.4)

**This is language work you perform directly. Not a Python script.**

The cleanup pass is language work. You (the agent executing this skill) read `merged.json` plus any parallel sources (clean-text pass, VTT cues) and emit the corrected JSON directly in one pass. Word-overlap heuristics, sentence regex, stopword tables, term-spelling regex — all wrong tools. See the [`Don't write language-processing scripts`](../SKILL.md#anti-patterns) anti-pattern.

### Inputs

- `merged.json` — diarized JSON with timestamps, speakers, garbled ASR text
- (Optional, two-pass mode) `clean_full.txt` — non-diarize transcribe output of the full stripped audio with a minimal prompt; better text quality, possibly with a few hallucinations
- (Optional, VTT mode) `vtt_cues.json` — produced by `parse_vtt.py`

### What the agent does

In one pass, reading the inputs holistically:

1. **Remap speaker labels across chunks.** `overlap_windows[]` shows the same audio span on both sides of a chunk boundary. If chunk 1's "B" matches chunk 0's "A" semantically, swap chunk 1's labels.
2. **Drop ASR debris and fabrications.** Single-character ghost segments, silence-induced subtitle phrases ("Спасибо за просмотр"), labels above the intake speaker count, and (in two-pass mode) sentences from the clean pass that introduce concepts absent from the diarize signal — all dropped.
3. **Repair garbled spans.** When the diarize text is ASR gibberish ("Артагамария", "Раил университет", transliterated tech terms) and the speaker's intent is recoverable from the clean pass or surrounding context, replace it with the faithful version. **This is not paraphrasing — it's selecting the better evidence of what was said.** See the [fidelity rule](../SKILL.md#fidelity-rule).
4. **Reconstruct cross-talk.** From side-by-side `overlap_windows` into readable sequential turns; preserve who said what.
5. **Consolidate over-fragmented turns.** Same speaker, sub-second gap, same thought → one turn.
6. **Smooth boundary stitches.** Where a sentence got cut at `core_end_s`, glue the halves.
7. **Resolve tech-term spelling** against `intake_context.terms` (Latin proper nouns: NestJS, Postgres, Render, S3, KYC; loanwords stay Cyrillic when natural in the speaker's register).
8. **VTT restore** (when `cross_check_cues` present) — on API gaps (empty / sub-5-char span where VTT cue is substantive); VTT spelling preference for proper nouns in terms.

### Output

`polished.json` with the same `segments[]` schema as `merged.json`. Drop the `in_overlap` and `source_chunk` fields if you want; keep `start` / `end` / `speaker` / `text`. Render with `render_transcript.py`.

`edits.json` is **optional**, not required. If you produce one for audit purposes, log substantive replacements (garble-repair, hallucination-drop, label-remap) — skip the long tail of consolidations and spelling fixes. Don't let the schema turn the cleanup into a bookkeeping exercise.

### Constraints

- **Preserve every substantive turn.** Decisions, claims, questions, objections, reactions — they all stay. Even when a turn is reworded for readability, its meaning must survive intact.
- **Don't invent.** When neither source has signal for a span, leave it empty / mark unclear. Don't generate plausible-sounding dialog to fill the gap.
- **Don't reorder.** Segments stay in timeline order; cross-talk reconstruction is local to one overlap window.
- **Timestamps come from source segments.** Don't synthesize new ones.
- **VTT speaker labels never override API ones.** VTT text may restore gaps; VTT speakers don't.

### Suggested prompt (when invoking via Anthropic SDK rather than inline)

```
You are merging transcripts of the same audio. Inputs:
  - merged.json: diarized JSON with timestamps + speakers + garbled ASR text.
  - (optional) clean_full.txt: non-diarized clean text of the same audio,
    fluent but may contain fabrications from a prompted run.

Output a JSON list of segments preserving merged.json's skeleton (speaker,
start, end), with text drawn from the clean pass where it faithfully
represents the meaning of the dirty segment, falling back to the dirty text
(with light tech-term spelling fixes) where the clean pass invented content
or skipped the turn. Drop sentences that introduce concepts absent from any
nearby diarize segment. Preserve every substantive turn the speaker made.

Output JSON only, no commentary.
```

## Two-pass text-quality flow

Use when the audio is technical, multilingual, mumbled, or otherwise produces unusable text from the diarize-only path. Typical signal at Gate 1: the user describes the audio as "Russian devspeak", "engineering call with English jargon", "thick accent + fast pace", or the user previously got a poor result from a single-pass run.

### When to use

- Russian, French, German, etc. with heavy English technical vocabulary mixed in
- Engineering / architecture / domain-specific calls
- Multiple speakers talking over each other
- Any case where the user has rejected a diarize-only transcript as too garbled

When in doubt, ask the user at Gate 1.

### Pipeline

1. **Pass 1 — diarize for skeleton** (per chunk, as standard). Produces speaker labels + timestamps. Text quality may be poor.
2. **Pass 2 — non-diarize for text** on the **full `stripped.ogg`**, not chunked.
   - Why full audio: the model produces more fluent prose with continuous context, and a single output avoids the chunk-overlap duplication artifact (each chunk's output covers the ~30s overlap region, so chunked text passes produce duplicated content at boundaries).
   - File size check: `stripped.ogg` for a 22-min meeting is ~5 MB; the OpenAI 25 MB limit comfortably covers ~90 min. For longer recordings, transcode to lower bitrate first.
   - Use a **minimal prompt**: vocabulary list + 1-line topic. Avoid summaries, lists of names, example phrases — they leak into the output. See [prompt-hallucination warning](transcribe-cli.md#prompt-hallucination-warning).
3. **Merge — you do this directly in one pass.** Read both `merged.json` and `clean_full.txt`, emit the merged transcript yourself per the [Cleanup Pass](#cleanup-pass-step-44) above.

```bash
# Pass 1 (per chunk, as usual)
uv run --script scripts/transcribe_diarize.py \
  tmp/prep/<slug>/chunks/chunk_00.ogg \
  --model gpt-4o-transcribe-diarize --response-format diarized_json \
  --language ru --manifest tmp/prep/<slug>/manifest.json \
  --chunk-index 0 --out-dir tmp/prep/<slug>/transcripts
# (repeat for chunk 1, …)

uv run --script scripts/merge_chunks.py \
  --manifest tmp/prep/<slug>/manifest.json \
  --intake '{...}' \
  --out tmp/prep/<slug>/merged.json

# Pass 2 (one call on full stripped audio)
uv run --script scripts/transcribe_diarize.py \
  tmp/prep/<slug>/stripped.ogg \
  --model gpt-4o-transcribe --response-format text \
  --language ru \
  --prompt "Terms: NestJS, Fastify, Postgres, Render, Railway, KYC. Names: Alice, Bob. Topic: backend architecture." \
  --out tmp/prep/<slug>/clean_full.txt

# Merge → cleanup pass: agent reads merged.json + clean_full.txt and produces polished.json
# (you perform the merge directly, no Python alignment script)
```

## Worked Example

### 45-minute meeting (3 chunks), single-pass

```
$ uv run --script scripts/prep_audio.py inbox/workshop.m4a --out-dir tmp/prep/workshop-20260504
Manifest: tmp/prep/workshop-20260504/manifest.json
Chunks: 3
Stripped duration: 2695.2s

$ # Per-chunk transcription (agent loop)
$ uv run --script scripts/transcribe_diarize.py \
    tmp/prep/workshop-20260504/chunks/chunk_00.ogg \
    --model gpt-4o-transcribe-diarize --response-format diarized_json \
    --language en --manifest tmp/prep/workshop-20260504/manifest.json \
    --chunk-index 0 --out-dir tmp/prep/workshop-20260504/transcripts
[request] X-Client-Request-Id: abc123...
[done] elapsed_s=127.3 request_id=abc123...
Wrote tmp/prep/workshop-20260504/transcripts/chunk_00.transcript.json

$ # (repeat for chunks 1, 2)

$ uv run --script scripts/merge_chunks.py \
    --manifest tmp/prep/workshop-20260504/manifest.json \
    --intake '{"speaker_count":3,"speaker_names":["A","B","C"],"topic":"Workshop","terms":["Kubernetes","ArgoCD"]}' \
    --out tmp/prep/workshop-20260504/merged.json
Wrote tmp/prep/workshop-20260504/merged.json

$ # Cleanup pass — you read merged.json and write polished.json directly (language work, not a script).
$ uv run --script scripts/render_transcript.py \
    tmp/prep/workshop-20260504/polished.json \
    --speakers "A=Sarah,B=Mike,C=Lisa" \
    --out outbox/workshop-20260504/transcript.md
Wrote outbox/workshop-20260504/transcript.md
```
