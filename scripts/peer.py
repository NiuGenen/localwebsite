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
"""
import argparse
import json
import mimetypes
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

VERSION = "1.1"

# 默认中心站与注册密钥（可按需修改，也可通过命令行参数覆盖）
DEFAULT_CENTRAL = "http://192.168.8.65:8080"
DEFAULT_SECRET = "e9f41c66bf7fbb56ee05cd6775944749"


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

    def shutdown(signum, frame):
        sys.stderr.write("\n正在停止...\n")
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    httpd = ThreadingHTTPServer((args.bind, port), PeerHandler)
    sys.stderr.write("PeerShare %s\n" % VERSION)
    sys.stderr.write("共享目录: %s\n" % root)
    sys.stderr.write("监听地址: http://%s:%d\n" % (args.bind, port))
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
