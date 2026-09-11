#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

echo "========================================================"
echo " 🃏 正在启动 AgentPoker 2.0 全能可视化控制台..."
echo " 监听地址: http://${HOST}:${PORT}"
echo "========================================================"

if command -v uv >/dev/null 2>&1; then
    exec uv run python -m agentpoker.cli dashboard --host "${HOST}" --port "${PORT}" "$@"
else
    exec python3 -m agentpoker.cli dashboard --host "${HOST}" --port "${PORT}" "$@"
fi
