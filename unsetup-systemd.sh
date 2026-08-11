#!/bin/bash
USER_UNIT_DIR="$HOME/.config/systemd/user"
SVC_BACKEND="localwebsite-backend.service"
SVC_NGINX="localwebsite-nginx.service"

systemctl --user stop $SVC_BACKEND $SVC_NGINX 2>/dev/null
systemctl --user disable $SVC_BACKEND $SVC_NGINX 2>/dev/null
rm -f "$USER_UNIT_DIR/$SVC_BACKEND" "$USER_UNIT_DIR/$SVC_NGINX"
systemctl --user daemon-reload

echo "Done. 已停止并移除 systemd 服务单元文件。"

if loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
    echo "提示: Linger 仍为开启状态，如需一并关闭，请手动执行:"
    echo "    sudo loginctl disable-linger $USER"
fi
echo "重新安装: ./setup-systemd.sh"
