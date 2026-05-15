#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract a short audio clip at a given timestamp for spot-checking.

Use when you want to verify what a speaker actually said in a particular
segment — point at the audio, give a timestamp, get a small clip.
The agent (or user) can listen to it directly to disambiguate ASR garble.

Examples:

    # 6-second clip starting at 11:05
    uv run --script scripts/extract_clip.py inbox/meeting.m4a --at 665 --duration 6

    # Specify output path
    uv run --script scripts/extract_clip.py inbox/meeting.m4a \\
        --at 665 --duration 6 --out tmp/spot_check.ogg

    # Accept timestamp as MM:SS or H:MM:SS
    uv run --script scripts/extract_clip.py inbox/meeting.m4a --at 11:05

Defaults:
  --duration 6
  --out tmp/clips/clip_<seconds>.ogg
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def parse_timestamp(value: str) -> float:
    """Accept seconds (float / int) or H:MM:SS / MM:SS."""
    if ":" not in value:
        return float(value)
    parts = value.split(":")
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    raise argparse.ArgumentTypeError(f"Bad timestamp: {value}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("audio", type=Path, help="Source audio or video file")
    p.add_argument(
        "--at",
        type=parse_timestamp,
        required=True,
        help="Start timestamp (seconds, MM:SS, or H:MM:SS)",
    )
    p.add_argument(
        "--duration", type=float, default=6.0, help="Clip duration in seconds (default 6)"
    )
    p.add_argument(
        "--out", type=Path, default=None, help="Output path (default tmp/clips/clip_<seconds>.ogg)"
    )
    args = p.parse_args()

    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not on PATH", file=sys.stderr)
        return 2
    if not args.audio.exists():
        print(f"Error: {args.audio} not found", file=sys.stderr)
        return 2

    if args.out is None:
        out = Path("tmp/clips") / f"clip_{int(args.at):04d}.ogg"
    else:
        out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{args.at}",
        "-t",
        f"{args.duration}",
        "-i",
        str(args.audio),
        "-vn",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"ffmpeg failed: {res.stderr.strip()}", file=sys.stderr)
        return res.returncode

    print(json.dumps({"path": str(out), "start_s": args.at, "duration_s": args.duration}))
    print(f"Wrote {out} ({args.duration:.1f}s @ {args.at:.1f}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
