#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agentclaw}"

echo "🐳 停止基础设施..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" down

echo "   ✅ 已停止"
