# meetings-to-docs

An [Agent Skill](https://skills.sh) that turns recorded meetings into speaker-labelled markdown transcripts, optionally with screenshots and topic-by-topic documents.

Built for knowledge handovers, interviews, screen-share walkthroughs, and voice notes — anything where the value is in what was said, not in the audio.

## Install

```bash
npx skills add dim-kharitonov/meetings-to-docs
```

This drops `distill-knowledge` into your agent's skills directory. Works with Claude Code and any other agent that reads the [Agent Skills](https://skills.sh) format.

Manual install: clone this repo, copy `skills/distill-knowledge/` into your agent's skills folder.

## Prerequisites

| Tool | Why |
|---|---|
| [`uv`](https://docs.astral.sh/uv/) | Runs the Python scripts (PEP 723, no venv to manage) |
| `ffmpeg`, `ffprobe` | Audio normalisation, video → audio extraction, screenshot frames |
| `OPENAI_API_KEY` | Transcription via `gpt-4o-transcribe` |
| Python ≥ 3.10 | `uv` installs the right interpreter automatically |

The skill checks all of these on first run.

## How to use

1. Drop the recording in `inbox/`. Audio or video. If you have a `.vtt` next to it, leave it there — the skill uses it as a speaker-aligned skeleton.
2. Ask the agent in plain English what you want.
3. Answer three intake questions: language, number of speakers, topic + any proper names or specialised terms.
4. The agent emits everything under `outbox/{slug}/`. It never writes outside that folder.

The skill always asks before transcribing. If you do not answer the intake questions, it will not call the API.

## Examples

### Voice note → transcript only

> Process the voice memo I just dropped in inbox.

You get one file:

```
outbox/quick-thoughts-q3-20260420/
└── transcript.md
```

`transcript.md` has timestamped speaker turns. If there is one speaker, it is paragraphed by topic. The transcript is faithful to what was said — recoverable garble is repaired, silences are not filled.

### Process handover → topic docs with screenshots

Anonymised prompt:

> I have a recording of a process handover from Person A to Person B, in Spanish. The recording with screen-share and the VTT are in `inbox/`, prefixed `GMTYYYYMMDD-Recording`. I need documents that describe the processes as Person A presented them, but in English, split by topic with an index file. All tool explanations must be supported by clear screenshots with sequential numbering and explanatory titles. The VTT transcription is likely low quality and needs re-transcription.

You get:

```
outbox/process-handover-20260420/
├── summary.md              # index — one row per topic, links into topics/
├── transcript.md           # full transcript, faithful to the source language
├── topics/
│   ├── 01-big-picture.md
│   ├── 02-new-client-signal.md
│   ├── 03-pricing-reference.md
│   └── ...
└── screenshots/
    ├── 01.jpg
    ├── 02.jpg
    └── ...
```

`summary.md` lists who is who (built from screenshots and transcript), the big picture in one paragraph, and a table of every topic with a one-line description. It is the page you read first.

Each topic file follows the same shape: **What it is → What you do → What you see → Things to watch out for → Source**. Screenshots are inline with explanatory captions, numbered continuously across all topics.

## What a topic document looks like

The block below is a synthetic excerpt with placeholder screenshots. In real outputs the screenshots are frames extracted from the recording at the right timestamps.

---

> ### Step 5 — Setting up the company file
>
> #### What it is
>
> The dashboard is where a new client is registered before any monthly invoice can run. Three fields are mandatory to enable billing: name, address, contact person.
>
> #### What you do
>
> 1. Open the dashboard → find the company in the `Companies` list.
> 2. Read the `Onboarding` tab. Most data should already be there.
> 3. Click `Company info`. Fill any field that is empty.
> 4. If the company is **in incorporation**, type `(In Incorporation)` after the name. Without this tag, billing rejects the company.
> 5. Save. Confirm the read-only view shows everything correctly.
>
> #### What you see
>
> ![Screenshot 12](docs/assets/example-screenshot-01.png)
> **Screenshot 12 — `Company info` edit form for Acme Holding.** Header: *"New company — Company info"*, subtitle *"Acme Holding S.à r.l. (In Incorporation)"*. Fields visible top to bottom: Client reference (`901908`, auto-populated), BOB-equivalent dossier (empty), VAT ID (empty), RCS number (empty), Financial year (`31.12.`), Address (empty), Contact person (empty). Left sidebar: `Companies | Invoices | Tasks | Settings`.
>
> ![Screenshot 13](docs/assets/example-screenshot-02.png)
> **Screenshot 13 — Monthly invoices view, April 2026.** Header: *"Monthly invoices — April 2026"*, *"12 drafts pending review"*. Table columns: Client, Plan, Amount, Status. Rows visible: Acme Holding (Standard, €450, Draft), Borealis Trade (Premium, €890, Draft), Ceres Studio (Standard, €450, Approved), Delta Atelier (Payroll+, €1,210, Draft), Echo Logistics (Standard, €450, Draft), Forge & Sons (Starter, €220, Draft).
>
> #### Things to watch out for
>
> - Always tag `(In Incorporation)` on companies that are not yet registered. The platform refuses to bill unregistered companies.
> - The address field is the one most often missing. Order of fallbacks: Onboarding tab → public registry → CRM → original engagement letter.
>
> #### Source
>
> Transcript: parts 34, 35, 36 (timestamps 46:30–52:30).

---

## Repo layout

| Path | What it is |
|---|---|
| `skills/distill-knowledge/` | The skill itself — what `npx skills add` installs |
| `inbox/` | Drop recordings here |
| `outbox/` | Generated transcripts and topic docs |
| `tmp/` | Preprocessing intermediates (chunks, manifests). Safe to delete. |
| `eval/` | Trigger-evaluation harness — checks that the skill activates on the right prompts |
| `docs/assets/` | Placeholder images used in this README |

## Two transcription paths

| Input | Path | Notes |
|---|---|---|
| Recording with a good VTT | Render the VTT directly | Cheapest, most accurate. No API call. |
| Recording with a garbled VTT | VTT-aligned re-transcription | VTT gives speaker labels and turn timestamps; `gpt-4o-transcribe` gives clean text; the agent aligns. |
| Recording, no VTT, one speaker | Direct transcription | `gpt-4o-transcribe` on the prepared audio. |
| Recording, no VTT, many speakers | Diarise fallback | `gpt-4o-transcribe-diarize` in 8-minute chunks. Quality is unstable — the skill warns you. |

The skill picks the path at Gate 1 of the workflow and asks you to confirm before spending API budget.

## License

MIT — see [LICENSE](LICENSE).
