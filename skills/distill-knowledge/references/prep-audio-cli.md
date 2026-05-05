# prep_audio.py CLI reference

Preprocesses audio or video for transcription: strips leading/trailing silence, re-encodes to canonical Opus 32k mono 16kHz, and optionally splits into balanced chunks for long recordings.

## Usage

```bash
uv run --script scripts/prep_audio.py <input> --out-dir <dir> [options]
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| `<input>` | yes | Audio (`.m4a`, `.mp3`, `.wav`, `.ogg`, `.opus`, `.flac`) or video (`.mp4`, `.mov`, `.mkv`, `.webm`) file |
| `--out-dir` | yes | Output directory (created if needed) |
| `--max-chunk` | no | Max chunk duration in seconds (default: 1080 = 18 min) |
| `--overlap` | no | Overlap between chunks in seconds (default: 30 for diarize; use 5 for single-speaker) |
| `--no-split` | no | Force single output even if stripped duration exceeds max-chunk |

## Examples

### Standard preprocessing (short file)

```bash
uv run --script scripts/prep_audio.py \
  inbox/meeting.m4a \
  --out-dir tmp/prep/onboarding-review-20260504
```

### Long file with default chunking

```bash
uv run --script scripts/prep_audio.py \
  inbox/long-workshop.mp4 \
  --out-dir tmp/prep/workshop-20260504
```

### Single-speaker (smaller overlap)

```bash
uv run --script scripts/prep_audio.py \
  inbox/voice-note.m4a \
  --out-dir tmp/prep/voice-note-20260504 \
  --overlap 5
```

### Force single file (no split regardless of duration)

```bash
uv run --script scripts/prep_audio.py \
  inbox/podcast.mp3 \
  --out-dir tmp/prep/podcast-20260504 \
  --no-split
```

## Outputs

| File | Always | Description |
|---|---|---|
| `stripped.ogg` | yes | Opus 32k mono 16kHz, leading/trailing silence removed |
| `chunks/chunk_NN.ogg` | when split | Stream-copied from `stripped.ogg` |
| `manifest.json` | yes | Chunk boundaries, overlap, status tracking |

## Behaviour

- **Leading/trailing silence only.** Internal silence is never removed.
- **No filters, no loudness normalisation.** Filtering can introduce phantom diarize labels.
- **No speed adjustment** unless an explicit user flag is added later.
- **Video input:** audio track extracted via `-vn` in the re-encode pass. The source video is unmodified and retained for Step 6 screenshots.
- **Split trigger:** stripped duration > `--max-chunk` → `n = ceil(duration / max_chunk)`, target = `duration / n`. Each ideal split point snaps to the nearest silence within ±60s.
- **Chunk arithmetic:** 17 min → 1 chunk; 22 min → 2× ~11 min; 45 min → 3× ~15 min.

## manifest.json schema

```json
{
  "version": 1,
  "source": "inbox/meeting.m4a",
  "source_duration_s": 1800.0,
  "stripped_duration_s": 1797.5,
  "silence_stripped": {"leading_s": 1.2, "trailing_s": 1.3},
  "split": true,
  "n_chunks": 2,
  "max_chunk_s": 1080,
  "overlap_s": 30,
  "chunks": [
    {
      "index": 0,
      "file": "chunks/chunk_00.ogg",
      "core_start_s": 0.0,
      "core_end_s": 897.4,
      "chunk_start_s": 0.0,
      "chunk_end_s": 927.4,
      "split_silence": {"start": 896.8, "end": 898.0},
      "status": "pending",
      "transcript_file": null,
      "request_id": null
    }
  ]
}
```

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Input error (file not found, entirely silent, ffmpeg failure) |
