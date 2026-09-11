#!/usr/bin/env bash
set -e

PORT="9003"

echo "=========================================================="
echo " 🃏 AgentPoker 2.0 Docker 一键部署"
echo " 映射端口: ${PORT}"
echo "=========================================================="

mkdir -p models data logs
if [ ! -f .env ]; then
    touch .env
fi

DOCKER_CMD="docker"
if ! docker info >/dev/null 2>&1; then
    if sudo docker info >/dev/null 2>&1; then
        echo "💡 已自动启用 sudo 权限执行..."
        DOCKER_CMD="sudo docker"
    else
        echo "❌ 错误: Docker 服务未运行"
        exit 1
    fi
fi

if $DOCKER_CMD compose version >/dev/null 2>&1; then
    COMPOSE_CMD="$DOCKER_CMD compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
elif command -v sudo >/dev/null 2>&1 && sudo docker-compose version >/dev/null 2>&1; then
    COMPOSE_CMD="sudo docker-compose"
else
    echo "❌ 错误: 未检测到 docker compose"
    exit 1
fi

echo "🚀 正在启动容器..."
${COMPOSE_CMD} up -d --build

echo "=========================================================="
echo " ✅ 容器已成功在后台启动！"
echo " • 访问控制台: http://<你的服务器公网IP>:${PORT}"
echo " • 查看实时日志: ${COMPOSE_CMD} logs -f"
echo " • 停止容器:     ${COMPOSE_CMD} down"
echo "=========================================================="
