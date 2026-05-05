# Setup & Prerequisites

Run these checks before first invocation. All three must pass.

## 1. uv

```bash
uv --version
```

If missing: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## 2. ffmpeg + ffprobe

```bash
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && ffmpeg -version | head -1
```

Prints version → proceed. If missing, **do not auto-install** — ask:

> "ffmpeg required, not on PATH. Install for you, or yourself? (**auto** / **manual**)"

- **auto** — detect OS, confirm, run install, re-verify. Per-OS commands in [ffmpeg reference](ffmpeg.md#installation).
- **manual** — point to https://ffmpeg.org/download.html; on "done", re-verify.

## 3. OPENAI_API_KEY

Read from process env first, then project `.env`. The script (`transcribe_diarize.py`) auto-loads `.env` and surfaces a clear error if the key is missing — no manual check needed unless preflight fails.

- `export OPENAI_API_KEY=sk-...` (wins over .env)
- Or `cp .env.example .env` + paste key (gitignored)
- Get key: https://platform.openai.com/api-keys
- Never paste in chat; never commit `.env`.

## Script dependency resolution

All scripts use PEP 723 inline metadata. Invoke via `uv run --script` — deps auto-resolve. If `uv run --script scripts/<name>.py --help` fails with an import error, surface the uv stderr verbatim. Do NOT `pip install` manually.
