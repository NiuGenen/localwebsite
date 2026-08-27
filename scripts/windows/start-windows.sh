#!/bin/bash
# Windows（Git Bash）启动脚本：Flask 后端 + Nginx
# 用法：bash scripts/windows/start-windows.sh
# 可选：NGINX_BIN=/path/to/nginx.exe bash scripts/windows/start-windows.sh
set -e

# 项目根目录 = scripts/windows/ 上溯两级
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DIR"

VENV_PYTHON="$DIR/venv-win/Scripts/python.exe"
BACKEND_PY="$DIR/backend.py"
NGINX_CONF="$DIR/nginx.windows.conf"

# 选择 nginx 可执行文件
if [ -z "$NGINX_BIN" ]; then
    NGINX_BIN="nginx"
fi

if [ ! -f "$VENV_PYTHON" ]; then
    echo "错误: 未找到虚拟环境 $VENV_PYTHON"
    echo "请先运行: python -m venv venv-win && venv-win/Scripts/pip install -r requirements.txt"
    exit 1
fi

if ! command -v "$NGINX_BIN" >/dev/null 2>&1; then
    echo "错误: 未找到 nginx ($NGINX_BIN)"
    echo "  - 系统级: winget install nginx（装完重开终端）; 或"
    echo "  - 指定路径: NGINX_BIN=/path/to/nginx.exe bash scripts/windows/start-windows.sh"
    exit 1
fi

mkdir -p "$DIR/logs" "$DIR/temp"

# 先停掉可能已运行的实例（忽略错误）
bash "$DIR/scripts/windows/stop-windows.sh" >/dev/null 2>&1 || true

echo "启动 Flask 后端 (端口 5000)..."
"$VENV_PYTHON" "$BACKEND_PY" >"$DIR/logs/flask.log" 2>&1 &
echo $! > "$DIR/logs/flask.pid"

echo "启动 nginx (端口 8080)..."
# Windows 程序需要 Windows 风格路径
DIR_WIN=$(cygpath -w "$DIR")
NGINX_CONF_WIN=$(cygpath -w "$NGINX_CONF")
"$NGINX_BIN" -p "$DIR_WIN\\" -c "$NGINX_CONF_WIN" &
NGINX_PID=$!
echo $NGINX_PID > "$DIR/logs/nginx_bash.pid"

sleep 1

echo ""
echo "完成，服务已启动："
echo "  本机访问:    http://localhost:8080"
echo "  局域网访问:  http://<本机局域网IP>:8080"
echo "  日志目录:    $DIR/logs"
echo "停止:    bash scripts/windows/stop-windows.sh"
echo "检查:    bash scripts/windows/check-windows.sh"
