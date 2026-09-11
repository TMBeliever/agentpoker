#!/usr/bin/env bash
#
# 训练启动脚本。所有参数都可以用环境变量覆盖，例如：
#
#   GENERATIONS=6 RUNS_PER_CANDIDATE=60 ./run_train.sh --no-resume
#
# 命令行剩余参数会原样透传给底层 train 命令（如 --no-resume / --track）。
#
# --- 训练规模 ---
#   GENERATIONS         训练代数。每代耗时取决于 RUNS_PER_CANDIDATE 和 AGENTS
#                       实测：36人×30场 约 2.5 分钟/代；96人×120场 约 30 分钟/代
#   POPULATION          每代候选策略数量（默认 16）。越大探索越广，每代耗时线性增加
#
# --- 评估精度（噪声的关键）---
#   RUNS_PER_CANDIDATE  每个候选评估的锦标赛场数（默认 120）
#                       30 场时标准误约 ±0.07，相邻代差异会被噪声淹没；120 场降到约 ±0.035
#   REEVAL_RUNS         每代初选后用全新对手池复评的场数（默认 60）
#                       用于消除「冠军只是抽样运气」的偏差
#   FINAL_RACE          最终在留出集上验证冠军的场数（默认 500），决定报告数字的可信度
#
# --- 赛场规模 ---
#   AGENTS              每场锦标赛参赛人数（默认 36）。建议对齐真实赛场规模
#
# --- 性能 ---
#   WORKERS             并发进程数，默认取 CPU 核数
#
# --- 输出 ---
#   SAVE                冠军模型输出路径（默认 models/champion.json）
#
# --- 混练开关（通用轨中混入真实对手画像）---
#   MIX_PROFILES        设为非空即启用。不加则纯原型训练
#   PROFILE_MIN_HANDS   画像质量门槛：手数低于此值不采用（默认 100）
#   PROFILE_SHARE       画像在对手池中最多占的座位比例（默认 0.5），其余留给原型
#   PROFILES            画像文件路径，默认 models/opponent_profiles.json
#
set -euo pipefail
cd "$(dirname "$0")"

EXTRA=()
if [ -n "${MIX_PROFILES:-}" ]; then EXTRA+=(--mix-profiles); fi
if [ -n "${PROFILE_MIN_HANDS:-}" ]; then EXTRA+=(--profile-min-hands "$PROFILE_MIN_HANDS"); fi
if [ -n "${PROFILE_SHARE:-}" ]; then EXTRA+=(--profile-share "$PROFILE_SHARE"); fi
if [ -n "${PROFILE_TOP:-}" ]; then EXTRA+=(--profile-top "$PROFILE_TOP"); fi
if [ -n "${PROFILES:-}" ]; then EXTRA+=(--profiles "$PROFILES"); fi
if [ -n "${BASE_MODEL:-}" ]; then EXTRA+=(--base-model "$BASE_MODEL"); fi

uv run python -m agentpoker.cli train \
  --generations "${GENERATIONS:-30}" \
  --population "${POPULATION:-16}" \
  --runs "${RUNS_PER_CANDIDATE:-120}" \
  --agents "${AGENTS:-36}" \
  --workers "${WORKERS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)}" \
  --final-race "${FINAL_RACE:-500}" \
  --reeval-runs "${REEVAL_RUNS:-60}" \
  --save "${SAVE:-models/champion.json}" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  "$@"
