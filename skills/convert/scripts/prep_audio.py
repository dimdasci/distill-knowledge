#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "speech-prep>=0.1.4",
# ]
# ///
"""Preprocess audio/video for transcription: strip silence, re-encode, chunk.

Run with:
    uv run --script skills/convert/scripts/prep_audio.py \
        <input> --out-dir tmp/prep/<slug>
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def _die(message: str, code: int = 1) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _probe_duration(path: Path) -> float:
    """Get duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as exc:
        _die(f"ffprobe failed on {path}: {exc}", 2)


def _reencode_stripped(
    input_path: Path,
    output_path: Path,
    leading_s: float,
    trailing_s: float,
    source_duration: float,
) -> None:
    """Re-encode to Opus 32k mono 16kHz, trimming leading/trailing silence."""
    start = leading_s
    duration = source_duration - leading_s - trailing_s

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "libopus",
        "-b:a", "32k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _die(f"ffmpeg re-encode failed:\n{result.stderr}", 2)


def _cut_chunk(
    source: Path,
    output: Path,
    start_s: float,
    duration_s: float,
) -> None:
    """Cut a chunk from stripped.ogg using stream copy (no re-encode)."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-i", str(source),
        "-t", f"{duration_s:.3f}",
        "-c", "copy",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _die(f"ffmpeg chunk cut failed:\n{result.stderr}", 2)


def _find_nearest_silence(
    silence_periods: list[dict],
    target_s: float,
    window: float = 60.0,
) -> dict | None:
    """Find the silence period nearest to target_s within ±window."""
    best = None
    best_dist = float("inf")
    for period in silence_periods:
        mid = (period["start"] + period["end"]) / 2
        dist = abs(mid - target_s)
        if dist <= window and dist < best_dist:
            best = period
            best_dist = dist
    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess audio/video for transcription."
    )
    parser.add_argument("input", help="Input audio or video file")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument(
        "--max-chunk", type=float, default=1080.0,
        help="Max chunk duration in seconds (default: 1080 = 18 min)",
    )
    parser.add_argument(
        "--overlap", type=float, default=30.0,
        help="Overlap between chunks in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-split", action="store_true",
        help="Force single output even if >18 min",
    )

    args = parser.parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    if not input_path.exists():
        _die(f"Input file not found: {input_path}", 2)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Import speech-prep for silence detection
    try:
        from speech_prep import SoundFile  # noqa: PLC0415
    except ImportError:
        _die(
            "speech-prep is not installed. Run this script via "
            "`uv run --script` so PEP 723 metadata resolves the dep."
        )

    # Detect silence periods (single invocation)
    print(f"Analyzing silence in {input_path}...", file=sys.stderr)
    sf = SoundFile(str(input_path), noise_threshold_db=-40, min_silence_duration=0.5)

    source_duration = _probe_duration(input_path)

    # Determine leading/trailing silence to strip
    leading_s = 0.0
    trailing_s = 0.0

    silence_periods = sf.silence_periods
    if silence_periods:
        # speech-prep returns tuples: (start, end, duration)
        # Leading: silence that starts at or near 0
        first = silence_periods[0]
        if first[0] <= 0.1:
            leading_s = first[1]
        # Trailing: silence that ends at or near the file end
        last = silence_periods[-1]
        if last[1] >= source_duration - 0.1:
            trailing_s = source_duration - last[0]

    stripped_duration = source_duration - leading_s - trailing_s
    if stripped_duration <= 0:
        _die("File is entirely silence after strip", 2)

    # Re-encode to stripped.ogg
    stripped_path = out_dir / "stripped.ogg"
    print(f"Re-encoding to {stripped_path}...", file=sys.stderr)
    _reencode_stripped(input_path, stripped_path, leading_s, trailing_s, source_duration)

    # Actual stripped duration from the produced file
    stripped_duration = _probe_duration(stripped_path)

    # Decide split
    needs_split = (not args.no_split) and (stripped_duration > args.max_chunk)

    # Adjust silence_periods to stripped timeline (subtract leading_s)
    adjusted_silences = []
    for period in silence_periods:
        # period is tuple: (start, end, duration)
        adj_start = period[0] - leading_s
        adj_end = period[1] - leading_s
        # Only keep periods that are internal (not the stripped leading/trailing)
        if adj_start > 0 and adj_end < stripped_duration:
            adjusted_silences.append({"start": adj_start, "end": adj_end})

    manifest: dict = {
        "version": 1,
        "source": str(input_path),
        "source_duration_s": round(source_duration, 1),
        "stripped_duration_s": round(stripped_duration, 1),
        "silence_stripped": {
            "leading_s": round(leading_s, 1),
            "trailing_s": round(trailing_s, 1),
        },
        "split": needs_split,
        "n_chunks": 1,
        "max_chunk_s": args.max_chunk,
        "overlap_s": args.overlap,
        "chunks": [],
    }

    if not needs_split:
        # Single chunk = the whole file
        manifest["n_chunks"] = 1
        manifest["chunks"] = [{
            "index": 0,
            "file": "stripped.ogg",
            "core_start_s": 0.0,
            "core_end_s": round(stripped_duration, 1),
            "chunk_start_s": 0.0,
            "chunk_end_s": round(stripped_duration, 1),
            "split_silence": None,
            "status": "pending",
            "transcript_file": None,
            "request_id": None,
        }]
    else:
        # Split into balanced chunks
        n = math.ceil(stripped_duration / args.max_chunk)
        target = stripped_duration / n
        chunks_dir = out_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        # Find ideal split points and snap to silence
        split_points: list[dict] = []  # {core_end, silence}
        for i in range(1, n):
            ideal = target * i
            silence = _find_nearest_silence(adjusted_silences, ideal, window=60.0)
            if silence:
                core_end = (silence["start"] + silence["end"]) / 2
                split_points.append({"core_end": core_end, "silence": silence})
            else:
                # No silence found; split at ideal point
                split_points.append({"core_end": ideal, "silence": None})

        # Build chunk list
        chunks = []
        prev_core_end = 0.0
        for idx in range(n):
            if idx < n - 1:
                core_end = split_points[idx]["core_end"]
                split_silence = split_points[idx]["silence"]
            else:
                core_end = stripped_duration
                split_silence = None

            core_start = prev_core_end

            # chunk extends overlap past core_end (except last chunk)
            if idx < n - 1:
                chunk_end = min(core_end + args.overlap, stripped_duration)
            else:
                chunk_end = stripped_duration

            # chunk starts overlap before core_start (except first chunk)
            if idx > 0:
                chunk_start = max(core_start - args.overlap, 0.0)
            else:
                chunk_start = 0.0

            chunk_duration = chunk_end - chunk_start
            chunk_file = f"chunks/chunk_{idx:02d}.ogg"
            chunk_path = out_dir / chunk_file

            _cut_chunk(stripped_path, chunk_path, chunk_start, chunk_duration)

            chunks.append({
                "index": idx,
                "file": chunk_file,
                "core_start_s": round(core_start, 1),
                "core_end_s": round(core_end, 1),
                "chunk_start_s": round(chunk_start, 1),
                "chunk_end_s": round(chunk_end, 1),
                "split_silence": (
                    {"start": round(split_silence["start"], 1),
                     "end": round(split_silence["end"], 1)}
                    if split_silence else None
                ),
                "status": "pending",
                "transcript_file": None,
                "request_id": None,
            })
            prev_core_end = core_end

        manifest["n_chunks"] = n
        manifest["chunks"] = chunks

    # Write manifest
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Manifest: {manifest_path}", file=sys.stderr)
    print(f"Chunks: {manifest['n_chunks']}", file=sys.stderr)
    print(f"Stripped duration: {stripped_duration:.1f}s", file=sys.stderr)

    # Output manifest to stdout for script consumers
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
