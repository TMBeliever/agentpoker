#!/usr/bin/env bash
#
# Sohu Agent Poker 锦标赛擂台赛启动脚本
# 支持直接在终端交互式勾选所有可用模型、原型 Bot 与真实画像
#
set -euo pipefail

# 优先使用 uv，其次使用本地虚拟环境 python，最后使用系统 python3
if command -v uv >/dev/null 2>&1; then
    exec uv run python -m agentpoker.cli battle "$@"
elif [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python -m agentpoker.cli battle "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m agentpoker.cli battle "$@"
else
    echo "错误: 未找到 Python 或 uv 环境，请先安装 uv 或创建虚拟环境。" >&2
    exit 1
fi
