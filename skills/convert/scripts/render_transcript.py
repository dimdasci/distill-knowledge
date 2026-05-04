#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Render diarized JSON to clean markdown transcript.

Run with:
    uv run --script skills/convert/scripts/render_transcript.py \\
        <diarized.json> [flags]

Modes:
    --samples           Print longest substantive segments per speaker (for user labelling).
    (default)           Render cleaned markdown transcript to --out path.

Filters (default-on):
    - Drop speaker == "@" (unattributable marker)
    - Drop zero-duration segments (start == end)
    - Drop hallucination blacklist matches
    - Merge consecutive same-speaker segments
    - Absorb ≤2-word cross-talk interjections back into surrounding speaker turns
    - Reconstruct overlapping speech: when two speakers' segments overlap in
      time (interleaved A/B/A/B), group each speaker's text into one
      sequential turn so each idea reads as a phrase, not word-by-word.
      Disable with --no-reconstruct-overlaps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn


# ---------------------------------------------------------------------------
# Hallucination blacklist — exact full-segment matches (after strip)
# ---------------------------------------------------------------------------

DEFAULT_BLACKLIST: list[str] = [
    # Russian
    "Субтитры сделал DimaTorzok",
    "Субтитры от Amara.org",
    "Субтитры подогнал",
    "Субтитры создавал DimaTorzok",
    "Субтитры делал DimaTorzok",
    "Продолжение следует...",
    # English
    "Thanks for watching",
    "Thanks for watching!",
    "Subscribe to the channel",
    "Like and subscribe",
    "Like and subscribe!",
    "Please subscribe",
    # French
    "Sous-titres réalisés par la communauté d'Amara.org",
    "Sous-titres réalisés para la communauté d'Amara.org",
]


def _die(message: str, code: int = 1) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_segments(path: Path) -> list[dict[str, Any]]:
    """Load segments from a diarized JSON file."""
    if not path.exists():
        _die(f"File not found: {path}", 2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON: {exc}", 2)

    if isinstance(data, dict) and "segments" in data:
        segments = data["segments"]
    elif isinstance(data, list):
        segments = data
    else:
        _die("JSON must contain a top-level 'segments' array or be a list", 2)

    return segments  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _build_blacklist(extra_path: str | None) -> set[str]:
    """Build the full blacklist set from defaults + optional file."""
    bl = {phrase.strip() for phrase in DEFAULT_BLACKLIST}
    if extra_path:
        p = Path(extra_path)
        if not p.exists():
            _die(f"Blacklist file not found: {p}", 2)
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                bl.add(line)
    return bl


def _word_count(text: str) -> int:
    return len(text.split())


def _filter_segments(
    segments: list[dict[str, Any]],
    blacklist: set[str],
) -> list[dict[str, Any]]:
    """Apply all default-on filters except merge and smoothing."""
    result: list[dict[str, Any]] = []
    for seg in segments:
        speaker = seg.get("speaker", "")
        text = seg.get("text", "").strip()
        start = seg.get("start", 0)
        end = seg.get("end", 0)

        # Drop unattributable speaker
        if speaker == "@":
            continue

        # Drop zero-duration
        if start == end:
            continue

        # Drop empty text
        if not text:
            continue

        # Drop blacklisted (exact full-segment match)
        if text in blacklist:
            continue

        result.append(seg)

    return result


def _reconstruct_overlaps(
    segments: list[dict[str, Any]],
    *,
    tolerance: float = 0.0,
    max_cluster_seconds: float = 20.0,
    max_cluster_segments: int = 8,
) -> list[dict[str, Any]]:
    """Reconstruct overlapping speech into sequential per-speaker phrases.

    When two different speakers' segments overlap in time (segment B starts
    before segment A ends), the diarized output interleaves them as
    A/B/A/B. This function detects bounded overlap clusters and groups
    each speaker's segments into a single concatenated turn — preserving
    the full idea per speaker rather than word-by-word interleaving.

    Cluster bounds (to prevent runaway collapse of long debates):
      - Extend only while the next segment overlaps the immediately
        previous segment in the cluster (next.start < prev.end). A pause
        between consecutive segments closes the cluster, so normal turn
        flow is preserved.
      - Hard cap: max_cluster_seconds total span.
      - Hard cap: max_cluster_segments raw segments.

    Within a cluster, speakers are emitted in the order they first
    started speaking. Each emitted turn keeps its earliest start and
    latest end.
    """
    if len(segments) < 2:
        return segments

    result: list[dict[str, Any]] = []
    i = 0
    n = len(segments)
    while i < n:
        if (
            i + 1 < n
            and segments[i]["speaker"] != segments[i + 1]["speaker"]
            and segments[i + 1].get("start", 0) < segments[i].get("end", 0) - tolerance
        ):
            cluster: list[dict[str, Any]] = [segments[i], segments[i + 1]]
            cluster_start = segments[i].get("start", 0)
            cluster_max_end = max(
                segments[i].get("end", 0), segments[i + 1].get("end", 0)
            )
            j = i + 2
            while j < n:
                prev = cluster[-1]
                nxt = segments[j]
                if nxt.get("start", 0) >= prev.get("end", 0) - tolerance:
                    break  # natural pause — close cluster
                if len(cluster) >= max_cluster_segments:
                    break
                if nxt.get("end", 0) - cluster_start > max_cluster_seconds:
                    break
                cluster.append(nxt)
                cluster_max_end = max(cluster_max_end, nxt.get("end", 0))
                j += 1

            speaker_order: list[str] = []
            grouped: dict[str, list[dict[str, Any]]] = {}
            for seg in cluster:
                sp = seg["speaker"]
                if sp not in grouped:
                    grouped[sp] = []
                    speaker_order.append(sp)
                grouped[sp].append(seg)

            speaker_order.sort(key=lambda sp: min(s.get("start", 0) for s in grouped[sp]))

            for sp in speaker_order:
                segs = grouped[sp]
                merged = {
                    "speaker": sp,
                    "start": min(s.get("start", 0) for s in segs),
                    "end": max(s.get("end", 0) for s in segs),
                    "text": "".join(s.get("text", "") for s in segs),
                }
                result.append(merged)

            i = j
        else:
            result.append(segments[i])
            i += 1

    return result


def _smooth_crosstalk(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Absorb ≤2-word interjections that briefly flip speaker.

    Pattern: [A long] [B ≤2 words] [A long] → absorb B into A.
    """
    if len(segments) < 3:
        return segments

    result: list[dict[str, Any]] = []
    i = 0
    while i < len(segments):
        if (
            i + 2 < len(segments)
            and segments[i]["speaker"] == segments[i + 2]["speaker"]
            and segments[i]["speaker"] != segments[i + 1]["speaker"]
            and _word_count(segments[i + 1].get("text", "").strip()) <= 2
        ):
            # Absorb the interjection into the surrounding speaker's turn
            merged = dict(segments[i])
            merged["end"] = segments[i + 2]["end"]
            merged["text"] = (
                segments[i].get("text", "")
                + segments[i + 2].get("text", "")
            )
            result.append(merged)
            i += 3
        else:
            result.append(segments[i])
            i += 1

    return result


def _merge_same_speaker(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive same-speaker segments into single turns."""
    if not segments:
        return []

    merged: list[dict[str, Any]] = []
    current = dict(segments[0])

    for seg in segments[1:]:
        if seg["speaker"] == current["speaker"]:
            current["end"] = seg["end"]
            current["text"] = current.get("text", "") + seg.get("text", "")
        else:
            merged.append(current)
            current = dict(seg)

    merged.append(current)
    return merged


# ---------------------------------------------------------------------------
# Speaker map
# ---------------------------------------------------------------------------


def _parse_speaker_map(raw: str | None) -> dict[str, str]:
    """Parse 'A=Dima,B=Mark' into a dict."""
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            _die(f"Invalid speaker mapping (expected KEY=NAME): {pair!r}")
        key, name = pair.split("=", 1)
        mapping[key.strip()] = name.strip()
    return mapping


def _resolve_speaker(speaker: str, speaker_map: dict[str, str]) -> str:
    return speaker_map.get(speaker, speaker)


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------


def _format_ts(seconds: float) -> str:
    """Format seconds as [H:MM:SS] or [M:SS]."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"[{h}:{m:02d}:{s:02d}]"
    return f"[{m}:{s:02d}]"


# ---------------------------------------------------------------------------
# Samples mode
# ---------------------------------------------------------------------------


def _print_samples(segments: list[dict[str, Any]]) -> None:
    """Print the longest 1-2 substantive segments per detected speaker."""
    from collections import defaultdict

    by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for seg in segments:
        by_speaker[seg["speaker"]].append(seg)

    for speaker in sorted(by_speaker.keys()):
        segs = by_speaker[speaker]
        # Sort by text length descending, pick top 2
        segs_sorted = sorted(segs, key=lambda s: len(s.get("text", "")), reverse=True)
        top = segs_sorted[:2]
        print(f"\n### Speaker {speaker}")
        for seg in top:
            text = seg.get("text", "").strip()
            preview = text[:120] + ("…" if len(text) > 120 else "")
            print(f"  {_format_ts(seg['start'])} {preview}")


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_markdown(
    segments: list[dict[str, Any]],
    speaker_map: dict[str, str],
    *,
    meeting_slug: str = "",
    source: str = "",
    model: str = "",
    language: str = "",
    topic: str = "",
    terms: str = "",
) -> str:
    """Render segments into the target markdown shape."""
    lines: list[str] = []

    # Header
    title = meeting_slug or "Transcript"
    lines.append(f"# {title}")
    lines.append("")

    meta_items: list[str] = []
    if source:
        meta_items.append(f"- source: {source}")
    if model:
        meta_items.append(f"- model: {model}")
    if language:
        meta_items.append(f"- language: {language}")

    # Speakers list
    speakers_seen: list[str] = []
    seen_set: set[str] = set()
    for seg in segments:
        sp = _resolve_speaker(seg["speaker"], speaker_map)
        if sp not in seen_set:
            speakers_seen.append(sp)
            seen_set.add(sp)
    if speakers_seen:
        meta_items.append(f"- speakers: {', '.join(speakers_seen)}")

    if topic:
        meta_items.append(f"- topic: {topic}")
    if terms:
        meta_items.append(f"- terms: {terms}")

    meta_items.append(f"- generated: {datetime.now().strftime('%Y-%m-%d')}")

    for item in meta_items:
        lines.append(item)

    lines.append("")
    lines.append("---")
    lines.append("")

    # Turns
    for seg in segments:
        speaker = _resolve_speaker(seg["speaker"], speaker_map)
        ts = _format_ts(seg.get("start", 0))
        text = seg.get("text", "").strip()
        lines.append(f"**{speaker}** {ts}: {text}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render diarized JSON to cleaned markdown transcript."
    )
    parser.add_argument("json_file", help="Path to diarized JSON file")
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print longest segments per speaker for labelling",
    )
    parser.add_argument(
        "--speakers",
        help='Speaker map, e.g. "A=Dima,B=Mark"',
    )
    parser.add_argument("--out", help="Output markdown file path (required unless --samples)")
    parser.add_argument("--blacklist", help="Extra blacklist file (one phrase per line)")
    parser.add_argument(
        "--no-reconstruct-overlaps",
        action="store_true",
        help="Disable overlap reconstruction (default: on)",
    )

    # Header metadata flags
    parser.add_argument("--source", default="", help="Source audio file path")
    parser.add_argument("--model", default="", help="Model used for transcription")
    parser.add_argument("--language", default="", help="Language hint used")
    parser.add_argument("--topic", default="", help="One-line meeting topic")
    parser.add_argument("--terms", default="", help="Comma-separated domain terms")

    args = parser.parse_args()

    json_path = Path(args.json_file)
    segments = _load_segments(json_path)
    blacklist = _build_blacklist(args.blacklist)

    # Filter
    segments = _filter_segments(segments, blacklist)

    if args.samples:
        _print_samples(segments)
        return

    if not args.out:
        _die("--out is required when not using --samples mode")

    # Reconstruct overlapping speech → smooth cross-talk → merge same speaker
    if not args.no_reconstruct_overlaps:
        segments = _reconstruct_overlaps(segments)
    segments = _smooth_crosstalk(segments)
    segments = _merge_same_speaker(segments)

    speaker_map = _parse_speaker_map(args.speakers)

    # Derive meeting slug from output path
    out_path = Path(args.out)
    meeting_slug = out_path.parent.name if out_path.parent.name != "." else out_path.stem

    md = _render_markdown(
        segments,
        speaker_map,
        meeting_slug=meeting_slug,
        source=args.source,
        model=args.model,
        language=args.language,
        topic=args.topic,
        terms=args.terms,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
