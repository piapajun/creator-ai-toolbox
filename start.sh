#!/bin/bash
# ============================================
# Creator AI Toolbox — 快速启动 (公网版)
# 用法: bash start.sh
# 等同: python3 dev.py --tunnel
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Creator AI Toolbox 启动中..."
python3 dev.py --tunnel "$@"
