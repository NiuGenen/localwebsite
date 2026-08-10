#!/bin/bash
kill "$(cat /tmp/nginx_demo.pid 2>/dev/null)" 2>/dev/null && echo "nginx stopped" || echo "nginx not running"
kill "$(cat /tmp/flask_backend.pid 2>/dev/null)" 2>/dev/null && echo "flask stopped" || echo "flask not running"
