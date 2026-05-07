#!/bin/bash
# ============================================
# Creator AI Toolbox - 一键上线脚本
# 用法: bash start.sh
# ============================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
CLOUDFLARED="$HOME/.local/bin/cloudflared"
TUNNEL_URL_FILE="/tmp/creator_toolbox_url.txt"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════╗"
echo "║   🚀 Creator AI Toolbox 启动器      ║"
echo "╚══════════════════════════════════════╝"
echo -e "${NC}"

# 1. 检查/安装 cloudflared
if [ ! -f "$CLOUDFLARED" ]; then
    echo -e "${YELLOW}📥 正在安装 Cloudflare Tunnel...${NC}"
    mkdir -p "$HOME/.local/bin"
    if [ -f /tmp/cloudflared-new ] && [ -s /tmp/cloudflared-new ]; then
        cp /tmp/cloudflared-new "$CLOUDFLARED"
        chmod +x "$CLOUDFLARED"
    elif [ -f /tmp/cloudflared ] && [ -s /tmp/cloudflared ]; then
        cp /tmp/cloudflared "$CLOUDFLARED"
        chmod +x "$CLOUDFLARED"
    else
        echo -e "${YELLOW}正在下载 cloudflared (约25MB)...${NC}"
        wget -q --show-progress -O "$CLOUDFLARED" \
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" || {
            echo -e "${RED}❌ 下载失败。请手动下载后放到 $CLOUDFLARED${NC}"
            echo "   wget -O ~/.local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
            echo "   chmod +x ~/.local/bin/cloudflared"
            exit 1
        }
        chmod +x "$CLOUDFLARED"
    fi
    echo -e "${GREEN}✅ cloudflared 就绪${NC}"
fi

# 2. 启动 Flask
echo -e "${YELLOW}🔧 启动后端...${NC}"
pkill -f "python3 app.py" 2>/dev/null || true
sleep 1

cd "$BACKEND_DIR"
nohup python3 app.py > /tmp/flask_server.log 2>&1 &
sleep 2

if curl -s http://localhost:5000/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Flask 后端运行在 :5000${NC}"
else
    echo -e "${RED}❌ Flask 启动失败${NC}"
    cat /tmp/flask_server.log | tail -20
    exit 1
fi

# 3. 写入前端 API 占位符 (运行时自动检测)
# 前端已通过 window.location.origin 动态获取，无需修改

# 4. 启动 Cloudflare Tunnel
echo -e "${YELLOW}🌐 启动公网隧道...${NC}"
echo ""

"$CLOUDFLARED" tunnel --url http://localhost:5000 2>&1 | while IFS= read -r line; do
    echo "$line"
    if [[ "$line" =~ https://.*\.trycloudflare\.com ]]; then
        URL=$(echo "$line" | grep -oP 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com')
        echo "$URL" > "$TUNNEL_URL_FILE"
        echo ""
        echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  🎉 上线成功!                     ║${NC}"
        echo -e "${GREEN}║  🔗 ${URL}${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
        echo ""
        echo -e "按 ${RED}Ctrl+C${NC} 停止服务"
    fi
done
