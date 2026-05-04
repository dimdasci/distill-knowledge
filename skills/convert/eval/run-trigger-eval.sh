#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Skill trigger evaluation for the `convert` skill.
#
# Runs each query through Claude Code and checks whether the skill was
# activated.  Produces a JSON report with per-query trigger rates and a
# pass/fail summary.
#
# Usage:
#   ./run-trigger-eval.sh                       # all queries, 3 runs each
#   ./run-trigger-eval.sh --split train         # train set only
#   ./run-trigger-eval.sh --split validation    # validation set only
#   ./run-trigger-eval.sh --runs 5              # 5 runs per query
#   ./run-trigger-eval.sh --threshold 0.6       # custom pass threshold
#
# Requires: claude (Claude Code CLI), jq
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUERIES_FILE="${SCRIPT_DIR}/queries.json"
SKILL_NAME="convert"
RUNS=3
SPLIT=""
THRESHOLD=0.5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs)       RUNS="$2";      shift 2 ;;
    --split)      SPLIT="$2";     shift 2 ;;
    --threshold)  THRESHOLD="$2"; shift 2 ;;
    --queries)    QUERIES_FILE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,/^# ---/{ /^# ---/d; s/^# //; s/^#//; p; }' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# --- preflight -------------------------------------------------------------
for cmd in claude jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Error: $cmd not found" >&2; exit 1; }
done

if [[ ! -f "$QUERIES_FILE" ]]; then
  echo "Error: queries file not found: $QUERIES_FILE" >&2
  exit 1
fi

# --- filter queries by split ------------------------------------------------
if [[ -n "$SPLIT" ]]; then
  QUERIES=$(jq --arg s "$SPLIT" '[.[] | select(.split == $s)]' "$QUERIES_FILE")
else
  QUERIES=$(cat "$QUERIES_FILE")
fi

COUNT=$(echo "$QUERIES" | jq 'length')
if [[ "$COUNT" -eq 0 ]]; then
  echo "No queries to run (split=$SPLIT)" >&2
  exit 1
fi

echo "=== Skill trigger eval: $SKILL_NAME ==="
echo "    Queries:   $COUNT"
echo "    Runs/each: $RUNS"
echo "    Threshold: $THRESHOLD"
echo "    Split:     ${SPLIT:-all}"
echo ""

# --- check if skill triggered -----------------------------------------------
check_triggered() {
  local query="$1"
  # Run claude in pipe mode with stream-json (verbose) output.
  # Each line is a JSON event. Look for an assistant message containing a
  # Skill tool_use call matching our skill name.
  claude -p "$query" --output-format stream-json --verbose 2>/dev/null \
    | jq -e --slurp --arg skill "$SKILL_NAME" \
      'any(.[]; .type == "assistant" and
        (.message.content // [] | any(
          .type == "tool_use" and .name == "Skill" and .input.skill == $skill
        ))
      )' \
      > /dev/null 2>&1
}

# --- run eval ----------------------------------------------------------------
RESULTS="[]"
PASS=0
FAIL=0

for i in $(seq 0 $((COUNT - 1))); do
  ROW=$(echo "$QUERIES" | jq ".[$i]")
  ID=$(echo "$ROW"     | jq -r '.id')
  QUERY=$(echo "$ROW"  | jq -r '.query')
  SHOULD=$(echo "$ROW" | jq -r '.should_trigger')

  triggers=0
  for run in $(seq 1 "$RUNS"); do
    if check_triggered "$QUERY"; then
      triggers=$((triggers + 1))
    fi
  done

  RATE=$(echo "$triggers $RUNS" | awk '{printf "%.2f", $1/$2}')

  # Pass logic: should_trigger → rate ≥ threshold; !should_trigger → rate < threshold
  if [[ "$SHOULD" == "true" ]]; then
    PASSED=$(echo "$RATE $THRESHOLD" | awk '{print ($1 >= $2) ? "true" : "false"}')
  else
    PASSED=$(echo "$RATE $THRESHOLD" | awk '{print ($1 < $2) ? "true" : "false"}')
  fi

  if [[ "$PASSED" == "true" ]]; then
    STATUS="✅"
    PASS=$((PASS + 1))
  else
    STATUS="❌"
    FAIL=$((FAIL + 1))
  fi

  echo "  $STATUS  $ID  rate=$RATE  should_trigger=$SHOULD"

  RESULTS=$(echo "$RESULTS" | jq \
    --arg id "$ID" \
    --arg query "$QUERY" \
    --argjson should "$SHOULD" \
    --argjson triggers "$triggers" \
    --argjson runs "$RUNS" \
    --arg rate "$RATE" \
    --argjson passed "$PASSED" \
    '. + [{id: $id, query: $query, should_trigger: $should, triggers: $triggers, runs: $runs, trigger_rate: ($rate | tonumber), passed: $passed}]'
  )
done

# --- summary -----------------------------------------------------------------
TOTAL=$((PASS + FAIL))
echo ""
echo "=== Results: $PASS/$TOTAL passed ($FAIL failed) ==="

# Write report
REPORT_PATH="${SCRIPT_DIR}/report.json"
echo "$RESULTS" | jq '{
  skill: "'"$SKILL_NAME"'",
  runs_per_query: '"$RUNS"',
  threshold: '"$THRESHOLD"',
  split: "'"${SPLIT:-all}"'",
  summary: {
    total: (. | length),
    passed: [.[] | select(.passed)] | length,
    failed: [.[] | select(.passed | not)] | length
  },
  failures: [.[] | select(.passed | not)],
  results: .
}' > "$REPORT_PATH"
echo "Report written to $REPORT_PATH"
