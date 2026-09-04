import os
import re
import shutil
import time
import uuid
import json
import errno
import socket
import zipfile
import urllib.request
from urllib.parse import quote
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024 * 1024  # 上传上限 1GB，与 nginx client_max_body_size 对齐
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 本机访问判定（仅回环地址）=====
LOCAL_IPS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# ===== 文件夹打包下载临时目录（磁盘，不入库）=====
TMP_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_downloads")
MAX_ZIP_SIZE = 1 * 1024 * 1024 * 1024  # 文件夹打包下载的大小上限（1GB）

# ===== 待办事项数据文件 =====
TODO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "todo.json")
PRIORITIES = ("high", "medium", "low")
TODO_STATUSES = {"pending", "in_progress", "paused"}

# ===== 实用功能数据文件 =====
FEATURES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "features.json")

# ===== 首页自定义网页卡片数据文件 =====
LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "links.json")

# ===== 局域网共享节点（peer）注册表 =====
PEERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "peers.json")
PEER_SECRET = "e9f41c66bf7fbb56ee05cd6775944749"
PEER_TTL = 90  # 在线判定阈值（秒），需大于 peer 心跳间隔

# ===== 自定义页面数据 =====
SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
CUSTOM_PAGES_FILE = os.path.join(SITE_DIR, "custom_pages.json")
CUSTOM_DIR = os.path.join(SITE_DIR, "custom")
DOC_EXTS = {".md"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# ===== 禁止上传/创建的黑名单（相对 files/，前缀匹配）=====
BLOCKED_PATHS = ["binary-translation"]

# ===== 路径工具 =====

def safe_leaf_name(name):
    return bool(re.match(r'^[\w\-. \u4e00-\u9fff]+$', name))

def is_blocked(rel_path):
    if not rel_path or rel_path.strip() == "" or rel_path.strip() == ".":
        return False
    clean = rel_path.strip().strip("/")
    for b in BLOCKED_PATHS:
        if clean == b or clean.startswith(b + "/"):
            return True
    return False

def safe_join_soft(base, child):
    """Join paths without following symlinks; prevents .. traversal."""
    if not child or child.strip() == "":
        return base
    norm = os.path.normpath(os.path.join(base, child))
    base_str = base.rstrip("/") + "/"
    if not norm.startswith(base_str):
        return None
    return norm

# ===== 文件浏览 API =====

@app.route("/api/files")
def api_list_files():
    path = request.args.get("path", "").strip().strip("/")
    target_dir = UPLOAD_DIR
    if path:
        target_dir = safe_join_soft(UPLOAD_DIR, path)
        if not target_dir:
            return jsonify({"error": "invalid path"}), 400
    if not os.path.isdir(target_dir):
        return jsonify({"error": "目录不存在"}), 400

    try:
        names = sorted(os.listdir(target_dir))
    except OSError:
        return jsonify({"error": "无法读取目录"}), 500

    entries = []
    for name in names:
        full = os.path.join(target_dir, name)
        if name.startswith(".") or name == "index.html":
            continue
        try:
            st = os.stat(full)
            is_dir = os.path.isdir(full)
            entry_rel = path + "/" + name if path else name
            entries.append({
                "name": name,
                "type": "dir" if is_dir else "file",
                "size": st.st_size if not is_dir else 0,
                "mtime": int(st.st_mtime),
                "blocked": is_blocked(entry_rel)
            })
        except OSError:
            pass
    return jsonify({"entries": entries, "path": path, "blocked": is_blocked(path)})

# ===== 文件夹打包下载 API =====

def dir_size(target):
    """计算目录数据总量（与打包规则一致：排除点文件、index.html、符号链接）。"""
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

@app.route("/api/zip")
def api_zip_dir():
    path = (request.args.get("path") or "").strip().strip("/")
    target = safe_join_soft(UPLOAD_DIR, path) if path else UPLOAD_DIR
    if not target or not os.path.isdir(target):
        return jsonify({"error": "无效的目录"}), 400

    total = dir_size(target)
    if total > MAX_ZIP_SIZE:
        return jsonify({"error": "文件夹数据量过大（{:.2f} GB），超过 1GB 限制，禁止打包下载".format(total / (1024 ** 3))}), 413
    if request.args.get("check"):
        return jsonify({"ok": True, "size": total})

    name = os.path.basename(os.path.normpath(target)) or "files"
    os.makedirs(TMP_DOWNLOAD_DIR, exist_ok=True)
    tmp = os.path.join(TMP_DOWNLOAD_DIR, uuid.uuid4().hex + ".zip")

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
                    arc = os.path.relpath(full, UPLOAD_DIR)
                    zf.write(full, arc)
    except Exception as e:
        cleanup()
        return jsonify({"error": "打包失败: {}".format(e)}), 500

    def generate():
        try:
            with open(tmp, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            cleanup()

    headers = {"Content-Disposition": "attachment; filename*=UTF-8''{}.zip".format(quote(name))}
    return Response(generate(), mimetype="application/zip", headers=headers)

# ===== 文件上传 API =====

@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "未选择文件"}), 400

    path = request.form.get("path", "").strip().strip("/")
    target_dir = UPLOAD_DIR
    if path:
        if is_blocked(path):
            return jsonify({"error": "该目录不允许文件上传"}), 403
        target_dir = safe_join_soft(UPLOAD_DIR, path)
        if not target_dir:
            return jsonify({"error": "无效的目录路径"}), 400

    saved = []
    for f in files:
        if not f.filename:
            continue
        if os.path.basename(f.filename) != f.filename:
            return jsonify({"error": f"非法的文件名: {f.filename}"}), 400
        save_path = os.path.normpath(os.path.join(target_dir, f.filename))
        base_str = UPLOAD_DIR.rstrip("/") + "/"
        if not save_path.startswith(base_str):
            return jsonify({"error": "无效的文件路径"}), 400
        f.save(save_path)
        saved.append(f.filename)

    if not saved:
        return jsonify({"error": "未选择文件"}), 400
    return jsonify({"success": True, "names": saved})

# ===== 新建文件夹 API =====

@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求"}), 400

    parent = data.get("parent", "").strip()
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"error": "文件夹名称不能为空"}), 400
    if not safe_leaf_name(name):
        return jsonify({"error": "名称包含非法字符"}), 400

    parent_dir = UPLOAD_DIR
    if parent:
        parent_dir = safe_join_soft(UPLOAD_DIR, parent)
        if not parent_dir:
            return jsonify({"error": "无效的父目录"}), 400

    rel_parent = os.path.relpath(parent_dir, UPLOAD_DIR)
    if is_blocked(rel_parent):
        return jsonify({"error": "该目录不允许创建文件夹"}), 403

    new_dir = os.path.normpath(os.path.join(parent_dir, name))
    base_str = UPLOAD_DIR.rstrip("/") + "/"
    if not new_dir.startswith(base_str):
        return jsonify({"error": "无效的路径"}), 400

    if os.path.lexists(new_dir):
        return jsonify({"error": "已存在同名目录或文件"}), 400

    try:
        os.makedirs(new_dir)
        rel_path = os.path.relpath(new_dir, UPLOAD_DIR)
        return jsonify({"success": True, "path": rel_path})
    except Exception as e:
        return jsonify({"error": f"创建失败: {e}"}), 500

# ===== 移动文件 API =====

@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求"}), 400

    src = data.get("src", "").strip().strip("/")
    dst = data.get("dst", "").strip().strip("/")

    if not src:
        return jsonify({"error": "源文件不能为空"}), 400

    src_path = safe_join_soft(UPLOAD_DIR, src)
    if not src_path or src_path == UPLOAD_DIR:
        return jsonify({"error": "无效的源路径"}), 400
    if not os.path.isfile(src_path):
        return jsonify({"error": "只能移动文件，不能移动文件夹"}), 400

    rel_src = os.path.relpath(src_path, UPLOAD_DIR)
    if is_blocked(rel_src):
        return jsonify({"error": "该目录不允许移动文件"}), 403

    dst_dir = UPLOAD_DIR if not dst else safe_join_soft(UPLOAD_DIR, dst)
    if not dst_dir:
        return jsonify({"error": "无效的目标目录"}), 400
    if not os.path.isdir(dst_dir):
        return jsonify({"error": "目标目录不存在"}), 400

    rel_dst = os.path.relpath(dst_dir, UPLOAD_DIR)
    if is_blocked(rel_dst):
        return jsonify({"error": "该目录不允许移动文件"}), 403

    dest_path = os.path.normpath(os.path.join(dst_dir, os.path.basename(src_path)))
    if os.path.lexists(dest_path):
        return jsonify({"error": "目标位置已存在同名文件"}), 400

    try:
        shutil.move(src_path, dest_path)
        to = "" if rel_dst == "." else rel_dst
        return jsonify({"success": True, "name": os.path.basename(src_path), "to": to})
    except Exception as e:
        return jsonify({"error": f"移动失败: {e}"}), 500

# ===== 重命名 API =====

@app.route("/api/rename", methods=["POST"])
def api_rename():
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求"}), 400

    path = data.get("path", "").strip().strip("/")
    name = data.get("name", "").strip()

    if not path:
        return jsonify({"error": "路径不能为空"}), 400
    if not name:
        return jsonify({"error": "名称不能为空"}), 400
    if not safe_leaf_name(name):
        return jsonify({"error": "名称包含非法字符"}), 400

    src = safe_join_soft(UPLOAD_DIR, path)
    if not src or src == UPLOAD_DIR:
        return jsonify({"error": "无效的路径"}), 400
    if not os.path.lexists(src):
        return jsonify({"error": "目标不存在"}), 400

    rel_src = os.path.relpath(src, UPLOAD_DIR)
    if is_blocked(rel_src):
        return jsonify({"error": "该目录不允许重命名"}), 403
    if os.path.basename(src) == "index.html":
        return jsonify({"error": "该文件不允许重命名"}), 403

    new_path = os.path.normpath(os.path.join(os.path.dirname(src), name))
    base_str = UPLOAD_DIR.rstrip("/") + "/"
    if not new_path.startswith(base_str):
        return jsonify({"error": "无效的路径"}), 400
    if os.path.lexists(new_path):
        return jsonify({"error": "已存在同名目录或文件"}), 400

    try:
        os.rename(src, new_path)
        new_rel = os.path.relpath(new_path, UPLOAD_DIR)
        return jsonify({"success": True, "old": path, "new": new_rel})
    except Exception as e:
        return jsonify({"error": f"重命名失败: {e}"}), 500

# ===== 本机判定 API =====

def is_local_client():
    client = request.headers.get("X-Real-IP", "") or request.remote_addr or ""
    return client in LOCAL_IPS

@app.route("/api/local")
def api_local():
    return jsonify({"local": is_local_client()})

# ===== 待办事项 API =====

def load_todos():
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            for it in data:
                if "status" not in it:
                    it["status"] = "in_progress" if it.get("in_progress") else "pending"
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def save_todos(todos):
    tmp = TODO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TODO_FILE)

@app.route("/api/todo", methods=["GET"])
def api_todo_list():
    return jsonify(load_todos())

@app.route("/api/todo", methods=["POST"])
def api_todo_add():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "事项内容不能为空"}), 400
    if len(text) > 200:
        return jsonify({"error": "事项内容过长"}), 400
    priority = data.get("priority") if data.get("priority") in PRIORITIES else "medium"

    todos = load_todos()
    item = {
        "id": uuid.uuid4().hex,
        "text": text,
        "priority": priority,
        "done": False,
        "status": "pending",
        "created": int(time.time()),
        "updated": int(time.time()),
    }
    todos.append(item)
    save_todos(todos)
    return jsonify(item), 201

@app.route("/api/todo/<todo_id>", methods=["PUT"])
def api_todo_update(todo_id):
    data = request.get_json() or {}
    todos = load_todos()
    for it in todos:
        if it["id"] == todo_id:
            if "text" in data:
                t = (data["text"] or "").strip()
                if not t:
                    return jsonify({"error": "事项内容不能为空"}), 400
                if len(t) > 200:
                    return jsonify({"error": "事项内容过长"}), 400
                it["text"] = t
            if "priority" in data and data["priority"] in PRIORITIES:
                it["priority"] = data["priority"]
            if "done" in data:
                it["done"] = bool(data["done"])
                if it["done"]:
                    it["status"] = "pending"
            if "status" in data and data["status"] in TODO_STATUSES:
                it["status"] = data["status"]
            it["updated"] = int(time.time())
            save_todos(todos)
            return jsonify(it)
    return jsonify({"error": "待办事项不存在"}), 404

@app.route("/api/todo/<todo_id>", methods=["DELETE"])
def api_todo_delete(todo_id):
    todos = load_todos()
    new_todos = [it for it in todos if it["id"] != todo_id]
    if len(new_todos) == len(todos):
        return jsonify({"error": "待办事项不存在"}), 404
    save_todos(new_todos)
    return jsonify({"success": True})

# ===== 实用功能 API =====

def load_features():
    try:
        with open(FEATURES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def save_features(features):
    tmp = FEATURES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(features, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FEATURES_FILE)

@app.route("/api/features", methods=["GET"])
def api_features_list():
    features = load_features()
    features.sort(key=lambda f: f.get("created", 0), reverse=True)
    q = (request.args.get("q") or "").strip().lower()
    if q:
        features = [
            f for f in features
            if q in (f.get("title") or "").lower() or q in (f.get("content") or "").lower()
        ]
    return jsonify(features)

@app.route("/api/features", methods=["POST"])
def api_features_create():
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title:
        return jsonify({"error": "标题不能为空"}), 400
    if len(title) > 100:
        return jsonify({"error": "标题过长"}), 400
    if not content:
        return jsonify({"error": "内容不能为空"}), 400
    if len(content) > 5000:
        return jsonify({"error": "内容过长"}), 400

    item = {
        "id": uuid.uuid4().hex,
        "title": title,
        "content": content,
        "created": int(time.time()),
    }
    features = load_features()
    features.append(item)
    save_features(features)
    return jsonify(item), 201

@app.route("/api/features/<feature_id>", methods=["PUT"])
def api_features_update(feature_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    features = load_features()
    for f in features:
        if f["id"] == feature_id:
            if "title" in data:
                title = (data["title"] or "").strip()
                if not title:
                    return jsonify({"error": "标题不能为空"}), 400
                if len(title) > 100:
                    return jsonify({"error": "标题过长"}), 400
                f["title"] = title
            if "content" in data:
                content = (data.get("content") or "").strip()
                if not content:
                    return jsonify({"error": "内容不能为空"}), 400
                if len(content) > 5000:
                    return jsonify({"error": "内容过长"}), 400
                f["content"] = content
            save_features(features)
            return jsonify(f)
    return jsonify({"error": "功能不存在"}), 404

@app.route("/api/features/<feature_id>", methods=["DELETE"])
def api_features_delete(feature_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    features = load_features()
    new_features = [f for f in features if f["id"] != feature_id]
    if len(new_features) == len(features):
        return jsonify({"error": "功能不存在"}), 404
    save_features(new_features)
    return jsonify({"success": True})

# ===== 首页自定义网页卡片 API =====

def load_links():
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def save_links(links):
    tmp = LINKS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LINKS_FILE)

def valid_url(url):
    return bool(re.match(r'^(https?://|/)', url))

@app.route("/api/links", methods=["GET"])
def api_links_list():
    links = load_links()
    links.sort(key=lambda l: l.get("created", 0), reverse=True)
    return jsonify(links)

@app.route("/api/links", methods=["POST"])
def api_links_create():
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    url = (data.get("url") or "").strip()
    if not title:
        return jsonify({"error": "标题不能为空"}), 400
    if len(title) > 100:
        return jsonify({"error": "标题过长"}), 400
    if len(description) > 2000:
        return jsonify({"error": "简介过长"}), 400
    if not url:
        return jsonify({"error": "目标网页链接不能为空"}), 400
    if len(url) > 500:
        return jsonify({"error": "链接过长"}), 400
    if not valid_url(url):
        return jsonify({"error": "链接需以 http://、https:// 或 / 开头"}), 400

    item = {
        "id": uuid.uuid4().hex,
        "title": title,
        "description": description,
        "url": url,
        "created": int(time.time()),
    }
    links = load_links()
    links.append(item)
    save_links(links)
    return jsonify(item), 201

@app.route("/api/links/<link_id>", methods=["PUT"])
def api_links_update(link_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    links = load_links()
    for l in links:
        if l["id"] == link_id:
            if "title" in data:
                title = (data["title"] or "").strip()
                if not title:
                    return jsonify({"error": "标题不能为空"}), 400
                if len(title) > 100:
                    return jsonify({"error": "标题过长"}), 400
                l["title"] = title
            if "description" in data:
                description = (data.get("description") or "").strip()
                if len(description) > 2000:
                    return jsonify({"error": "简介过长"}), 400
                l["description"] = description
            if "url" in data:
                url = (data.get("url") or "").strip()
                if not url:
                    return jsonify({"error": "目标网页链接不能为空"}), 400
                if len(url) > 500:
                    return jsonify({"error": "链接过长"}), 400
                if not valid_url(url):
                    return jsonify({"error": "链接需以 http://、https:// 或 / 开头"}), 400
                l["url"] = url
            save_links(links)
            return jsonify(l)
    return jsonify({"error": "卡片不存在"}), 404

@app.route("/api/links/<link_id>", methods=["DELETE"])
def api_links_delete(link_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    links = load_links()
    new_links = [l for l in links if l["id"] != link_id]
    if len(new_links) == len(links):
        return jsonify({"error": "卡片不存在"}), 404
    save_links(new_links)
    return jsonify({"success": True})

# ===== 局域网共享节点（peer）API =====

def load_peers():
    try:
        with open(PEERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def save_peers(peers):
    tmp = PEERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(peers, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PEERS_FILE)

def find_peer(peer_id):
    for p in load_peers():
        if p["id"] == peer_id:
            return p
    return None

def peer_online(peer):
    return (int(time.time()) - (peer.get("last_seen") or 0)) <= PEER_TTL

@app.route("/api/peers/register", methods=["POST"])
def api_peers_register():
    data = request.get_json() or {}
    secret = (data.get("secret") or "").strip()
    if not PEER_SECRET or secret != PEER_SECRET:
        return jsonify({"error": "注册密钥不正确"}), 403
    name = (data.get("name") or "").strip()
    host = (data.get("host") or "").strip()
    port = data.get("port")
    dir_label = (data.get("dir_label") or "").strip()
    if not name:
        return jsonify({"error": "节点名称不能为空"}), 400
    if len(name) > 50:
        return jsonify({"error": "节点名称过长"}), 400
    if not host:
        return jsonify({"error": "IP 地址不能为空"}), 400
    if len(host) > 100:
        return jsonify({"error": "IP 地址过长"}), 400
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return jsonify({"error": "端口无效"}), 400
    if len(dir_label) > 200:
        return jsonify({"error": "共享目录描述过长"}), 400

    now = int(time.time())
    peers = load_peers()
    for p in peers:
        if p.get("host") == host and p.get("port") == port:
            p["name"] = name
            p["dir_label"] = dir_label
            p["last_seen"] = now
            save_peers(peers)
            return jsonify(p)
    peer = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "host": host,
        "port": port,
        "dir_label": dir_label,
        "first_seen": now,
        "last_seen": now,
    }
    peers.append(peer)
    save_peers(peers)
    return jsonify(peer), 201

@app.route("/api/peers", methods=["GET"])
def api_peers_list():
    peers = load_peers()
    online = [p for p in peers if peer_online(p)]
    if len(online) != len(peers):
        save_peers(online)
    result = []
    for p in online:
        result.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "host": p.get("host"),
            "port": p.get("port"),
            "dir_label": p.get("dir_label"),
            "first_seen": p.get("first_seen"),
            "last_seen": p.get("last_seen"),
            "online": True,
        })
    result.sort(key=lambda p: p["name"] or "")
    return jsonify(result)

@app.route("/api/peers/unregister", methods=["POST"])
def api_peers_unregister():
    data = request.get_json() or {}
    secret = (data.get("secret") or "").strip()
    if not PEER_SECRET or secret != PEER_SECRET:
        return jsonify({"error": "注册密钥不正确"}), 403
    host = (data.get("host") or "").strip()
    port = data.get("port")
    if not host or not isinstance(port, int):
        return jsonify({"error": "参数无效"}), 400
    peers = load_peers()
    new_peers = [p for p in peers if not (p.get("host") == host and p.get("port") == port)]
    if len(new_peers) == len(peers):
        return jsonify({"error": "节点不存在"}), 404
    save_peers(new_peers)
    return jsonify({"success": True})

@app.route("/api/peers/<peer_id>", methods=["DELETE"])
def api_peers_delete(peer_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    peers = load_peers()
    new_peers = [p for p in peers if p["id"] != peer_id]
    if len(new_peers) == len(peers):
        return jsonify({"error": "节点不存在"}), 404
    save_peers(new_peers)
    return jsonify({"success": True})

def peer_conn_error(peer, exc):
    """把连接节点失败映射为可操作的中文提示。"""
    reason = getattr(exc, "reason", exc)
    err = getattr(reason, "errno", None)
    addr = "{}:{}".format(peer.get("host"), peer.get("port"))
    if err in (errno.EHOSTUNREACH, errno.EHOSTDOWN):
        return ("无法访问节点 {}：该机器可能开启了防火墙（未放行端口 {}）或已离线，"
                "请在该机器上放行端口后重试。").format(addr, peer.get("port"))
    if err in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.ENETDOWN):
        return "无法连接节点 {}：peer.py 可能未运行或端口被占用。".format(addr)
    if isinstance(reason, socket.timeout) or err in (errno.ETIMEDOUT, errno.EAGAIN):
        return "连接节点 {} 超时，请检查该机器网络。".format(addr)
    return "无法连接节点 {}：{}".format(addr, reason)

@app.route("/api/peers/<peer_id>/tree", methods=["GET"])
def api_peers_tree(peer_id):
    peer = find_peer(peer_id)
    if not peer:
        return jsonify({"error": "节点不存在"}), 404
    if not peer_online(peer):
        return jsonify({"error": "节点离线"}), 503
    path = (request.args.get("path") or "").strip().strip("/")
    url = "http://{}:{}/api/peertree".format(peer["host"], peer["port"])
    if path:
        url += "?path=" + quote(path, safe="/")
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return jsonify(data)
    except urllib.error.URLError as e:
        return jsonify({"error": peer_conn_error(peer, e)}), 502
    except socket.timeout:
        return jsonify({"error": peer_conn_error(peer, "timeout")}), 502
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "节点返回数据无效"}), 502

@app.route("/api/peers/<peer_id>/file", methods=["GET"])
def api_peers_file(peer_id):
    peer = find_peer(peer_id)
    if not peer:
        return jsonify({"error": "节点不存在"}), 404
    if not peer_online(peer):
        return jsonify({"error": "节点离线"}), 503
    path = (request.args.get("path") or "").strip().strip("/")
    if not path or not path.lower().endswith(".md"):
        return jsonify({"error": "仅支持阅读 .md 文件"}), 400
    url = "http://{}:{}/files/{}".format(peer["host"], peer["port"], quote(path, safe="/"))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read(5 * 1024 * 1024 + 1)
            if len(data) > 5 * 1024 * 1024:
                return jsonify({"error": "文件过大（>5MB），暂不支持在线阅读"}), 413
            return app.response_class(data.decode("utf-8", errors="replace"),
                                      mimetype="text/plain; charset=utf-8")
    except urllib.error.URLError as e:
        return jsonify({"error": peer_conn_error(peer, e)}), 502
    except socket.timeout:
        return jsonify({"error": "读取节点文件超时"}), 502

# ===== 自定义页面 API =====

def load_pages():
    try:
        with open(CUSTOM_PAGES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def save_pages(pages):
    tmp = CUSTOM_PAGES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CUSTOM_PAGES_FILE)

def find_page(page_id):
    for p in load_pages():
        if p["id"] == page_id:
            return p
    return None

def page_dir(page_id):
    return os.path.join(CUSTOM_DIR, page_id)

def page_list_dir(base, rel):
    """List entries under a page dir; returns (entries, rel_path) or (None, None) on bad path."""
    if not rel or rel.strip() == "":
        rel = ""
    target = safe_join_soft(base, rel) if rel else base
    if not target:
        return None, None
    if not os.path.isdir(target):
        return None, None
    entries = []
    try:
        names = sorted(os.listdir(target))
    except OSError:
        return None, None
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
                "mtime": int(st.st_mtime)
            })
        except OSError:
            pass
    return entries, rel

def require_local():
    if not is_local_client():
        return False
    return True

@app.route("/api/pages", methods=["GET"])
def api_pages_list():
    pages = load_pages()
    pages.sort(key=lambda p: p.get("created", 0), reverse=True)
    return jsonify(pages)

@app.route("/api/pages", methods=["POST"])
def api_pages_create():
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not title:
        return jsonify({"error": "标题不能为空"}), 400
    if len(title) > 100:
        return jsonify({"error": "标题过长"}), 400
    if len(description) > 2000:
        return jsonify({"error": "简介过长"}), 400

    page_id = uuid.uuid4().hex[:12]
    os.makedirs(page_dir(page_id), exist_ok=True)
    page = {
        "id": page_id,
        "title": title,
        "description": description,
        "pinned": False,
        "created": int(time.time()),
    }
    pages = load_pages()
    pages.append(page)
    save_pages(pages)
    return jsonify(page), 201

@app.route("/api/pages/<page_id>", methods=["PUT"])
def api_pages_update(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    page = find_page(page_id)
    if not page:
        return jsonify({"error": "页面不存在"}), 404
    data = request.get_json() or {}
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            return jsonify({"error": "标题不能为空"}), 400
        if len(title) > 100:
            return jsonify({"error": "标题过长"}), 400
        page["title"] = title
    if "description" in data:
        description = (data.get("description") or "").strip()
        if len(description) > 2000:
            return jsonify({"error": "简介过长"}), 400
        page["description"] = description
    if "pinned" in data:
        page["pinned"] = bool(data["pinned"])
    pages = load_pages()
    for i, p in enumerate(pages):
        if p["id"] == page_id:
            pages[i] = page
            break
    save_pages(pages)
    return jsonify(page)

@app.route("/api/pages/<page_id>", methods=["DELETE"])
def api_pages_delete(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    page = find_page(page_id)
    if not page:
        return jsonify({"error": "页面不存在"}), 404
    pages = load_pages()
    new_pages = [p for p in pages if p["id"] != page_id]
    save_pages(new_pages)
    d = page_dir(page_id)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    return jsonify({"success": True})

@app.route("/api/pages/<page_id>/tree", methods=["GET"])
def api_pages_tree(page_id):
    if not find_page(page_id):
        return jsonify({"error": "页面不存在"}), 404
    rel = request.args.get("path", "").strip().strip("/")
    entries, rel = page_list_dir(page_dir(page_id), rel)
    if entries is None:
        return jsonify({"error": "无效的路径"}), 400
    return jsonify({"entries": entries, "path": rel})

@app.route("/api/pages/<page_id>/upload", methods=["POST"])
def api_pages_upload(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not find_page(page_id):
        return jsonify({"error": "页面不存在"}), 404
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "未选择文件"}), 400

    rel = request.form.get("path", "").strip().strip("/")
    d = page_dir(page_id)
    target = safe_join_soft(d, rel) if rel else d
    if not target:
        return jsonify({"error": "无效的目录路径"}), 400
    if not os.path.isdir(target):
        return jsonify({"error": "目标目录不存在"}), 400

    allowed = DOC_EXTS | IMAGE_EXTS
    saved = []
    for f in files:
        if not f.filename:
            continue
        if os.path.basename(f.filename) != f.filename:
            return jsonify({"error": f"非法的文件名: {f.filename}"}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in allowed:
            return jsonify({"error": f"不支持的文件类型: {f.filename}"}), 400
        f.save(os.path.join(target, f.filename))
        saved.append(f.filename)
    if not saved:
        return jsonify({"error": "未选择文件"}), 400
    return jsonify({"success": True, "names": saved})

@app.route("/api/pages/<page_id>/mkdir", methods=["POST"])
def api_pages_mkdir(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not find_page(page_id):
        return jsonify({"error": "页面不存在"}), 404
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip().strip("/")
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "文件夹名称不能为空"}), 400
    if not safe_leaf_name(name):
        return jsonify({"error": "名称包含非法字符"}), 400

    d = page_dir(page_id)
    parent = safe_join_soft(d, rel) if rel else d
    if not parent:
        return jsonify({"error": "无效的目录路径"}), 400
    new_dir = os.path.normpath(os.path.join(parent, name))
    base_str = d.rstrip("/") + "/"
    if not new_dir.startswith(base_str):
        return jsonify({"error": "无效的路径"}), 400
    if os.path.lexists(new_dir):
        return jsonify({"error": "已存在同名目录或文件"}), 400
    try:
        os.makedirs(new_dir)
        return jsonify({"success": True, "path": os.path.relpath(new_dir, d) if rel else name})
    except Exception as e:
        return jsonify({"error": f"创建失败: {e}"}), 500

@app.route("/api/pages/<page_id>/delete", methods=["POST"])
def api_pages_delete_entry(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not find_page(page_id):
        return jsonify({"error": "页面不存在"}), 404
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip().strip("/")
    if not rel:
        return jsonify({"error": "路径不能为空"}), 400

    d = page_dir(page_id)
    target = safe_join_soft(d, rel)
    if not target or target == d:
        return jsonify({"error": "无效的路径"}), 400
    if not os.path.lexists(target):
        return jsonify({"error": "目标不存在"}), 404
    try:
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"删除失败: {e}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
