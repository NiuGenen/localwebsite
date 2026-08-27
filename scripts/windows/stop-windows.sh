#!/bin/bash
# Windows（Git Bash）停止脚本：Flask 后端 + Nginx
# 用法：bash scripts/windows/stop-windows.sh
set -e

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NGINX_CONF="$DIR/nginx.windows.conf"

if [ -z "$NGINX_BIN" ]; then
    NGINX_BIN="nginx"
fi

echo "停止 nginx..."
if command -v "$NGINX_BIN" >/dev/null 2>&1; then
    DIR_WIN=$(cygpath -w "$DIR")
    NGINX_CONF_WIN=$(cygpath -w "$NGINX_CONF")
    "$NGINX_BIN" -p "$DIR_WIN\\" -c "$NGINX_CONF_WIN" -s quit >/dev/null 2>&1 || true
else
    echo "  nginx 命令不可用，若已用其它方式安装请设置 NGINX_BIN"
fi

echo "停止 Flask..."
FPID="$DIR/logs/flask.pid"
if [ -f "$FPID" ]; then
    kill "$(cat "$FPID")" 2>/dev/null || true
    rm -f "$FPID"
fi

rm -f "$DIR/logs/nginx_bash.pid" 2>/dev/null || true

echo "完成，服务已停止。"
