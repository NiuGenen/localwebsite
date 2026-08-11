#!/bin/bash
DIR="$(dirname "$0")"
NGINX_BIN="$HOME/nginx_install/usr/sbin/nginx"
CONF="$DIR/nginx.conf"
VENV_PYTHON="$DIR/venv/bin/python3"

if [ ! -f "$NGINX_BIN" ]; then
    echo "Error: nginx binary not found at $NGINX_BIN"
    exit 1
fi

echo "Starting Flask backend on port 5000..."
nohup "$VENV_PYTHON" "$DIR/backend.py" > /tmp/flask_backend.log 2>&1 &
echo $! > /tmp/flask_backend.pid

echo "Starting nginx on port 8080..."
nohup "$NGINX_BIN" -c "$CONF" -p "$DIR" > /tmp/nginx_startup.log 2>&1 &
echo $! > /tmp/nginx_demo.pid

echo "Done. Services started."
