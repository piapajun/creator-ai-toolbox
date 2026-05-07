#!/bin/bash
# Creator AI Toolbox - 一键启动脚本
# 使用方式: bash start.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

echo "🚀 Creator AI Toolbox 启动中..."
echo ""

# 检查 Python
PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python，请安装 Python 3"
    exit 1
fi

echo "✅ Python: $($PYTHON --version)"

# 安装依赖
echo "📦 检查依赖..."
$PYTHON -m pip install flask flask-cors requests -q 2>/dev/null

# 启动
PORT=${PORT:-5000}
echo ""
echo "============================================" 
echo "  🌐 打开浏览器访问: http://localhost:$PORT"
echo "  🔥 热榜分析 | 🔍 爆文搜索 | ✍️ AI改写"
echo "============================================"
echo ""

cd "$BACKEND_DIR"
PORT=$PORT $PYTHON app.py
