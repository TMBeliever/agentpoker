#!/usr/bin/env bash
#
# Sohu Agent Poker 训练场/实战比赛启动脚本
# 默认使用 candidate_v3_balanced 模型接入当前活跃赛事 (Play S11 训练场)
#
set -euo pipefail
export PYTHONUNBUFFERED=1

STRATEGY="${1:-models/champion.json}"
shift || true

if command -v uv >/dev/null 2>&1; then
    exec uv run python -m agentpoker.cli live --strategy "$STRATEGY" "$@"
elif [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python -m agentpoker.cli live --strategy "$STRATEGY" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m agentpoker.cli live --strategy "$STRATEGY" "$@"
else
    echo "错误: 未找到 Python 或 uv 环境，请先安装 uv 或创建虚拟环境。" >&2
    exit 1
fi
