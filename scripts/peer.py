#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""局域网共享节点（peer）—— 仅使用 Python 标准库，零依赖。

以只读方式通过 HTTP 共享一个本地目录，并定期向中心站注册心跳，
使目录出现在中心站「局域网共享」门户中。

用法（方式一）: 直接执行，共享脚本所在目录，使用默认机器名
    python3 peer.py
用法（方式二）: 指定共享目录，使用默认机器名
    python3 peer.py --dir /path/to/share
用法（方式三）: 指定共享目录与机器名
    python3 peer.py --dir /path/to/share --name "我的机器"

参数（均可省略，使用默认值）:
    --dir      要共享的目录，默认脚本所在目录
    --port     监听端口，默认自动探测可用端口（从 9000 起）
    --name     机器显示名称，默认本机主机名
    --central  中心站地址，默认 http://192.168.8.65:8080
    --secret   与中心站一致的注册密钥（默认已内置）
    --host     手动指定上报的 IP（默认自动探测）
    --interval 心跳间隔秒数，默认 30
    --bind     绑定地址，默认 0.0.0.0

防火墙:
    若本机启用了 firewalld/ufw，默认会拦截未放行的端口。以 root 运行时本脚本
    会自动放行所选端口；以普通用户运行时请按启动提示的命令手动放行。
"""
import argparse
import json
import mimetypes
import os
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

VERSION = "1.5"

# 默认中心站与注册密钥（可按需修改，也可通过命令行参数覆盖）
DEFAULT_CENTRAL = "http://192.168.8.65:8080"
DEFAULT_SECRET = "e9f41c66bf7fbb56ee05cd6775944749"

# 文件夹打包下载大小上限（1GB）
MAX_ZIP_SIZE = 1 * 1024 * 1024 * 1024


def find_free_port(start=9000, attempts=100):
    """探测从 start 起第一个可用的端口。"""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return 0


# ===== 防火墙处理（firewalld / ufw）=====

def is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _which(name):
    try:
        return shutil.which(name)
    except Exception:
        return None


def _run(cmd):
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except Exception:
        return None


def detect_firewall():
    """检测本机是否启用了常见防火墙。返回 {'type': 'firewalld'|'ufw'} 或 None。"""
    if _which("firewall-cmd"):
        r = _run(["systemctl", "is-active", "firewalld"])
        if r and r.returncode == 0 and (r.stdout or b"").strip() == b"active":
            return {"type": "firewalld"}
    if _which("ufw"):
        r = _run(["ufw", "status"])
        if r and b"Status: active" in (r.stdout or b""):
            return {"type": "ufw"}
    return None


def firewall_change(fw_type, port, action):
    """action 为 'allow' 或 'disallow'，修改防火墙端口规则。返回 (成功?, 说明)。"""
    if fw_type == "firewalld":
        flag = "add" if action == "allow" else "remove"
        r = _run(["firewall-cmd", "--permanent", "%s-port=%d/tcp" % (flag, port)])
        if not r or r.returncode != 0:
            return False, "firewall-cmd %s-port=%d/tcp 执行失败" % (flag, port)
        _run(["firewall-cmd", "--reload"])
        return True, "firewalld"
    if fw_type == "ufw":
        cmd = ["ufw"] + (["delete"] if action == "disallow" else []) + ["allow", "%d/tcp" % port]
        r = _run(cmd)
        if not r or r.returncode != 0:
            return False, " ".join(cmd) + " 执行失败"
        return True, "ufw"
    return False, "未知防火墙"


def firewall_hint(fw_type, port):
    """非 root 运行时提示给用户的放行命令。"""
    if fw_type == "firewalld":
        return "sudo firewall-cmd --permanent --add-port=%d/tcp && sudo firewall-cmd --reload" % port
    if fw_type == "ufw":
        return "sudo ufw allow %d/tcp" % port
    return ""


def detect_lan_ip(central):
    """通过 UDP connect 探测访问中心站所用的源 IP（多网卡时选对网卡）。"""
    try:
        parsed = urlparse(central)
        target = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target, port))
            return s.getsockname()[0]
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def safe_join(base, child):
    """安全拼接路径，防止 .. 穿越。"""
    if not child:
        return base
    full = os.path.normpath(os.path.join(base, child))
    if not full.startswith(os.path.normpath(base) + os.sep):
        return None
    return full


def dir_size(target):
    """统计目录数据总量（与打包/列表规则一致：排除点文件、index.html、符号链接）。"""
    total = 0
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith(".") or f == "index.html":
                continue
            full = os.path.join(root, f)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    return total


def list_dir(base, rel):
    """列出目录，返回与中心站 /api/files 同构的结构。"""
    target = safe_join(base, rel) if rel else base
    if not target or not os.path.isdir(target):
        return None
    entries = []
    try:
        names = sorted(os.listdir(target))
    except OSError:
        return None
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        try:
            st = os.stat(full)
            is_dir = os.path.isdir(full)
            entries.append({
                "name": name,
                "type": "dir" if is_dir else "file",
                "size": st.st_size if not is_dir else 0,
                "mtime": int(st.st_mtime),
                "blocked": False,
            })
        except OSError:
            pass
    return {"entries": entries, "path": rel or "", "blocked": False}


class PeerHandler(BaseHTTPRequestHandler):
    server_version = "PeerShare/" + VERSION
    root = None

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def send_bytes(self, data, code=200, ctype="application/octet-stream", headers=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(code)
        self.send_cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, code=code, ctype="application/json; charset=utf-8")

    def send_error_text(self, code, msg):
        self.send_bytes(json.dumps({"error": msg}, ensure_ascii=False),
                        code=code, ctype="application/json; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.end_headers()

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve(head_only=True)

    def _serve(self, head_only=False):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parsed.query

        if path == "/api/peertree":
            rel = ""
            if query:
                for pair in query.split("&"):
                    if pair.startswith("path="):
                        rel = unquote(pair[5:]).strip().strip("/")
                        break
            result = list_dir(self.root, rel)
            if result is None:
                return self.send_error_text(400, "无效的目录路径")
            return self.send_json(result)

        if path.startswith("/api/zip"):
            rel = ""
            check_only = False
            if query:
                for pair in query.split("&"):
                    if pair.startswith("path="):
                        rel = unquote(pair[5:]).strip().strip("/")
                    elif pair.startswith("check=1"):
                        check_only = True
            return self._serve_zip(rel, check_only)

        if path.startswith("/files/"):
            rel = path[len("/files/"):]
            return self._serve_file(unquote(rel), head_only)

        if path == "/" or path == "":
            return self.send_json({"service": "PeerShare", "version": VERSION,
                                   "dir": self.root, "hint": "通过中心站门户浏览"})

        self.send_error_text(404, "Not Found")

    def _serve_file(self, rel, head_only=False):
        full = safe_join(self.root, rel)
        if not full:
            return self.send_error_text(400, "非法路径")
        if not os.path.isfile(full):
            return self.send_error_text(404, "文件不存在")

        try:
            st = os.stat(full)
        except OSError:
            return self.send_error_text(500, "无法读取文件")

        size = st.st_size
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"

        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        extra = {}
        if range_header and range_header.startswith("bytes="):
            spec = range_header[6:].split(",", 1)[0].strip()
            try:
                if spec.startswith("-"):
                    suffix = int(spec[1:])
                    start = max(size - suffix, 0)
                elif "-" in spec:
                    a, b = spec.split("-", 1)
                    start = int(a) if a else 0
                    end = int(b) if b else size - 1
                else:
                    start = int(spec)
                if start >= size:
                    self.send_response(416)
                    self.send_cors()
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers()
                    return
                if end >= size:
                    end = size - 1
                if end < start:
                    end = size - 1
                code = 206
                extra["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
                extra["Accept-Ranges"] = "bytes"
            except ValueError:
                pass
        else:
            extra["Accept-Ranges"] = "bytes"

        length = end - start + 1
        self.send_response(code)
        self.send_cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(os.path.basename(full)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()

        if head_only:
            return
        try:
            with open(full, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            pass

    def _serve_zip(self, rel, check_only=False):
        target = safe_join(self.root, rel)
        if not target or not os.path.isdir(target):
            return self.send_error_text(400, "无效的目录")
        total = dir_size(target)
        if total > MAX_ZIP_SIZE:
            return self.send_error_text(
                413, "文件夹数据量过大（{:.2f} GB），超过 1GB 限制，禁止打包下载".format(total / (1024 ** 3)))
        if check_only:
            return self.send_json({"ok": True, "size": total})

        name = os.path.basename(os.path.normpath(target)) or "files"
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target) or None, suffix=".zip")
        except OSError:
            fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)

        def cleanup():
            try:
                os.remove(tmp)
            except OSError:
                pass

        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
                for root, dirs, files in os.walk(target):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for f in files:
                        if f.startswith(".") or f == "index.html":
                            continue
                        full = os.path.join(root, f)
                        if os.path.islink(full):
                            continue
                        arc = os.path.relpath(full, self.root)
                        zf.write(full, arc)
        except Exception as e:
            cleanup()
            return self.send_error_text(500, "打包失败: %s" % e)

        try:
            st = os.stat(tmp)
            self.send_response(200)
            self.send_cors()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s.zip" % quote(name))
            self.end_headers()
            with open(tmp, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            pass
        finally:
            cleanup()


def unregister(central, secret, host, port):
    """主动关闭时通知中心站移除本节点，实现快速下线。"""
    url = central.rstrip("/") + "/api/peers/unregister"
    payload = {"secret": secret, "host": host, "port": port}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.getcode() < 300:
                sys.stderr.write("[unregister] ok\n")
            else:
                sys.stderr.write("[unregister] failed HTTP %s\n" % resp.getcode())
    except Exception as e:
        sys.stderr.write("[unregister] error: %s\n" % e)


def heartbeat(central, secret, name, host, port, dir_label, interval, stop_event):
    url = central.rstrip("/") + "/api/peers/register"
    payload = {
        "secret": secret,
        "name": name,
        "host": host,
        "port": port,
        "dir_label": dir_label,
    }
    while not stop_event.is_set():
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                code = resp.getcode()
            if 200 <= code < 300:
                sys.stderr.write("[heartbeat] ok\n")
            else:
                sys.stderr.write("[heartbeat] failed HTTP %s: %s\n" % (code, body))
        except Exception as e:
            sys.stderr.write("[heartbeat] error: %s\n" % e)
        stop_event.wait(interval)


def main():
    ap = argparse.ArgumentParser(description="局域网共享节点（PeerShare）")
    ap.add_argument("--dir", default="", help="要共享的目录，默认脚本所在目录")
    ap.add_argument("--port", type=int, default=None, help="监听端口，默认自动探测可用端口")
    ap.add_argument("--name", default=socket.gethostname(), help="机器显示名称，默认本机主机名")
    ap.add_argument("--central", default=DEFAULT_CENTRAL, help="中心站地址，默认 %s" % DEFAULT_CENTRAL)
    ap.add_argument("--secret", default=DEFAULT_SECRET, help="与中心站一致的注册密钥（默认已内置）")
    ap.add_argument("--host", default="", help="手动指定上报的 IP（默认自动探测）")
    ap.add_argument("--interval", type=int, default=30, help="心跳间隔秒数，默认 30")
    ap.add_argument("--bind", default="0.0.0.0", help="绑定地址，默认 0.0.0.0")
    args = ap.parse_args()

    root = os.path.abspath(args.dir or os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(root):
        sys.stderr.write("错误: 共享目录不存在: %s\n" % root)
        sys.exit(1)

    port = args.port or find_free_port()
    host = args.host or detect_lan_ip(args.central)
    PeerHandler.root = root

    stop_event = threading.Event()
    fw_state = {"port_allowed": False, "fw_type": None}

    def shutdown(signum, frame):
        sys.stderr.write("\n正在停止...\n")
        stop_event.set()
        if fw_state["port_allowed"]:
            ok, detail = firewall_change(fw_state["fw_type"], port, "disallow")
            sys.stderr.write("[firewall] %s（端口 %d）\n" % ("已移除自动放行规则" if ok else "移除失败: " + detail, port))
        unregister(args.central, args.secret, host, port)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 防火墙处理：回环绑定无需放行
    if args.bind not in ("127.0.0.1", "::1", "localhost"):
        fw = detect_firewall()
        if fw:
            fw_type = fw["type"]
            fw_state["fw_type"] = fw_type
            if is_root():
                ok, detail = firewall_change(fw_type, port, "allow")
                if ok:
                    fw_state["port_allowed"] = True
                    sys.stderr.write("已自动放行端口 %d（%s）\n" % (port, detail))
                else:
                    sys.stderr.write("自动放行端口 %d 失败，请手动执行:\n  %s\n" % (port, detail))
            else:
                sys.stderr.write(
                    "警告: 检测到本机启用 %s 防火墙，端口 %d 可能被拦截，局域网其他机器将无法访问。\n"
                    "      放行方法（需要 root）: %s\n"
                    % (fw_type, port, firewall_hint(fw_type, port)))

    httpd = ThreadingHTTPServer((args.bind, port), PeerHandler)
    sys.stderr.write("PeerShare %s\n" % VERSION)
    sys.stderr.write("共享目录: %s\n" % root)
    sys.stderr.write("绑定地址: %s:%d（0.0.0.0 表示监听所有网卡，局域网可访问）\n" % (args.bind, port))
    sys.stderr.write("访问地址: http://%s:%d\n" % (host, port))
    sys.stderr.write("上报信息: 名称=%s IP=%s 端口=%d\n" % (args.name, host, port))
    sys.stderr.write("中心站: %s\n" % args.central)
    sys.stderr.write("心跳间隔: %ds\n" % args.interval)

    hb = threading.Thread(target=heartbeat, daemon=True,
                          args=(args.central, args.secret, args.name, host, port,
                                root, args.interval, stop_event))
    hb.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
