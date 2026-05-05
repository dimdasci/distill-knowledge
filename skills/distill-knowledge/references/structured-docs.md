# Structured Documents (Steps 7–10)

Only invoked if user requests at Gate 2. The transcript is always the primary artifact.

## Step 7 — Plan structure

Read transcript; identify:
- **Topics** — coherent segments worth their own article
- **Decisions** made during the meeting
- **Action items** — task + owner + deadline
- **Open questions** still unresolved
- **Pain points** + **proposals**

Propose a short list:

```
summary.md                    — overview + decisions + actions
topics/{slug-1}.md            — {one-line}
topics/{slug-2}.md            — {one-line}
```

Note which screenshots belong to which topic. Do not produce files yet.

## Step 8 — Gate 3 + emit

Confirm structure with user, then write files per templates below.

## Decision rules (structured docs only)

| Situation | Action |
|---|---|
| Meeting < 5 min | Summary only, skip topic split |
| Diagram / flowchart on screen | Screenshot **and** Mermaid |
| Data table on screen | Screenshot **and** markdown table |

## Output shapes

See [output-templates.md](output-templates.md) for the full `summary.md`, `topics/{slug}.md` (default and process variants), and Mermaid diagram conventions.

## Step 10 — Report

```
outbox/{meeting-slug}/
  transcript.md           ({n} turns, {duration})
  screenshots/            ({n} images)
  summary.md              [if structured]
  topics/                 ({n} articles) [if structured]
```

Stop. Do not run any downstream skill automatically.
