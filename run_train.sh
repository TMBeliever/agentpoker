#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run python -m agentpoker.cli train \
  --generations "${GENERATIONS:-30}" \
  --population "${POPULATION:-16}" \
  --runs "${RUNS_PER_CANDIDATE:-120}" \
  --agents "${AGENTS:-36}" \
  --workers "${WORKERS:-$(nproc 2>/dev/null || echo 4)}" \
  --final-race "${FINAL_RACE:-500}" \
  --reeval-runs "${REEVAL_RUNS:-60}" \
  --save "${SAVE:-models/champion.json}"
