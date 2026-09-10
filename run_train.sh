#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m agentpoker.cli train \
  --generations "${GENERATIONS:-30}" \
  --population "${POPULATION:-16}" \
  --runs "${RUNS_PER_CANDIDATE:-30}" \
  --agents "${AGENTS:-36}" \
  --workers "${WORKERS:-$(nproc 2>/dev/null || echo 4)}" \
  --final-race "${FINAL_RACE:-500}" \
  --save "${SAVE:-models/champion.json}"
