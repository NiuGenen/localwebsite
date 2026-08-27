#!/bin/bash
# Windows（Git Bash）状态检查脚本
# 用法：bash scripts/windows/check-windows.sh
DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "== 进程状态 =="
FPID="$DIR/logs/flask.pid"
if [ -f "$FPID" ]; then
    PID="$(cat "$FPID")"
    if kill -0 "$PID" 2>/dev/null; then
        echo "Flask backend : RUNNING (pid $PID)"
    else
        echo "Flask backend : NOT RUNNING"
    fi
else
    echo "Flask backend : NOT RUNNING (无 pid 文件)"
fi

if tasklist 2>/dev/null | grep -i nginx >/dev/null; then
    echo "Nginx         : RUNNING"
else
    echo "Nginx         : NOT RUNNING"
fi

echo ""
echo "== HTTP 检查 =="
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8080/ 2>/dev/null)
if [ "$CODE" = "200" ]; then
    echo "首页 http://localhost:8080/ -> HTTP 200"
else
    echo "首页 http://localhost:8080/ -> 不可访问 ($CODE)"
fi

LOCAL=$(curl -s --max-time 5 http://localhost:8080/api/local 2>/dev/null)
if [ -n "$LOCAL" ]; then
    echo "api/local 本机判定 -> $LOCAL"
else
    echo "api/local 本机判定 -> 不可访问"
fi
