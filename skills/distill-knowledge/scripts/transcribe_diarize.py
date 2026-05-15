#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "openai>=2.4,<3",        # 2.4.0 added typed gpt-4o-transcribe-diarize support
#   "httpx>=0.25",           # granular Timeout objects for the SDK
#   "python-dotenv>=1.0",
# ]
# ///
"""Transcribe audio (optionally with speaker diarization) using OpenAI.

Run with:
    uv run --script skills/convert/scripts/transcribe_diarize.py \\
        <audio> [flags]
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, NoReturn

import httpx


def _load_dotenv_quietly() -> None:
    """Fill missing env vars from a .env in CWD or any parent. Silent on failure.

    Existing os.environ values are preserved (override=False), so an explicit
    `export OPENAI_API_KEY=...` always wins over the .env file.
    """
    try:
        from dotenv import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
            find_dotenv,
            load_dotenv,
        )
    except ImportError:
        return  # uv should have installed it; skip if not.
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


_load_dotenv_quietly()


def _check_runner() -> None:
    """Warn if the script was run without uv — deps may be missing."""
    if "VIRTUAL_ENV" in os.environ:
        return
    # If openai was importable above we're fine; this is a soft hint.
    try:
        import openai  # noqa: F401, PLC0415  # pyright: ignore[reportMissingImports]
    except ImportError:
        _die(
            "openai is not installed in the current environment.\n"
            "  Run via uv (recommended):  "
            "uv run --script "
            "skills/convert/scripts/transcribe_diarize.py ...\n"
            "  If uv cannot resolve dependencies, surface the full uv error — "
            "do not work around it with manual pip installs."
        )


DEFAULT_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_RESPONSE_FORMAT = "text"
DEFAULT_CHUNKING_STRATEGY = "auto"
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_KNOWN_SPEAKERS = 4

ALLOWED_RESPONSE_FORMATS = {"text", "json", "diarized_json"}

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, write=120.0, read=450.0, pool=10.0)
DEFAULT_MAX_WALL = 600.0  # 10 min hard wall-clock limit per API call


def _die(message: str, code: int = 1) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _ensure_api_key(dry_run: bool) -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    msg = (
        "OPENAI_API_KEY is not set.\n"
        "  Set it in your shell:   export OPENAI_API_KEY=sk-...\n"
        "  Or in a project .env:   echo 'OPENAI_API_KEY=sk-...' >> .env\n"
        "  Get a key:              https://platform.openai.com/api-keys"
    )
    if dry_run:
        _warn(msg)
        return
    _die(msg)


def _normalize_response_format(value: str | None) -> str:
    if not value:
        return DEFAULT_RESPONSE_FORMAT
    fmt = value.strip().lower()
    if fmt not in ALLOWED_RESPONSE_FORMATS:
        _die("response-format must be one of: " + ", ".join(sorted(ALLOWED_RESPONSE_FORMATS)))
    return fmt


def _normalize_chunking_strategy(value: str | None) -> Any:
    if not value:
        return DEFAULT_CHUNKING_STRATEGY
    raw = str(value).strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            _die("chunking-strategy JSON is invalid")
    return raw


def _guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    return "audio/wav"


def _encode_data_url(path: Path) -> str:
    data = path.read_bytes()
    mime = _guess_mime_type(path)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _parse_known_speakers(raw_items: list[str]) -> tuple[list[str], list[str]]:
    names: list[str] = []
    refs: list[str] = []
    for raw in raw_items:
        if "=" not in raw:
            _die("known-speaker must be NAME=PATH")
        name, path_str = raw.split("=", 1)
        name = name.strip()
        path = Path(path_str.strip())
        if not name or not path_str.strip():
            _die("known-speaker must be NAME=PATH")
        if not path.exists():
            _die(f"Known speaker file not found: {path}")
        names.append(name)
        refs.append(_encode_data_url(path))
    if len(names) > MAX_KNOWN_SPEAKERS:
        _die(f"known speakers must be <= {MAX_KNOWN_SPEAKERS}")
    return names, refs


def _output_extension(response_format: str) -> str:
    return "txt" if response_format == "text" else "json"


def _build_output_path(
    audio_path: Path,
    response_format: str,
    out: str | None,
    out_dir: str | None,
) -> Path:
    ext = "." + _output_extension(response_format)
    if out:
        path = Path(out)
        if path.exists() and path.is_dir():
            return path / f"{audio_path.stem}.transcript{ext}"
        if path.suffix == "":
            return path.with_suffix(ext)
        return path
    if out_dir:
        base = Path(out_dir)
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{audio_path.stem}.transcript{ext}"
    return Path(f"{audio_path.stem}.transcript{ext}")


def _create_client(timeout: httpx.Timeout | None = None):
    try:
        from openai import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
            OpenAI,
        )
    except ImportError:
        _die(
            "openai SDK not importable. Run this script via "
            "`uv run --script` so PEP 723 metadata resolves the dep automatically."
        )
    return OpenAI(timeout=timeout or DEFAULT_TIMEOUT)


def _format_output(result: Any, response_format: str) -> str:
    if response_format == "text":
        text = getattr(result, "text", None)
        return text if isinstance(text, str) else str(result)
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), indent=2)
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return json.dumps({"text": getattr(result, "text", str(result))}, indent=2)


def _validate_audio(path: Path) -> None:
    if not path.exists():
        _die(f"Audio file not found: {path}", 2)
    size = path.stat().st_size
    if size > MAX_AUDIO_BYTES:
        _die(f"Audio file exceeds 25MB limit ({size} bytes): {path}", 2)


def _build_payload(
    args: argparse.Namespace,
    known_speaker_names: list[str],
    known_speaker_refs: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": args.model,
        "response_format": args.response_format,
        "chunking_strategy": args.chunking_strategy,
    }
    if args.language:
        payload["language"] = args.language
    if args.prompt:
        payload["prompt"] = args.prompt
    if known_speaker_names:
        payload["known_speaker_names"] = known_speaker_names
        payload["known_speaker_references"] = known_speaker_refs
    return payload


def _die_api(category: str, exit_code: int, message: str) -> NoReturn:
    """Exit with a category-tagged error. Tag is read by the calling skill."""
    print(f"Error [{category}]: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def _preflight(client: Any, model: str, cache_dir: Path | None) -> None:
    """Fail-fast check: verify auth + model access before uploading audio.

    Result is cached in `cache_dir/.preflight_ok` for the session.
    """
    from openai import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        APIConnectionError,
        AuthenticationError,
        NotFoundError,
        PermissionDeniedError,
    )

    if cache_dir:
        marker = cache_dir / ".preflight_ok"
        if marker.exists():
            return

    try:
        client.models.retrieve(model)
    except AuthenticationError as exc:
        _die_api(
            "auth",
            10,
            "OpenAI rejected the API key (HTTP 401). The key may be revoked, "
            "expired, or malformed. Replace OPENAI_API_KEY and retry.\n"
            f"  Details: {exc}",
        )
    except PermissionDeniedError as exc:
        _die_api(
            "permission",
            11,
            f"API key does not have access to model {model!r} (HTTP 403). "
            "Grant model access on the project at "
            "https://platform.openai.com/settings, or choose a model the key can use.\n"
            f"  Details: {exc}",
        )
    except NotFoundError as exc:
        _die_api(
            "permission",
            11,
            f"Model {model!r} was not found (HTTP 404). "
            "Check the model name; it may be misspelled or "
            "unavailable on this account.\n"
            f"  Details: {exc}",
        )
    except APIConnectionError as exc:
        _die_api(
            "service",
            20,
            "Could not reach OpenAI during pre-flight check. "
            "Check connectivity and retry.\n"
            f"  Details: {exc}",
        )

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        marker = cache_dir / ".preflight_ok"
        marker.write_text("ok\n")


def _update_manifest(
    manifest_path: Path,
    chunk_index: int,
    *,
    status: str | None = None,
    request_id: str | None = None,
    transcript_file: str | None = None,
) -> None:
    """Atomically update a chunk row in the manifest."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = data["chunks"][chunk_index]
    if status is not None:
        chunk["status"] = status
    if request_id is not None:
        chunk["request_id"] = request_id
    if transcript_file is not None:
        chunk["transcript_file"] = transcript_file
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.rename(manifest_path)


def _run_one(
    client: Any,
    audio_path: Path,
    payload: dict[str, Any],
    *,
    read_timeout: float | None = None,
    max_wall: float | None = None,
    request_id: str | None = None,
) -> Any:
    # Lazy import so dry-run/preflight paths don't require the SDK loaded.
    from openai import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
    )

    model = payload.get("model")
    req_id = request_id or str(uuid.uuid4())
    effective_wall = max_wall if max_wall is not None else DEFAULT_MAX_WALL

    # Per-call timeout override
    call_timeout: httpx.Timeout | None = None
    if read_timeout is not None:
        call_timeout = httpx.Timeout(connect=10.0, write=120.0, read=read_timeout, pool=10.0)

    # Extra headers for traceability
    extra_headers = {"X-Client-Request-Id": req_id}

    print(f"[request] X-Client-Request-Id: {req_id}", file=sys.stderr)
    t0 = time.monotonic()

    def _do_call() -> Any:
        with audio_path.open("rb") as audio_file:
            kwargs: dict[str, Any] = {
                "file": audio_file,
                "extra_headers": extra_headers,
                **payload,
            }
            if call_timeout is not None:
                kwargs["timeout"] = call_timeout
            return client.audio.transcriptions.create(**kwargs)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_call)
            try:
                result = future.result(timeout=effective_wall)
            except FuturesTimeoutError:
                elapsed = time.monotonic() - t0
                _die_api(
                    "timeout",
                    21,
                    f"Wall-clock limit exceeded: {effective_wall:.0f}s "
                    f"(elapsed {elapsed:.1f}s). request_id={req_id}. "
                    "The API accepted the request but never completed. "
                    "Server may be streaming bytes without finishing. "
                    "Retry, or increase --max-wall if the file is unusually large.\n"
                    "  Details: ThreadPoolExecutor deadline reached",
                )
    except AuthenticationError as exc:
        _die_api(
            "auth",
            10,
            "OpenAI rejected the API key (HTTP 401). The key may be revoked, "
            "expired, or malformed. Replace OPENAI_API_KEY and retry.\n"
            f"  Details: {exc}",
        )
    except PermissionDeniedError as exc:
        _die_api(
            "permission",
            11,
            f"API key does not have access to model {model!r} (HTTP 403). "
            "Grant model access on the project at "
            "https://platform.openai.com/settings, or choose a model the key can use.\n"
            f"  Details: {exc}",
        )
    except NotFoundError as exc:
        _die_api(
            "permission",
            11,
            f"Model {model!r} was not found (HTTP 404). "
            "Check the model name; it may be misspelled or "
            "unavailable on this account.\n"
            f"  Details: {exc}",
        )
    except RateLimitError as exc:
        _die_api(
            "rate-limit",
            12,
            "Rate limit or quota exceeded (HTTP 429). "
            "Inspect usage at https://platform.openai.com/usage. "
            "Wait and retry, or switch to a different model/tier.\n"
            f"  Details: {exc}",
        )
    except BadRequestError as exc:
        _die_api(
            "bad-request",
            30,
            f"Request rejected (HTTP 400) for {audio_path}. Likely an unsupported "
            "audio format, malformed file, or invalid parameter combination.\n"
            f"  Details: {exc}",
        )
    except APITimeoutError as exc:
        elapsed = time.monotonic() - t0
        effective_timeout = read_timeout if read_timeout is not None else 450.0
        _die_api(
            "timeout",
            21,
            f"Request accepted but no response within {effective_timeout:.0f}s "
            f"(elapsed {elapsed:.1f}s). request_id={req_id}. "
            "Retry with --timeout <larger> or cancel.\n"
            f"  Details: {exc}",
        )
    except APIConnectionError as exc:
        _die_api(
            "service",
            20,
            "Could not reach OpenAI (network error). The SDK already retried; "
            "this is usually transient. Check connectivity and retry.\n"
            f"  Details: {exc}",
        )
    except InternalServerError as exc:
        _die_api(
            "service",
            20,
            "OpenAI service error (HTTP 5xx). The SDK already retried. "
            "Check https://status.openai.com and retry.\n"
            f"  Details: {exc}",
        )
    except Exception as exc:
        _die_api(
            "unknown",
            1,
            f"Unexpected API error for {audio_path}: {type(exc).__name__}: {exc}",
        )

    elapsed = time.monotonic() - t0
    print(f"[done] elapsed_s={elapsed:.1f} request_id={req_id}", file=sys.stderr)

    return result, req_id, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Transcribe audio (optionally with speaker diarization) using OpenAI.")
    )
    parser.add_argument("audio", nargs="+", help="Audio file(s) to transcribe")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--response-format",
        default=DEFAULT_RESPONSE_FORMAT,
        help="Response format: text, json, or diarized_json",
    )
    parser.add_argument(
        "--chunking-strategy",
        default=DEFAULT_CHUNKING_STRATEGY,
        help="Chunking strategy (use 'auto' for long audio)",
    )
    parser.add_argument("--language", help="Optional language hint (e.g. 'en')")
    parser.add_argument("--prompt", help="Optional prompt to guide transcription")
    parser.add_argument(
        "--known-speaker",
        action="append",
        default=[],
        help="Known speaker reference as NAME=PATH (repeatable, max 4)",
    )
    parser.add_argument("--out", help="Output file path (single audio only)")
    parser.add_argument("--out-dir", help="Output directory for transcripts")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write transcript to stdout instead of a file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print payload without calling the API",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override read timeout in seconds (default: 450)",
    )
    parser.add_argument(
        "--max-wall",
        type=float,
        default=None,
        help="Hard wall-clock limit per API call in seconds (default: 600). "
        "Kills the request if the server streams bytes without completing.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the pre-flight model access check",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to manifest.json for chunked transcription (updates chunk status)",
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        default=None,
        help="Chunk index in manifest to update (required with --manifest)",
    )

    args = parser.parse_args()
    args.response_format = _normalize_response_format(args.response_format)
    args.chunking_strategy = _normalize_chunking_strategy(args.chunking_strategy)

    if args.out and len(args.audio) > 1:
        _die("--out only supports a single audio file")
    if args.stdout and (args.out or args.out_dir):
        _die("--stdout cannot be combined with --out or --out-dir")
    if args.stdout and len(args.audio) > 1:
        _die("--stdout only supports a single audio file")

    if args.prompt and "transcribe-diarize" in args.model:
        _die("prompt is not supported with gpt-4o-transcribe-diarize")
    if args.response_format == "diarized_json" and "transcribe-diarize" not in args.model:
        _die("diarized_json requires gpt-4o-transcribe-diarize")
    if args.manifest and args.chunk_index is None:
        _die("--chunk-index is required when using --manifest")
    if args.manifest and len(args.audio) > 1:
        _die("--manifest only supports a single audio file (one chunk per invocation)")

    _check_runner()
    _ensure_api_key(args.dry_run)

    audio_paths = [Path(p) for p in args.audio]
    for path in audio_paths:
        _validate_audio(path)

    known_names, known_refs = _parse_known_speakers(args.known_speaker)
    if known_names and "transcribe-diarize" not in args.model:
        _warn("known-speaker references are only supported for gpt-4o-transcribe-diarize")
    payload = _build_payload(args, known_names, known_refs)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    client = _create_client()

    # Pre-flight: verify model access before uploading audio
    if not args.skip_preflight:
        # Determine cache dir for preflight marker
        preflight_cache: Path | None = None
        if args.out_dir:
            preflight_cache = Path(args.out_dir)
        elif args.manifest:
            preflight_cache = Path(args.manifest).parent
        _preflight(client, args.model, preflight_cache)

    # Manifest setup
    manifest_path = Path(args.manifest) if args.manifest else None

    for path in audio_paths:
        req_id = str(uuid.uuid4())

        # Update manifest: in-progress
        if manifest_path and args.chunk_index is not None:
            _update_manifest(
                manifest_path,
                args.chunk_index,
                status="in_progress",
                request_id=req_id,
            )

        result, req_id, elapsed = _run_one(
            client,
            path,
            payload,
            read_timeout=args.timeout,
            max_wall=args.max_wall,
            request_id=req_id,
        )
        output = _format_output(result, args.response_format)

        # Inject request_id and elapsed_s into JSON output
        if args.response_format != "text":
            try:
                output_data = json.loads(output)
                if isinstance(output_data, dict):
                    output_data["request_id"] = req_id
                    output_data["elapsed_s"] = round(elapsed, 1)
                    output = json.dumps(output_data, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                pass

        if args.stdout:
            print(output)
            continue
        out_path = _build_output_path(path, args.response_format, args.out, args.out_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote {out_path}")

        # Update manifest: done
        if manifest_path and args.chunk_index is not None:
            # Store path relative to manifest dir so working dir is portable.
            # merge_chunks.py resolves transcript_file against manifest_path.parent.
            try:
                rel = out_path.resolve().relative_to(manifest_path.parent.resolve())
                transcript_file_value = str(rel)
            except ValueError:
                transcript_file_value = str(out_path.resolve())
            _update_manifest(
                manifest_path,
                args.chunk_index,
                status="done",
                transcript_file=transcript_file_value,
            )


if __name__ == "__main__":
    main()
