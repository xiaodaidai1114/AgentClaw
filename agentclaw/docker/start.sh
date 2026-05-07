#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agentclaw}"

# 默认参数
PROJECT_DIR="${1:-.}"
PORT="${FA_PORT:-${PORT:-8000}}"
HOST="${FA_HOST:-0.0.0.0}"

# =====================
# 检查运行环境
# =====================

# 检查 Python
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "❌ 未检测到 Python，请先安装 Python 3.10+" >&2
    echo "   推荐: https://www.python.org/downloads/" >&2
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "   Python: $PY_VERSION ($PYTHON)"

# 检查 agentclaw 是否已安装
if ! command -v agentclaw &>/dev/null; then
    echo "⚠️  未检测到 agentclaw，正在安装..."
    if command -v uv &>/dev/null; then
        uv pip install agentclaw-ai
    elif command -v pip &>/dev/null; then
        pip install agentclaw-ai
    else
        echo "❌ 未检测到 pip 或 uv，无法自动安装 agentclaw" >&2
        echo "   请手动安装: pip install agentclaw-ai" >&2
        exit 1
    fi
    echo "   ✅ agentclaw 已安装"
fi

# 检查项目目录
PROJECT_PATH=$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "")
if [ -z "$PROJECT_PATH" ]; then
    echo "❌ 项目目录不存在: $PROJECT_DIR" >&2
    exit 1
fi

if [ ! -f "$PROJECT_PATH/server.py" ]; then
    echo "⚠️  项目目录中未找到 server.py: $PROJECT_PATH"
    echo "   提示: 运行 agentclaw init $PROJECT_DIR 初始化项目"
fi

if [ ! -f "$PROJECT_PATH/models.json" ]; then
    echo "⚠️  项目目录中未找到 models.json: $PROJECT_PATH"
    echo "   提示: 请创建 models.json 配置 LLM 模型和 API Key"
fi

# =====================
# 启动 Docker 基础设施
# =====================

if ! command -v docker &>/dev/null; then
    echo "⚠️  Docker 不可用，跳过基础设施启动"
    echo "   以下功能将不可用: 执行追踪、会话持久化、定时调度等"
    echo "   安装 Docker: https://docs.docker.com/get-docker/"
else
    echo "🐳 启动基础设施..."
    if docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" up -d --wait; then
        echo "   ✅ PostgreSQL 已启动 (localhost:${PG_PORT:-5432})"
        echo "   ✅ Redis 已启动 (localhost:${REDIS_PORT:-6379})"
        echo "   ✅ MinIO 已启动 (API: localhost:${MINIO_API_PORT:-9000}, Console: localhost:${MINIO_CONSOLE_PORT:-9001})"
        echo "   ✅ Milvus 已启动 (localhost:${MILVUS_PORT:-19530})"
        echo "   ✅ Adminer 已启动 (localhost:${ADMINER_PORT:-8080})"
    else
        echo "⚠️  基础设施启动失败，以内存模式继续"
    fi
fi

# 注入环境变量（不覆盖已有值）
export PG_HOST="${PG_HOST:-127.0.0.1}"
export PG_PORT="${PG_PORT:-5432}"
export PG_USER="${PG_USER:-postgres}"
export PG_PASSWORD="${PG_PASSWORD:-agentclaw}"
export PG_DATABASE="${PG_DATABASE:-agentclaw}"
export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export MINIO_API_PORT="${MINIO_API_PORT:-9000}"
export MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-9001}"
export MILVUS_PORT="${MILVUS_PORT:-19530}"
export MILVUS_HTTP_PORT="${MILVUS_HTTP_PORT:-9091}"
export ADMINER_PORT="${ADMINER_PORT:-8080}"

echo ""
echo "🚀 启动 AgentClaw 服务器..."
echo "   项目目录: $PROJECT_PATH"
echo "   端口: $PORT"
echo "   数据库: PostgreSQL ($PG_HOST:$PG_PORT)"
echo ""

exec agentclaw serve -d "$PROJECT_PATH" -p "$PORT" -h "$HOST"
