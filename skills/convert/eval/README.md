# Trigger evaluation for `convert` skill

Tests whether the skill's `description` field causes agents to activate it on relevant prompts and ignore it on irrelevant ones.

Based on the [Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions) guide.

## Query design

**22 queries total** — 12 should-trigger, 10 should-not-trigger.

Split into **train (60%)** and **validation (40%)** sets to avoid overfitting when iterating on the description.

| Split      | Should trigger | Should not | Total |
|------------|---------------|------------|-------|
| train      | 7             | 6          | 13    |
| validation | 5             | 4          | 9     |

### Should-trigger axes covered

| Axis | Examples |
|---|---|
| Phrasing (formal ↔ casual) | `t01` formal path, `t04` "hey can u" |
| Explicitness (direct ↔ indirect) | `t06` "need speaker labels", `t03` "what did we talk about" |
| Detail (terse ↔ context-heavy) | `t07` 6-word prompt, `t09` full paragraph |
| Input type variety | meeting, interview, voice memo, conference, WhatsApp voice |
| Non-English | `t08` Russian |
| Complexity (single ↔ multi-step) | `t04` just transcribe, `t09` transcript + screenshots |

### Should-not-trigger (near-misses)

Every negative query shares keywords or concepts with the skill but needs something different:

| Query | Shared concept | Actual task |
|---|---|---|
| `n01` | "transcript" | Edit existing markdown |
| `n02` | audio/video file | Format conversion |
| `n03` | "meeting" | Write agenda |
| `n04` | `.m4a` file | Probe metadata |
| `n05` | audio recording | Audio editing |
| `n06` | transcription | Live captions (not a file) |
| `n07` | "summarize" | PDF summarization |
| `n08` | "record" + "meetings" | Tool recommendation |
| `n09` | video + subtitles | Burn-in subtitles |
| `n10` | audio recording | Quality analysis |

## Running

```bash
# All queries, 3 runs each (default)
./run-trigger-eval.sh

# Train set only (use while iterating on description)
./run-trigger-eval.sh --split train

# Validation set (check generalization after changes)
./run-trigger-eval.sh --split validation

# Custom runs and threshold
./run-trigger-eval.sh --runs 5 --threshold 0.6
```

Requires `claude` (Claude Code CLI) and `jq`.

## Output

Terminal shows per-query pass/fail. Full report written to `report.json`:

```json
{
  "skill": "convert",
  "summary": { "total": 22, "passed": 20, "failed": 2 },
  "failures": [ ... ],
  "results": [ ... ]
}
```

## Iterating on the description

1. Run against **train** set: `./run-trigger-eval.sh --split train`
2. Fix failures by editing `description` in `SKILL.md` — generalize, don't overfit to specific wording
3. Repeat until train passes
4. Validate: `./run-trigger-eval.sh --split validation`
5. Pick the iteration with best validation pass rate (not necessarily the last one)
