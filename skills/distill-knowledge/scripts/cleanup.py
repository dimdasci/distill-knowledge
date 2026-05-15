#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Remove temporary prep artifacts after the user accepts the transcript.

Safety constraints:
- Only deletes directories under `<project-root>/tmp/`.
- Refuses to act if the final transcript is missing in outbox.
- Never shells out to `rm`; uses Python's shutil.rmtree.

Run with:
    uv run --script skills/distill-knowledge/scripts/cleanup.py \
        --slug <meeting-slug> [--project-root .]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import NoReturn


def _die(message: str, code: int = 1) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _resolve_project_root(raw: str) -> Path:
    """Resolve and validate the project root directory."""
    root = Path(raw).resolve()
    if not root.is_dir():
        _die(f"Project root is not a directory: {root}")
    return root


def _assert_under_tmp(path: Path, tmp_root: Path) -> None:
    """Hard guard: path must be strictly inside tmp_root."""
    try:
        path.resolve().relative_to(tmp_root.resolve())
    except ValueError:
        _die(
            f"Refusing to delete {path}: it is not under {tmp_root}. "
            "This script only removes directories inside the tmp/ folder."
        )


def _dir_size(path: Path) -> int:
    """Total bytes of all files in a directory tree."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _human_size(nbytes: int) -> str:
    """Format byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove temporary prep artifacts for a completed meeting."
    )
    parser.add_argument(
        "--slug",
        required=True,
        help="Meeting slug (e.g. architecture-dima-mark-20260211)",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )

    args = parser.parse_args()
    slug: str = args.slug
    root = _resolve_project_root(args.project_root)
    tmp_root = root / "tmp"
    prep_dir = tmp_root / "prep" / slug
    outbox_dir = root / "outbox" / slug
    transcript = outbox_dir / "transcript.md"

    # --- Pre-flight checks ---

    if not tmp_root.is_dir():
        _die(f"tmp/ directory does not exist: {tmp_root}")

    if not prep_dir.is_dir():
        _die(f"Nothing to clean: {prep_dir} does not exist")

    _assert_under_tmp(prep_dir, tmp_root)

    if not transcript.is_file():
        _die(
            f"Final transcript not found at {transcript}. "
            "Refusing to delete temp artifacts before the output is confirmed. "
            "Finish the transcript first, then re-run cleanup."
        )

    # --- Inventory ---

    files = list(prep_dir.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    dir_count = sum(1 for f in files if f.is_dir())
    total_bytes = _dir_size(prep_dir)

    print(f"Slug:        {slug}", file=sys.stderr)
    print(f"Prep dir:    {prep_dir}", file=sys.stderr)
    print(f"Transcript:  {transcript} ✓", file=sys.stderr)
    print(f"Files:       {file_count}", file=sys.stderr)
    print(f"Directories: {dir_count}", file=sys.stderr)
    print(f"Size:        {_human_size(total_bytes)}", file=sys.stderr)

    if args.dry_run:
        print(
            "\n[dry-run] Would delete the above. Pass without --dry-run to execute.",
            file=sys.stderr,
        )
        return

    # --- Delete ---

    shutil.rmtree(prep_dir)
    print(f"\nDeleted {prep_dir} — freed {_human_size(total_bytes)}", file=sys.stderr)


if __name__ == "__main__":
    main()
