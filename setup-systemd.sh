#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_UNIT_DIR="$HOME/.config/systemd/user"
NGINX_BIN="$HOME/nginx_install/usr/sbin/nginx"
NGINX_CONF="$DIR/nginx.conf"
VENV_PYTHON="$DIR/venv/bin/python3"
BACKEND_PY="$DIR/backend.py"
SVC_BACKEND="localwebsite-backend.service"
SVC_NGINX="localwebsite-nginx.service"

if [ ! -f "$NGINX_BIN" ]; then
    echo "Error: nginx binary not found at $NGINX_BIN"
    exit 1
fi
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: venv python not found at $VENV_PYTHON"
    exit 1
fi

if pgrep -f "nginx.*$DIR" > /dev/null 2>&1 || pgrep -f "$BACKEND_PY" > /dev/null 2>&1; then
    echo "Detected manually-started processes, stopping them first..."
    "$DIR/stop.sh"
    sleep 1
fi

mkdir -p "$USER_UNIT_DIR"

cat > "$USER_UNIT_DIR/$SVC_BACKEND" <<EOF
[Unit]
Description=Local Website Flask Backend
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$VENV_PYTHON $BACKEND_PY
Restart=on-failure

[Install]
WantedBy=default.target
EOF

cat > "$USER_UNIT_DIR/$SVC_NGINX" <<EOF
[Unit]
Description=Local Website Nginx
After=network-online.target localwebsite-backend.service
Wants=localwebsite-backend.service

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$NGINX_BIN -c $NGINX_CONF -p $DIR
Restart=on-failure

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now $SVC_BACKEND $SVC_NGINX
systemctl --user is-active $SVC_BACKEND $SVC_NGINX

if ! loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
    echo ""
    echo "Linger 未开启（否则服务仅登录后启动）。请手动执行以下命令并输入密码："
    echo "    sudo loginctl enable-linger $USER"
else
    echo "Linger 已开启，服务将在开机时自动启动。"
fi

echo "Done. Services started."
