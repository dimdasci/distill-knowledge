"""Tests for cleanup.py safety logic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "cleanup.py")


def _run(
    tmp_path: Path, slug: str, *, dry_run: bool = False, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        SCRIPT,
        "--slug",
        slug,
        "--project-root",
        str(tmp_path),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _setup_project(tmp_path: Path, slug: str, *, with_transcript: bool = True) -> None:
    """Create minimal project structure with tmp/prep and optionally outbox."""
    prep = tmp_path / "tmp" / "prep" / slug
    prep.mkdir(parents=True)
    # Create some temp files
    (prep / "stripped.ogg").write_bytes(b"\x00" * 1024)
    (prep / "manifest.json").write_text(json.dumps({"version": 1}))
    chunks = prep / "chunks"
    chunks.mkdir()
    (chunks / "chunk_00.ogg").write_bytes(b"\x00" * 512)

    if with_transcript:
        outbox = tmp_path / "outbox" / slug
        outbox.mkdir(parents=True)
        (outbox / "transcript.md").write_text("# Test transcript\n")


def test_refuses_without_transcript(tmp_path: Path) -> None:
    """Cleanup must refuse if outbox transcript is missing."""
    slug = "no-transcript-slug"
    _setup_project(tmp_path, slug, with_transcript=False)

    result = _run(tmp_path, slug)
    assert result.returncode != 0
    assert "Final transcript not found" in result.stderr
    # Prep dir must still exist
    assert (tmp_path / "tmp" / "prep" / slug).is_dir()


def test_refuses_nonexistent_slug(tmp_path: Path) -> None:
    """Cleanup must fail if prep dir doesn't exist."""
    (tmp_path / "tmp").mkdir(parents=True)
    result = _run(tmp_path, "ghost-slug")
    assert result.returncode != 0
    assert "does not exist" in result.stderr


def test_dry_run_preserves_files(tmp_path: Path) -> None:
    """Dry run should report but not delete."""
    slug = "dry-run-test"
    _setup_project(tmp_path, slug)

    result = _run(tmp_path, slug, dry_run=True)
    assert result.returncode == 0
    assert "dry-run" in result.stderr
    # Nothing deleted
    assert (tmp_path / "tmp" / "prep" / slug / "stripped.ogg").exists()


def test_actual_cleanup(tmp_path: Path) -> None:
    """Actual cleanup should remove prep dir when transcript exists."""
    slug = "real-cleanup"
    _setup_project(tmp_path, slug)

    prep = tmp_path / "tmp" / "prep" / slug
    assert prep.is_dir()

    result = _run(tmp_path, slug)
    assert result.returncode == 0
    assert "Deleted" in result.stderr
    assert "freed" in result.stderr
    # Prep dir gone
    assert not prep.exists()
    # Transcript untouched
    assert (tmp_path / "outbox" / slug / "transcript.md").is_file()


def test_reports_file_count_and_size(tmp_path: Path) -> None:
    """Dry run output should include file count and size."""
    slug = "inventory-check"
    _setup_project(tmp_path, slug)

    result = _run(tmp_path, slug, dry_run=True)
    assert "Files:" in result.stderr
    assert "Size:" in result.stderr
    assert "Directories:" in result.stderr
