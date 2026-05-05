# Chunked Transcription Reference

## Overview

When `prep_audio.py` splits a recording into chunks (stripped duration > 18 min), the pipeline becomes:

1. `prep_audio.py` → `stripped.ogg` + `chunks/*.ogg` + `manifest.json`
2. Per-chunk loop: `transcribe_diarize.py --manifest` (agent reports progress between chunks)
3. `merge_chunks.py` → `merged.json`
4. Agent cleanup pass → `polished.json` + `edits.json`
5. `render_transcript.py` → `transcript.md`

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

## Cleanup Pass Contract (Step 4.4)

The agent reads `merged.json` and produces `polished.json` + `edits.json`.

### MUST do

1. **Remap speaker labels across chunks** — read `overlap_windows[]`: same audio span on both sides → same speaker.
2. **Drop hallucinations** — labels not in `intake_context.speaker_count`, silence-induced subtitle phrases, single-character ghost segments.
3. **Reconstruct cross-talk** — from side-by-side `overlap_windows` into readable sequential turns; preserve who said what.
4. **Consolidate over-fragmented turns** — same speaker into natural sentence-length turns.
5. **Smooth boundary stitches** — where a sentence got cut at `core_end_s`.
6. **Resolve ASR variants** — against `intake_context.terms` (use intake spelling).
7. **VTT restore** (when `cross_check_cues` present) — on API gaps (empty / sub-5-char span where VTT cue is substantive); VTT spelling preference for proper nouns in terms.
8. **Log every change** in `edits.json`.

### MUST NOT

- Paraphrase substantive content; reword phrasing that carries meaning.
- Drop a turn that introduces new information, a decision, a question, an objection, or a reaction.
- Invent or modify timestamps; every output `start` / `end` comes from a source segment.
- Reorder events on the timeline; cross-talk reconstruction is local to one overlap window.
- Override API speaker labels with VTT speaker labels.
- Bulk-replace API text with VTT text (restoration is per-span only).

### edits.json schema

```json
[
  {
    "type": "label_remap",
    "at": {"absolute_start": 974.2, "source_chunk": 1},
    "reason": "Overlap window shows chunk-1 speaker B matches chunk-0 speaker A",
    "before": "B",
    "after": "A"
  },
  {
    "type": "hallucination_drop",
    "at": {"absolute_start": 1200.5, "source_chunk": 1},
    "reason": "Single-char ghost segment, speaker C not in intake (2 speakers)",
    "before": {"speaker": "C", "text": "."},
    "after": null
  },
  {
    "type": "vtt_restore",
    "at": {"absolute_start": 450.0, "source_chunk": 0},
    "reason": "API gap (2 chars) where VTT has substantive cue",
    "before": "..",
    "after": "The onboarding checklist needs updating."
  },
  {
    "type": "vtt_spelling",
    "at": {"absolute_start": 612.3, "source_chunk": 0},
    "reason": "Term 'PandaDoc' in intake; VTT confirms spelling",
    "before": "panda doc",
    "after": "PandaDoc"
  }
]
```

## Worked Example

### 45-minute meeting (3 chunks)

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

$ # Agent cleanup pass reads merged.json, produces polished.json + edits.json
$ # Then render:
$ uv run --script scripts/render_transcript.py \
    tmp/prep/workshop-20260504/polished.json \
    --speakers "A=Sarah,B=Mike,C=Lisa" \
    --out outbox/workshop-20260504/transcript.md
Wrote outbox/workshop-20260504/transcript.md
```
