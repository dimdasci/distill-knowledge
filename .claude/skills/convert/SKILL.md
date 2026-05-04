---
name: convert
description: Use when a meeting recording (video, audio, and/or VTT transcript) appears in `inbox/`, or when the user asks to process, clean up, or extract knowledge from such a recording — including requests for inlined screenshots from screen-sharing moments or for splitting the meeting into topic articles.
---

# Convert Meeting Recording → Knowledge Markdown

Always emit `outbox/{meeting-slug}/transcript.md`; screenshots inline when useful; `summary.md` + `topics/{slug}.md` only on request. `{meeting-slug}` = `kebab-case-topic-YYYYMMDD`. Never touch `inbox/` or `knowledge/`. Steps, shapes, prompts: `references/output-templates.md`. ffmpeg: `references/ffmpeg.md`.

## Setup

Scripts run via [`uv`](https://docs.astral.sh/uv/) (PEP 723, no venv).

1. **`uv`:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Verify `ffmpeg` + `ffprobe`:**
   ```bash
   command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && ffmpeg -version | head -1
   ```
   Prints version → continue. Else **do not auto-install**; ask:
   > "ffmpeg required, not on PATH. Install for you, or yourself? (**auto** / **manual**)"

   **auto** — detect OS, confirm, run matching install, re-run detect, proceed only on success:
   - macOS + `brew`: `brew install ffmpeg`
   - macOS, no `brew`: install Homebrew (`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`) then `brew install ffmpeg`
   - Debian/Ubuntu: `sudo apt-get update && sudo apt-get install -y ffmpeg`
   - Fedora/RHEL: `sudo dnf install -y ffmpeg`
   - Arch: `sudo pacman -S --noconfirm ffmpeg`
   - Windows / ambiguous → **manual**

   **manual** — https://ffmpeg.org/download.html; on "done", re-run detect.
3. **Re-transcription:** set `OPENAI_API_KEY` (see `transcribe` Setup).

## Workflow

Three gates — do not skip.

1. **Inventory + probe** inbox media + VTT.
2. **Gate 1** — findings, preprocessing plan, `{meeting-slug}`.
3. **Preprocess** what Gate 1 approved (convert, audio extract, VTT parse, re-transcribe + diarize, screen probe). Re-transcribe calls `transcribe`; on non-zero exit follow [`transcribe/SKILL.md` → Error handling](../transcribe/SKILL.md#error-handling), surface verbatim, **wait before retrying**, never fall back silently.
4. **Cleaned transcript (mandatory)** → `outbox/{meeting-slug}/transcript.md`. Cue: `[00:00:12] **Alice:** ...`. Faithful, never paraphrased.
5. **Screenshots inline** — skip if no screen content; else `timestamp + 2 s`, `-q:v 2`, inline at cue.
6. **Gate 2** — structured docs or transcript only?
7. **Plan structure** — topics, decisions, actions, open questions, pain points, proposals.
8. **Gate 3 + emit** `summary.md`, `topics/{slug}.md` (default/process), Mermaid for flow/decision shots.
9. **Report** + stop.

## Decision rules

| Situation | Decision |
|---|---|
| VTT speakers usable | Parse VTT, skip re-transcribe |
| VTT generic / garbled | Re-transcribe + diarize |
| Video unreadable / wrong container | Convert first |
| Probe: only faces | Zero screenshots |
| Probe: UI / slides / docs | Screenshots in scope |
| Meeting < 5 min | Summary only, skip topic split |
| Diagram / flowchart on screen | Screenshot **and** Mermaid |
| Data table on screen | Screenshot **and** markdown table |
| Non-English (FR/DE in LU) | Read VTT directly; auto detection won't fire |

## Anti-patterns

- **Don't skip the cleaned transcript.** Never optional.
- **Don't paraphrase.** Clean punctuation, merge same-speaker runs; never reword.
- **Don't write outside `outbox/{meeting-slug}/`.**
- **Don't structure without approval** (Gate 2 + Gate 3).
- **Don't screenshot everything.** Visual must add what text doesn't.
- **Don't transcribe a usable VTT.** Cheapest source of truth.
- **Don't fabricate screen content.** Unclear → mark it.
- **Don't run the next skill.** Stop after Step 9.
