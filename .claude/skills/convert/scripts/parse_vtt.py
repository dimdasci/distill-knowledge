#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Parse WebVTT transcript files into structured JSON for meeting analysis.

Run with: uv run --script .claude/skills/convert/scripts/parse_vtt.py <file.vtt>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})"
)
SPEAKER_RE = re.compile(r"^(.+?):\s+(.+)$")

SCREEN_PATTERNS = {
    "explicit": ["see my screen", "screen share", "showing you", "let me show",
                  "look at this", "you see this", "can you see"],
    "deictic": ["this table", "this page", "this column", "this field",
                "this button", "right here", "over here", "this one"],
    "navigation": ["scroll down", "click here", "go to", "open this",
                    "switch to", "zoom in"],
}
SCREEN_COMPILED = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats]
    for cat, pats in SCREEN_PATTERNS.items()
}


def ts_to_seconds(ts: str) -> float:
    """Convert HH:MM:SS.mmm to seconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def detect_screen_ref(text: str) -> str | None:
    """Return screen reference type if text matches any pattern, else None."""
    for cat, pats in SCREEN_COMPILED.items():
        for p in pats:
            if p.search(text):
                return cat
    return None


def parse_speaker(line: str) -> tuple[str, str]:
    """Extract (speaker, text) from a line. Defaults to ('Unknown', line)."""
    m = SPEAKER_RE.match(line)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("Unknown", line.strip())


def _die(msg: str, code: int = 1) -> NoReturn:
    print(f"Error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _check_input(vtt_path: str) -> Path:
    path = Path(vtt_path)
    if not path.exists():
        _die(f"VTT file not found: {path}")
    if not path.is_file():
        _die(f"VTT path is not a file: {path}")
    if path.suffix.lower() not in {".vtt", ".webvtt", ".txt"}:
        print(
            f"Warning: unexpected extension {path.suffix!r}; proceeding anyway.",
            file=sys.stderr,
        )
    return path


def parse_vtt(filepath: str) -> dict:
    """Parse a VTT file and return structured data."""
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        _die(f"reading file: {e}")

    # Find WEBVTT header
    start = 0
    for idx, line in enumerate(lines):
        if line.strip().replace("\ufeff", "").startswith("WEBVTT"):
            start = idx + 1
            break
    else:
        print("Warning: No WEBVTT header found, parsing anyway.", file=sys.stderr)

    cues, screen_refs, speakers = [], [], set()
    cue_index, max_end, i = 0, 0.0, start

    while i < len(lines):
        line = lines[i].strip()
        if not line or line.isdigit():
            i += 1
            continue

        ts_match = TIMESTAMP_RE.match(line)
        if not ts_match:
            i += 1
            continue

        start_ts, end_ts = ts_match.group(1), ts_match.group(2)
        try:
            start_sec, end_sec = ts_to_seconds(start_ts), ts_to_seconds(end_ts)
        except (ValueError, IndexError):
            print(
                f"Warning: malformed timestamp at line {i + 1}, skipping.",
                file=sys.stderr,
            )
            i += 1
            continue

        max_end = max(max_end, end_sec)

        # Collect cue text lines
        i += 1
        text_lines = []
        while i < len(lines):
            tl = lines[i].strip()
            if not tl:
                i += 1
                break
            if TIMESTAMP_RE.match(tl):
                break
            if (
                tl.isdigit()
                and i + 1 < len(lines)
                and TIMESTAMP_RE.match(lines[i + 1].strip())
            ):
                break
            text_lines.append(tl)
            i += 1

        if not text_lines:
            print(f"Warning: empty cue at {start_ts}, skipping.", file=sys.stderr)
            continue

        speaker, cleaned = parse_speaker(text_lines[0])
        if len(text_lines) > 1:
            cleaned = cleaned + " " + " ".join(text_lines[1:])

        speakers.add(speaker)
        cue_index += 1
        ref_type = detect_screen_ref(cleaned)

        cues.append({
            "index": cue_index, "start": start_ts, "end": end_ts,
            "start_seconds": round(start_sec, 3), "end_seconds": round(end_sec, 3),
            "speaker": speaker, "text": cleaned,
            "screen_reference": ref_type is not None,
        })

        if ref_type:
            screen_refs.append({
                "cue_index": cue_index, "timestamp": start_ts,
                "seconds": round(start_sec, 3), "context": cleaned, "type": ref_type,
            })

    sorted_speakers = sorted(speakers)
    return {
        "metadata": {
            "duration_seconds": round(max_end, 3),
            "speaker_count": len(sorted_speakers),
            "speakers": sorted_speakers,
            "cue_count": len(cues),
        },
        "cues": cues,
        "screen_references": screen_refs,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse WebVTT transcript files into structured JSON.")
    parser.add_argument("vtt_file", help="Path to the VTT file to parse")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output with indentation")
    parser.add_argument("--output", "-o", default=None,
                        help="Write JSON to this file instead of stdout")
    args = parser.parse_args()

    vtt_path = _check_input(args.vtt_file)
    result = parse_vtt(str(vtt_path))
    indent = 2 if args.pretty else None
    output_str = json.dumps(result, indent=indent, ensure_ascii=False)
    if indent:
        output_str += "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output_str)


if __name__ == "__main__":
    main()
