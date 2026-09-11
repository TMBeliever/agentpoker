#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo " 🃏 AgentPoker 2.0 Docker 一键部署"
echo "=========================================================="

if ! command -v docker >/dev/null 2>&1; then
    echo "❌ 检测到未安装 Docker。正在为您准备官方一键安装命令..."
    echo "请在 Ubuntu 上执行: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

mkdir -p models data logs

if [ ! -f .env ]; then
    echo "⚠️ 未发现 .env 文件，已自动生成基础模板..."
    cat << 'ENVEOF' > .env
AGENTPOKER_APP=https://poker.bang.sohu.com
AGENTPOKER_KEY=
AGENTPOKER_COMPETITION_ID=
ENVEOF
    echo "💡 如需实战对战，请在 .env 中填入你的 KEY 和 COMPETITION_ID"
fi

echo "🚀 正在构建并启动 AgentPoker 容器..."
docker compose up -d --build

echo "=========================================================="
echo " ✅ 容器已成功在后台启动！"
echo " • 访问控制台: http://<你的服务器公网IP>:8080"
echo " • 查看运行日志: docker compose logs -f"
echo " • 停止容器:     docker compose down"
echo "=========================================================="
