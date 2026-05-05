# Chunked Transcription Reference

## Overview

Three transcription paths exist. The first two use `gpt-4o-transcribe` (reliable); the third uses diarization (fallback, unstable).

| Path | When | Pipeline |
|------|------|----------|
| **VTT-aligned** | VTT exists, text quality is bad | VTT skeleton + transcribe chunks → agent aligns |
| **Single-speaker** | No VTT, 1 speaker | Transcribe chunks directly |
| **Diarize fallback** | No VTT, multi-speaker | Diarize at 8-min chunks → merge → cleanup |

When `prep_audio.py` splits a recording (stripped duration > 8 min), it produces `stripped.ogg` + `chunks/*.ogg` + `manifest.json`.

## VTT-aligned merge

**Primary path for retranscription.** The VTT provides structure (speakers, timestamps, turn boundaries); `gpt-4o-transcribe` provides clean text. The agent merges them.

### Pipeline

1. `parse_vtt.py <file.vtt> -o tmp/prep/<slug>/vtt_cues.json`
2. `prep_audio.py <input> --out-dir tmp/prep/<slug>` → `stripped.ogg` + chunks + `manifest.json`
3. Per-chunk transcription (text only, no diarize):
   ```bash
   uv run --script scripts/transcribe_diarize.py \
     tmp/prep/<slug>/chunks/chunk_00.ogg \
     --model gpt-4o-transcribe --response-format text \
     --language <lang> \
     --prompt "Terms: <terms>. Topic: <topic>." \
     --manifest tmp/prep/<slug>/manifest.json \
     --chunk-index 0 --out-dir tmp/prep/<slug>/transcripts
   ```
4. Concatenate chunk transcripts into `clean_full.txt`
5. **Agent aligns** clean text to VTT structure → `polished.json`
6. `render_transcript.py polished.json --speakers ... --out outbox/<slug>/transcript.md`

### VTT-aligned merge (Step 5 — language work)

**This is language work you perform directly. Not a Python script.**

Inputs:
- `vtt_cues.json` — speaker labels + timestamps + low-quality text (positional guide)
- `clean_full.txt` — high-quality continuous text from `gpt-4o-transcribe` (no speakers, no timestamps)

What you do in one pass:

1. **Map clean text onto VTT turns.** Use VTT text as a positional guide — find where each VTT cue's content appears in the clean text. The VTT text is garbled but close enough to locate the corresponding clean passage.
2. **Preserve VTT speaker labels.** The clean text has no speaker info — all attribution comes from VTT.
3. **Preserve VTT timestamps.** Use VTT `start_seconds`/`end_seconds` for each turn.
4. **Repair where clean text is better.** When the VTT says "Артагамария" and the clean text says "architecture", use the clean text. This is the whole point.
5. **Drop fabrications from clean text.** Prompted transcription may invent content during silence. If clean text has sentences with no corresponding VTT cue (no turn exists at that time), drop them.
6. **Consolidate turns.** Same speaker, consecutive VTT cues → merge into one turn (keep earliest timestamp).
7. **Resolve tech-term spelling** against intake terms.

### Output

`polished.json` with segments:
```json
[
  {"start": 12.4, "end": 25.1, "speaker": "Alice", "text": "..."},
  {"start": 25.3, "end": 41.8, "speaker": "Bob", "text": "..."}
]
```

Render with `render_transcript.py`.

### Constraints

- **VTT speakers are authoritative.** Never reassign speaker from clean text (it has none).
- **VTT timestamps are authoritative.** Don't synthesize new ones.
- **Preserve every substantive turn** from VTT. If a VTT cue exists, it maps to spoken content.
- **Don't invent.** If clean text has no match for a VTT cue and the VTT text is unrecoverable, keep VTT text as-is or mark unclear.
- See [fidelity rule](../SKILL.md#fidelity-rule).

---

## Diarize fallback pipeline

Used only when no VTT is available and there are multiple speakers. **Known unstable** — diarize model fails on chunks >8 min. Warn user about quality.

### Pipeline

1. `prep_audio.py` → chunks at 8-min max + `manifest.json`
2. Per-chunk: `transcribe_diarize.py --manifest --chunk-index N` (model: `gpt-4o-transcribe-diarize`, format: `diarized_json`)
3. `merge_chunks.py` → `merged.json`
4. **Cleanup pass** (language work) → `polished.json`
5. `render_transcript.py` → `transcript.md`

### Resume / retry contract

A chunk is "needs work" iff its manifest `status != "done"`. Possible values:

| `status` | Meaning |
|---|---|
| `pending` | Set by `prep_audio.py`. Never transcribed. |
| `in_progress` | Transcription started; script exited before `done`. |
| `done` | Transcript written and `transcript_file` populated. |

On failure: re-invoke `transcribe_diarize.py --manifest --chunk-index N` for every chunk where `status != "done"`. Already-done chunks are not re-transcribed.

`transcript_file` paths are stored **relative to manifest's parent directory**.

### merge_chunks.py CLI

```bash
uv run --script scripts/merge_chunks.py \
  --manifest tmp/prep/<slug>/manifest.json \
  --intake '{"speaker_count":2,"speaker_names":["Alice","Bob"],"topic":"...","terms":[]}' \
  --out tmp/prep/<slug>/merged.json
```

### Timestamp convention

All `start` / `end` fields in `merged.json` are **absolute seconds on the global timeline** (not chunk-relative). The cleanup pass MUST preserve this so `render_transcript.py` produces correct timestamps.

### merged.json schema

```json
{
  "version": 1,
  "language": "fr",
  "intake_context": { "speaker_count": 2, "speaker_names": ["Alice", "Bob"], "topic": "...", "terms": [] },
  "segments": [
    { "start": 12.4, "end": 18.7, "speaker": "A", "text": "...", "source_chunk": 0, "in_overlap": null }
  ],
  "chunk_boundaries": [
    {"index": 0, "core_end_s": 450.0, "shared_region": [420.0, 480.0]}
  ],
  "overlap_windows": [
    { "boundary_idx": 0, "shared_region": [420.0, 480.0], "left": [...], "right": [...] }
  ]
}
```

### Cleanup Pass (diarize fallback only)

**This is language work you perform directly. Not a Python script.**

Read `merged.json` and emit corrected JSON in one pass:

1. **Remap speaker labels across chunks.** `overlap_windows[]` shows the same span on both sides — match speakers semantically.
2. **Drop ASR debris.** Ghost segments, silence-induced subtitles, labels above intake speaker count.
3. **Repair garbled spans** where intent is recoverable from context. See [fidelity rule](../SKILL.md#fidelity-rule).
4. **Reconstruct cross-talk** from overlap windows into sequential turns.
5. **Consolidate turns.** Same speaker, sub-second gap, same thought → one turn.
6. **Smooth boundary stitches.** Sentence cut at `core_end_s` → glue halves.
7. **Resolve tech-term spelling** against `intake_context.terms`.

Output: `polished.json` (same schema, drop `in_overlap`/`source_chunk`). Render with `render_transcript.py`.

### Constraints

- **Preserve every substantive turn.**
- **Don't invent.** Unrecoverable spans → mark unclear.
- **Don't reorder.** Timeline order preserved.
- **Timestamps from source segments.** Don't synthesize.

---

## Worked Example: VTT-aligned (30-min meeting, 4 chunks)

```bash
# Parse VTT
uv run --script scripts/parse_vtt.py inbox/meeting.vtt -o tmp/prep/onboarding-20260505/vtt_cues.json

# Preprocess
uv run --script scripts/prep_audio.py inbox/meeting.mp4 --out-dir tmp/prep/onboarding-20260505
# → Chunks: 4, Stripped: 1823.5s

# Transcribe each chunk (text only, no diarize)
for i in 0 1 2 3; do
  uv run --script scripts/transcribe_diarize.py \
    tmp/prep/onboarding-20260505/chunks/chunk_0${i}.ogg \
    --model gpt-4o-transcribe --response-format text \
    --language ru \
    --prompt "Terms: NestJS, Postgres. Topic: onboarding review." \
    --manifest tmp/prep/onboarding-20260505/manifest.json \
    --chunk-index $i --out-dir tmp/prep/onboarding-20260505/transcripts
done

# Concatenate clean text
cat tmp/prep/onboarding-20260505/transcripts/chunk_0*.transcript.txt > tmp/prep/onboarding-20260505/clean_full.txt

# Agent aligns clean_full.txt to vtt_cues.json → polished.json (language work)

# Render
uv run --script scripts/render_transcript.py \
  tmp/prep/onboarding-20260505/polished.json \
  --speakers "Speaker 1=Dima,Speaker 2=Mark" \
  --out outbox/onboarding-20260505/transcript.md
```

## Worked Example: Diarize fallback (20-min, no VTT)

```bash
# Preprocess (8-min chunks)
uv run --script scripts/prep_audio.py inbox/call.m4a --out-dir tmp/prep/call-20260505
# → Chunks: 3, Stripped: 1195.0s

# Diarize per chunk
for i in 0 1 2; do
  uv run --script scripts/transcribe_diarize.py \
    tmp/prep/call-20260505/chunks/chunk_0${i}.ogg \
    --model gpt-4o-transcribe-diarize --response-format diarized_json \
    --language en \
    --manifest tmp/prep/call-20260505/manifest.json \
    --chunk-index $i --out-dir tmp/prep/call-20260505/transcripts
done

# Merge
uv run --script scripts/merge_chunks.py \
  --manifest tmp/prep/call-20260505/manifest.json \
  --intake '{"speaker_count":2,"speaker_names":["A","B"],"topic":"Sales call","terms":["CRM","Hubspot"]}' \
  --out tmp/prep/call-20260505/merged.json

# Cleanup pass → polished.json (language work)

# Render
uv run --script scripts/render_transcript.py \
  tmp/prep/call-20260505/polished.json \
  --speakers "A=Sarah,B=Client" \
  --out outbox/call-20260505/transcript.md
```
