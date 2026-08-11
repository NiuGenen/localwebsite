#!/bin/bash
SVC_BACKEND="localwebsite-backend.service"
SVC_NGINX="localwebsite-nginx.service"

check_unit() {
    local svc="$1"
    local enabled=""
    local active=""

    if systemctl --user is-enabled "$svc" > /dev/null 2>&1; then
        enabled="enabled"
    else
        enabled="not-enabled"
    fi

    active="$(systemctl --user is-active "$svc" 2>/dev/null)"
    if [ "$active" != "active" ]; then
        active="inactive"
    fi

    printf "%-34s  enabled=%-12s active=%s\n" "$svc" "$enabled" "$active"
    if [ "$active" != "active" ]; then
        echo "  -> 详情: systemctl --user status $svc"
        echo "  -> 日志: journalctl --user -u $svc -n 20"
    fi
}

if ! loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
    echo "警告: Linger 未开启，服务仅在登录后启动。执行: sudo loginctl enable-linger $USER"
    echo ""
fi

check_unit "$SVC_BACKEND"
check_unit "$SVC_NGINX"

echo ""
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null | grep -q 200; then
    echo "HTTP 检查: 首页 http://localhost:8080/ 返回 200"
else
    echo "HTTP 检查: 首页 http://localhost:8080/ 不可访问"
fi
