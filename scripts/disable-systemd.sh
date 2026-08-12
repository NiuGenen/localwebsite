#!/bin/bash
SVC_BACKEND="localwebsite-backend.service"
SVC_NGINX="localwebsite-nginx.service"

systemctl --user disable --now $SVC_BACKEND $SVC_NGINX

echo "Done. 已取消开机自启并停止服务。"
echo "重新启用: ./scripts/setup-systemd.sh"
