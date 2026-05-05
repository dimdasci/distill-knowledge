#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Merge per-chunk transcription JSONs into a unified timeline.

Produces merged.json with:
- segments[] — all chunks' segments in chronological order, with `start`/`end`
  rewritten to absolute (global) seconds; `source_chunk` and `in_overlap` added
- overlap_windows[] — side-by-side segments from adjacent chunks in shared regions
- chunk_boundaries[] — where chunks meet
- intake_context — pass-through from CLI
- cross_check_cues — present only with --vtt

Does NOT decide: label remap, hallucination flagging, dedup, quality scoring.

Run with:
    uv run --script skills/convert/scripts/merge_chunks.py \
        --manifest tmp/prep/<slug>/manifest.json \
        --intake '{"speaker_count":2,"speaker_names":["A","B"],"topic":"...","terms":[]}' \
        [--vtt path/to/parsed.vtt] \
        --out tmp/prep/<slug>/merged.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn


def _die(message: str, code: int = 1) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _load_json(path: Path) -> Any:
    """Load and parse a JSON file."""
    if not path.exists():
        _die(f"File not found: {path}", 2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {path}: {exc}", 2)


def _load_chunk_segments(manifest: dict, manifest_dir: Path) -> list[list[dict]]:
    """Load segments from each chunk's transcript file."""
    all_segments: list[list[dict]] = []
    for chunk in manifest["chunks"]:
        status = chunk.get("status")
        if status != "done":
            _die(
                f"Chunk {chunk['index']} status is {status!r} (expected 'done'). "
                "Re-run `transcribe_diarize.py --manifest --chunk-index "
                f"{chunk['index']}` and merge again.",
                2,
            )
        transcript_file = chunk.get("transcript_file")
        if not transcript_file:
            _die(f"Chunk {chunk['index']} has no transcript_file in manifest", 2)

        transcript_path = Path(transcript_file)
        if not transcript_path.is_absolute():
            transcript_path = manifest_dir / transcript_path

        data = _load_json(transcript_path)

        # Extract segments from various JSON shapes
        if isinstance(data, dict) and "segments" in data:
            segments = data["segments"]
        elif isinstance(data, list):
            segments = data
        else:
            _die(f"Unexpected JSON structure in {transcript_path}", 2)

        all_segments.append(segments)
    return all_segments


def _annotate_segments(
    segments: list[dict],
    chunk: dict,
) -> list[dict]:
    """Rewrite segment timestamps to the global timeline.

    `start` and `end` are overwritten with absolute (global) seconds so
    downstream consumers (render_transcript.py, the cleanup pass) see one
    consistent timeline. Adds `source_chunk` and `in_overlap` annotations.
    """
    chunk_start = chunk["chunk_start_s"]
    core_start = chunk["core_start_s"]
    core_end = chunk["core_end_s"]
    chunk_end = chunk["chunk_end_s"]
    chunk_index = chunk["index"]

    annotated = []
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        abs_start = round(chunk_start + seg_start, 3)
        abs_end = round(chunk_start + seg_end, 3)

        in_overlap = None
        if abs_start < core_start:
            in_overlap = "prev"
        elif abs_end > core_end and chunk_end > core_end:
            in_overlap = "next"

        annotated.append({
            **seg,
            "start": abs_start,
            "end": abs_end,
            "source_chunk": chunk_index,
            "in_overlap": in_overlap,
        })
    return annotated


def _build_overlap_windows(
    all_annotated: list[list[dict]],
    manifest: dict,
) -> list[dict]:
    """Build side-by-side overlap windows for each chunk boundary."""
    chunks = manifest["chunks"]
    overlap_s = manifest["overlap_s"]
    windows = []

    for i in range(len(chunks) - 1):
        left_chunk = chunks[i]
        right_chunk = chunks[i + 1]

        # Shared region: from core_end - overlap to core_end + overlap
        # More precisely: the region where both chunks have data
        boundary = left_chunk["core_end_s"]
        shared_start = boundary - overlap_s
        shared_end = boundary + overlap_s

        # Left segments in shared region (timestamps are now absolute)
        left_segs = [
            seg for seg in all_annotated[i]
            if seg["end"] > shared_start and seg["start"] < shared_end
        ]

        # Right segments in shared region
        right_segs = [
            seg for seg in all_annotated[i + 1]
            if seg["end"] > shared_start and seg["start"] < shared_end
        ]

        windows.append({
            "boundary_idx": i,
            "shared_region": [round(shared_start, 1), round(shared_end, 1)],
            "left": left_segs,
            "right": right_segs,
        })

    return windows


def _build_chunk_boundaries(manifest: dict) -> list[dict]:
    """Build chunk boundary metadata."""
    chunks = manifest["chunks"]
    overlap_s = manifest["overlap_s"]
    boundaries = []

    for i in range(len(chunks) - 1):
        core_end = chunks[i]["core_end_s"]
        boundaries.append({
            "index": i,
            "core_end_s": core_end,
            "shared_region": [
                round(core_end - overlap_s, 1),
                round(core_end + overlap_s, 1),
            ],
        })

    return boundaries


def _parse_vtt_cues(vtt_path: Path) -> list[dict]:
    """Parse VTT via the parse_vtt library function."""
    # Import from sibling script
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from parse_vtt import parse_vtt  # noqa: PLC0415
    except ImportError:
        _die("Cannot import parse_vtt from scripts directory")

    result = parse_vtt(str(vtt_path))
    return result.get("cues", [])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge per-chunk transcription JSONs into unified timeline."
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to manifest.json from prep_audio.py",
    )
    parser.add_argument(
        "--intake", required=True,
        help="JSON string with intake context (speaker_count, speaker_names, topic, terms)",
    )
    parser.add_argument(
        "--vtt", default=None,
        help="Path to VTT file for cross-check cues (optional)",
    )
    parser.add_argument(
        "--out", required=True,
        help="Output path for merged.json",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = _load_json(manifest_path)
    manifest_dir = manifest_path.parent

    # Parse intake context
    try:
        intake_context = json.loads(args.intake)
    except json.JSONDecodeError as exc:
        _die(f"Invalid --intake JSON: {exc}")

    # Load and annotate all chunk segments
    all_raw = _load_chunk_segments(manifest, manifest_dir)
    all_annotated: list[list[dict]] = []
    for i, (raw_segs, chunk) in enumerate(zip(all_raw, manifest["chunks"])):
        annotated = _annotate_segments(raw_segs, chunk)
        all_annotated.append(annotated)

    # Build unified segments list (chronological, all chunks)
    all_segments: list[dict] = []
    for annotated in all_annotated:
        all_segments.extend(annotated)
    all_segments.sort(key=lambda s: s["start"])

    # Detect language from first chunk or intake
    language = intake_context.get("language", "")
    if not language and all_raw:
        # Try to get from chunk transcript metadata
        first_chunk_path = manifest["chunks"][0].get("transcript_file")
        if first_chunk_path:
            p = Path(first_chunk_path)
            if not p.is_absolute():
                p = manifest_dir / p
            if p.exists():
                data = _load_json(p)
                if isinstance(data, dict):
                    language = data.get("language", "")

    # Build output
    merged: dict[str, Any] = {
        "version": 1,
        "language": language,
        "intake_context": intake_context,
        "segments": all_segments,
        "chunk_boundaries": _build_chunk_boundaries(manifest),
        "overlap_windows": _build_overlap_windows(all_annotated, manifest),
    }

    # Optional VTT cross-check
    if args.vtt:
        vtt_path = Path(args.vtt)
        if not vtt_path.exists():
            _die(f"VTT file not found: {vtt_path}", 2)
        merged["cross_check_cues"] = _parse_vtt_cues(vtt_path)

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
