import os
import re
import shutil
import time
import uuid
import json
import errno
import socket
import zipfile
import hashlib
import subprocess
import urllib.request
from urllib.parse import quote
from functools import wraps
import sqlite3
import storage
from flask import Flask, request, jsonify, Response, g

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024 * 1024  # 上传上限 1GB，与 nginx client_max_body_size 对齐
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 本机访问判定（仅回环地址）=====
LOCAL_IPS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# ===== 文件夹打包下载临时目录（磁盘，不入库）=====
TMP_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_downloads")
MAX_ZIP_SIZE = 1 * 1024 * 1024 * 1024  # 文件夹打包下载的大小上限（1GB）

# ===== 文档（doc/docx）在线阅读转换 =====
TMP_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_docs")
DOC_READ_EXTS = {".doc", ".docx"}
MAX_DOC_BYTES = 50 * 1024 * 1024  # 单个文档转换/提取上限（50MB）
MAX_WEEKLY_IMPORT_BYTES = 5 * 1024 * 1024

# ===== 待办事项取值 =====
PRIORITIES = ("high", "medium", "low")
TODO_STATUSES = {"pending", "in_progress", "paused"}

# ===== 局域网共享节点（peer）注册表 =====
PEER_SECRET = "e9f41c66bf7fbb56ee05cd6775944749"
PEER_TTL = 90  # 在线判定阈值（秒），需大于 peer 心跳间隔

# ===== 自定义页面数据 =====
SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
CUSTOM_DIR = os.path.join(SITE_DIR, "custom")
DOC_EXTS = {".md"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# ===== 禁止上传/创建的黑名单（相对 files/，前缀匹配）=====
BLOCKED_PATHS = ["binary-translation"]

# ===== SQLite：每个请求独立连接，写操作从读取前开始事务 =====
app.config["DATABASE"] = os.environ.get("LOCALWEBSITE_DB", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "app.db"))


def get_db():
    if "db" not in g:
        db = storage.connect(app.config["DATABASE"])
        try:
            storage.check_schema(db)
        except Exception:
            db.close()
            raise
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def db_write(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            response = app.make_response(func(*args, **kwargs))
            db.execute("COMMIT" if response.status_code < 400 else "ROLLBACK")
            return response
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
    return wrapped


@app.errorhandler(sqlite3.OperationalError)
def database_error(error):
    code = getattr(error, "sqlite_errorcode", 0) or 0
    if (code & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return jsonify({"error": "数据库繁忙，请稍后重试"}), 503, {"Retry-After": "1"}
    app.logger.exception("SQLite operation failed")
    return jsonify({"error": "数据库操作失败"}), 500


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
    return storage.all_records(get_db(), "todos")


@app.route("/api/todo", methods=["GET"])
def api_todo_list():
    return jsonify(load_todos())

@app.route("/api/todo", methods=["POST"])
@db_write
def api_todo_add():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "事项内容不能为空"}), 400
    if len(text) > 200:
        return jsonify({"error": "事项内容过长"}), 400
    priority = data.get("priority") if data.get("priority") in PRIORITIES else "medium"

    item = {
        "id": uuid.uuid4().hex,
        "text": text,
        "priority": priority,
        "done": False,
        "status": "pending",
        "created": int(time.time()),
        "updated": int(time.time()),
    }
    storage.insert(get_db(), "todos", item)
    return jsonify(item), 201

@app.route("/api/todo/<todo_id>", methods=["PUT"])
@db_write
def api_todo_update(todo_id):
    data = request.get_json() or {}
    it = storage.get(get_db(), "todos", todo_id)
    if it is None:
        return jsonify({"error": "待办事项不存在"}), 404
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
    storage.update(get_db(), "todos", it)
    return jsonify(it)

@app.route("/api/todo/<todo_id>", methods=["DELETE"])
@db_write
def api_todo_delete(todo_id):
    if not storage.delete(get_db(), "todos", todo_id):
        return jsonify({"error": "待办事项不存在"}), 404
    return jsonify({"success": True})


# ===== 实用功能 API =====

def load_features():
    return storage.all_records(get_db(), "features")


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
@db_write
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
    storage.insert(get_db(), "features", item)
    return jsonify(item), 201

@app.route("/api/features/<feature_id>", methods=["PUT"])
@db_write
def api_features_update(feature_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    f = storage.get(get_db(), "features", feature_id)
    if f is None:
        return jsonify({"error": "功能不存在"}), 404
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
    storage.update(get_db(), "features", f)
    return jsonify(f)

@app.route("/api/features/<feature_id>", methods=["DELETE"])
@db_write
def api_features_delete(feature_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not storage.delete(get_db(), "features", feature_id):
        return jsonify({"error": "功能不存在"}), 404
    return jsonify({"success": True})


# ===== 临时文本 API =====

def load_temp_notes():
    return storage.all_records(get_db(), "temp_notes")


@app.route("/api/temp", methods=["GET"])
def api_temp_list():
    notes = load_temp_notes()
    notes.reverse()
    notes.sort(key=lambda n: n.get("created", 0), reverse=True)
    return jsonify(notes)

@app.route("/api/temp", methods=["POST"])
@db_write
def api_temp_create():
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
    if len(content) > 100000:
        return jsonify({"error": "内容过长"}), 400

    item = {
        "id": uuid.uuid4().hex,
        "title": title,
        "content": content,
        "created": int(time.time()),
    }
    storage.insert(get_db(), "temp_notes", item)
    return jsonify(item), 201

@app.route("/api/temp/<note_id>", methods=["PUT"])
@db_write
def api_temp_update(note_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    n = storage.get(get_db(), "temp_notes", note_id)
    if n is None:
        return jsonify({"error": "内容不存在"}), 404
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            return jsonify({"error": "标题不能为空"}), 400
        if len(title) > 100:
            return jsonify({"error": "标题过长"}), 400
        n["title"] = title
    if "content" in data:
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "内容不能为空"}), 400
        if len(content) > 100000:
            return jsonify({"error": "内容过长"}), 400
        n["content"] = content
    storage.update(get_db(), "temp_notes", n)
    return jsonify(n)

@app.route("/api/temp/<note_id>", methods=["DELETE"])
@db_write
def api_temp_delete(note_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not storage.delete(get_db(), "temp_notes", note_id):
        return jsonify({"error": "内容不存在"}), 404
    return jsonify({"success": True})


# ===== 首页自定义网页卡片 API =====

def load_links():
    return storage.all_records(get_db(), "links")


def valid_url(url):
    return bool(re.match(r'^(https?://|/)', url))

@app.route("/api/links", methods=["GET"])
def api_links_list():
    links = load_links()
    links.sort(key=lambda l: l.get("created", 0), reverse=True)
    return jsonify(links)

@app.route("/api/links", methods=["POST"])
@db_write
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
    storage.insert(get_db(), "links", item)
    return jsonify(item), 201

@app.route("/api/links/<link_id>", methods=["PUT"])
@db_write
def api_links_update(link_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    l = storage.get(get_db(), "links", link_id)
    if l is None:
        return jsonify({"error": "卡片不存在"}), 404
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
    storage.update(get_db(), "links", l)
    return jsonify(l)

@app.route("/api/links/<link_id>", methods=["DELETE"])
@db_write
def api_links_delete(link_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not storage.delete(get_db(), "links", link_id):
        return jsonify({"error": "卡片不存在"}), 404
    return jsonify({"success": True})


# ===== 局域网共享节点（peer）API =====

def load_peers():
    return storage.all_records(get_db(), "peers")


def find_peer(peer_id):
    return storage.get(get_db(), "peers", peer_id)


def peer_online(peer):
    return (int(time.time()) - (peer.get("last_seen") or 0)) <= PEER_TTL

@app.route("/api/peers/register", methods=["POST"])
@db_write
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
    row = get_db().execute("SELECT * FROM peers WHERE host=? AND port=?", (host, port)).fetchone()
    if row is not None:
        p = storage.decode("peers", row)
        p["name"] = name
        p["dir_label"] = dir_label
        p["last_seen"] = now
        storage.update(get_db(), "peers", p)
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
    storage.insert(get_db(), "peers", peer)
    return jsonify(peer), 201

@app.route("/api/peers", methods=["GET"])
@db_write
def api_peers_list():
    get_db().execute("DELETE FROM peers WHERE last_seen < ?", (int(time.time()) - PEER_TTL,))
    online = load_peers()
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
@db_write
def api_peers_unregister():
    data = request.get_json() or {}
    secret = (data.get("secret") or "").strip()
    if not PEER_SECRET or secret != PEER_SECRET:
        return jsonify({"error": "注册密钥不正确"}), 403
    host = (data.get("host") or "").strip()
    port = data.get("port")
    if not host or not isinstance(port, int):
        return jsonify({"error": "参数无效"}), 400
    if not get_db().execute("DELETE FROM peers WHERE host=? AND port=?", (host, port)).rowcount:
        return jsonify({"error": "节点不存在"}), 404
    return jsonify({"success": True})

@app.route("/api/peers/<peer_id>", methods=["DELETE"])
@db_write
def api_peers_delete(peer_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    if not storage.delete(get_db(), "peers", peer_id):
        return jsonify({"error": "节点不存在"}), 404
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

# ===== 文档（doc/docx）在线阅读 =====

def docx_to_html(data):
    """将 .docx 字节提取为完整 HTML（正文/标题/表格/内嵌图片，均 stdlib）。"""
    import io
    import base64
    import html as _html
    from xml.etree import ElementTree as ET
    import posixpath

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml",
            ".tif": "image/tiff", ".tiff": "image/tiff"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        root = ET.fromstring(zf.read("word/document.xml"))
    except Exception:
        raise ValueError("不是有效的 .docx 文件（无法解析）")

    # 关系 -> 内嵌媒体
    media = {}
    try:
        rels = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        for rel in rels:
            rid = rel.get("Id")
            tgt = rel.get("Target") or ""
            if not rid or not tgt:
                continue
            candidates = []
            if tgt.startswith("/"):
                candidates.append(tgt.lstrip("/"))
            else:
                candidates.append(posixpath.normpath(posixpath.join("word", tgt)).lstrip("/"))
                candidates.append(posixpath.normpath(posixpath.join("word/_rels", tgt)).lstrip("/"))
            for name in candidates:
                if "/media/" not in "/" + name:
                    continue
                try:
                    mbytes = zf.read(name)
                except KeyError:
                    continue
                media[rid] = {"ext": os.path.splitext(name)[1].lower(), "data": mbytes}
                break
    except Exception:
        pass

    def media_img(rid):
        m = media.get(rid)
        if not m:
            return None
        mime = MIME.get(m["ext"])
        if not mime:
            return None
        b64 = base64.b64encode(m["data"]).decode("ascii")
        return '<img src="data:%s;base64,%s" class="doci" alt="">' % (mime, b64)

    def walk_inline(node):
        out = []

        def rec(n):
            for c in n:
                tag = c.tag
                if tag == W + "t":
                    out.append(_html.escape(c.text or "", quote=False))
                elif tag == W + "tab":
                    out.append("&#9;")
                elif tag == W + "br":
                    out.append("<br>")
                elif str(tag).endswith("}imagedata") or str(tag).endswith("}blip"):
                    for v in c.attrib.values():
                        if v in media:
                            img = media_img(v)
                            if img:
                                out.append(img)
                            break
                else:
                    rec(c)

        rec(node)
        return "".join(out)

    def para_html(p):
        ppr = p.find(W + "pPr")
        tag = "p"
        dlist = False
        if ppr is not None:
            pst = ppr.find(W + "pStyle")
            if pst is not None:
                v = (pst.get(W + "val") or "").strip()
                m = re.match(r"(?i)heading\s*([1-6])$", v)
                if m:
                    tag = "h" + m.group(1)
                elif v in ("1", "2", "3", "4", "5", "6"):
                    tag = "h" + v
            if ppr.find(W + "numPr") is not None:
                dlist = True
        inner = walk_inline(p)
        if not inner.strip():
            return "<p>&nbsp;</p>"
        if tag != "p":
            return "<%s>%s</%s>" % (tag, inner, tag)
        if dlist:
            return '<p class="dlist">• %s</p>' % inner
        return "<p>%s</p>" % inner

    def tbl_html(tbl):
        rows = ""
        for tr in tbl.findall(W + "tr"):
            cells = ""
            for tc in tr.findall(W + "tc"):
                cell = ""
                for p in tc.findall(W + "p"):
                    cell += para_html(p)
                cells += "<td>%s</td>" % cell
            rows += "<tr>%s</tr>" % cells
        return '<table class="doct"><tbody>%s</tbody></table>' % rows

    body = root.find(W + "body")
    blocks = []
    for el in body:
        if el.tag == W + "p":
            blocks.append(para_html(el))
        elif el.tag == W + "tbl":
            blocks.append(tbl_html(el))
    content = "".join(blocks) or "<p>（文档内容为空）</p>"

    style = (
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',"
        "Arial,sans-serif;color:#222;line-height:1.75;margin:0;}"
        ".docbody{max-width:880px;margin:0 auto;padding:1.5em 2em;word-break:break-word;}"
        "h1,h2,h3,h4,h5,h6{color:#2c3e50;line-height:1.35;}"
        "h1{font-size:1.7em;border-bottom:2px solid #eee;padding-bottom:.25em;}"
        "h2{font-size:1.4em;border-bottom:1px solid #eee;padding-bottom:.2em;}"
        "img.doci{max-width:100%;height:auto;}"
        "table.doct{border-collapse:collapse;margin:1em 0;max-width:100%;}"
        "table.doct td,table.doct th{border:1px solid #ccc;padding:4px 9px;font-size:.95em;}"
        "p.dlist{margin:.2em 0;}"
    )
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>%s</style></head>"
            "<body><div class=\"docbody\">%s</div></body></html>" % (style, content))


def doc_bytes_to_html(data, ext):
    """把文档字节转成完整 HTML。.docx 走 stdlib；.doc 走 LibreOffice；按字节哈希缓存。"""
    h = hashlib.sha1(data).hexdigest()
    os.makedirs(TMP_DOCS_DIR, exist_ok=True)
    cache = os.path.join(TMP_DOCS_DIR, h + ".html")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            pass

    if ext == ".docx":
        html = docx_to_html(data)
    else:
        import tempfile
        import glob
        with tempfile.TemporaryDirectory(prefix="lodoc_") as td:
            src = os.path.join(td, "input.doc")
            with open(src, "wb") as f:
                f.write(data)
            outdir = os.path.join(td, "out")
            os.makedirs(outdir, exist_ok=True)
            try:
                r = subprocess.run(
                    ["soffice", "--headless", "--norestore",
                     "-env:UserInstallation=file://" + os.path.join(td, "profile"),
                     "--convert-to", "html", "--outdir", outdir, src],
                    capture_output=True, timeout=180)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise ValueError("LibreOffice 调用失败: %s（是否已安装？）" % e)
            found = glob.glob(os.path.join(outdir, "*.html"))
            if not found:
                detail = (r.stderr or b"").decode("utf-8", "replace").strip()
                raise ValueError("文档转换失败%s" % (": " + detail[:200] if detail else ""))
            with open(found[0], "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
    try:
        with open(cache, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError:
        pass
    return html


def read_doc_bytes(full_or_url):
    """统一读取本地文件或 URL 的字节，带容量上限。返回 bytes。"""
    if isinstance(full_or_url, str) and (full_or_url.startswith("http://") or full_or_url.startswith("https://")):
        try:
            with urllib.request.urlopen(full_or_url, timeout=30) as resp:
                data = resp.read(MAX_DOC_BYTES + 1)
        except urllib.error.URLError as e:
            raise ValueError(peer_conn_error({"host": "", "port": ""}, e))
        except socket.timeout:
            raise ValueError("读取文件超时")
    else:
        try:
            with open(full_or_url, "rb") as f:
                data = f.read(MAX_DOC_BYTES + 1)
        except OSError as e:
            raise ValueError("读取文件失败: %s" % e)
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("文件过大（>50MB），暂不支持在线阅读")
    return data


@app.route("/api/doc")
def api_doc_read():
    path = (request.args.get("path") or "").strip().strip("/")
    full = safe_join_soft(UPLOAD_DIR, path)
    if not full or not os.path.isfile(full):
        return jsonify({"error": "文件不存在"}), 404
    ext = os.path.splitext(full)[1].lower()
    if ext not in DOC_READ_EXTS:
        return jsonify({"error": "仅支持阅读 .doc / .docx 文件"}), 400
    try:
        data = read_doc_bytes(full)
        html = doc_bytes_to_html(data, ext)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return app.response_class(html, mimetype="text/html")


@app.route("/api/peers/<peer_id>/doc", methods=["GET"])
def api_peers_doc(peer_id):
    peer = find_peer(peer_id)
    if not peer:
        return jsonify({"error": "节点不存在"}), 404
    if not peer_online(peer):
        return jsonify({"error": "节点离线"}), 503
    path = (request.args.get("path") or "").strip().strip("/")
    ext = os.path.splitext(path)[1].lower()
    if not path or ext not in DOC_READ_EXTS:
        return jsonify({"error": "仅支持阅读 .doc / .docx 文件"}), 400
    url = "http://{}:{}/files/{}".format(peer["host"], peer["port"], quote(path, safe="/"))
    try:
        data = read_doc_bytes(url)
        html = doc_bytes_to_html(data, ext)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except urllib.error.URLError as e:
        return jsonify({"error": peer_conn_error(peer, e)}), 502
    return app.response_class(html, mimetype="text/html")

# ===== 自定义页面 API =====

def load_pages():
    return storage.all_records(get_db(), "pages")


def find_page(page_id):
    return storage.get(get_db(), "pages", page_id)


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

# ===== 每周周报 API =====
def parse_weekly_markdown(text):
    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not re.fullmatch(r'# [^#].*', lines[index].strip()):
        raise ValueError('缺少周报标题，第一行应为“# 周报标题”')
    title = lines[index].strip()[2:].strip()
    if not title or len(title) > 200:
        raise ValueError('周报标题不能为空且不能超过 200 个字符')

    index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        raise ValueError('缺少周报时间范围')
    match = re.fullmatch(
        r'时间：(\d{4}-\d{2}-\d{2})\s+至\s+(\d{4}-\d{2}-\d{2})',
        lines[index].strip(),
    )
    if not match or match.group(1) > match.group(2):
        raise ValueError('时间范围格式无效，应为“时间：YYYY-MM-DD 至 YYYY-MM-DD”')

    projects = []
    project_names = set()
    people = []
    people_seen = set()
    current_project = None
    current_person = None
    content_lines = []

    def finish_person():
        nonlocal current_person, content_lines
        if current_person is None:
            return
        current_project['contents'][current_person] = '\n'.join(content_lines).strip()
        current_person = None
        content_lines = []

    for line in lines[index + 1:]:
        if line.startswith('## '):
            finish_person()
            name = line[3:].strip()
            if not name or len(name) > 100:
                raise ValueError('项目名称不能为空且不能超过 100 个字符')
            if name in project_names:
                raise ValueError('项目重复：' + name)
            current_project = {'name': name, 'contents': {}}
            projects.append(current_project)
            project_names.add(name)
        elif line.startswith('### '):
            if current_project is None:
                raise ValueError('人员标题必须位于项目标题之后')
            finish_person()
            name = re.sub(r'\s+', ' ', line[4:].strip())
            if not name or len(name) > 100:
                raise ValueError('人员名称不能为空且不能超过 100 个字符')
            if name in current_project['contents']:
                raise ValueError('项目“' + current_project['name'] + '”中的人员重复：' + name)
            current_person = name
            if name not in people_seen:
                people.append(name)
                people_seen.add(name)
        elif current_person is not None:
            content_lines.append(line)
        elif line.strip():
            raise ValueError('项目内容必须位于人员标题之后')
    finish_person()
    return {
        'title': title,
        'week_start': match.group(1),
        'week_end': match.group(2),
        'projects': projects,
        'people': people,
    }


@app.route("/api/weekly/default-projects", methods=["GET"])
def api_weekly_default_projects():
    rows = get_db().execute("SELECT * FROM weekly_default_projects ORDER BY position, seq").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/weekly/default-projects", methods=["POST"])
@db_write
def api_weekly_default_project_create():
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}; name = (data.get("name") or "").strip()
    if not name: return jsonify({"error": "项目名称不能为空"}), 400
    if get_db().execute("SELECT 1 FROM weekly_default_projects WHERE name=?", (name,)).fetchone(): return jsonify({"error": "项目名称已存在"}), 409
    pos = get_db().execute("SELECT COALESCE(MAX(position),-1)+1 FROM weekly_default_projects").fetchone()[0]; now = int(time.time()); pid = uuid.uuid4().hex[:12]
    get_db().execute("INSERT INTO weekly_default_projects(id,name,required,position,created,updated) VALUES(?,?,?,?,?,?)", (pid,name,1 if data.get("required") else 0,pos,now,now))
    return jsonify(dict(get_db().execute("SELECT * FROM weekly_default_projects WHERE id=?",(pid,)).fetchone())), 201

@app.route("/api/weekly/default-projects/<project_id>", methods=["PUT"])
@db_write
def api_weekly_default_project_update(project_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    row=get_db().execute("SELECT * FROM weekly_default_projects WHERE id=?",(project_id,)).fetchone()
    if not row: return jsonify({"error":"默认项目不存在"}),404
    data=request.get_json() or {}; name=(data.get("name",row["name"]) or "").strip(); pos=int(data.get("position",row["position"]))
    if not name:return jsonify({"error":"项目名称不能为空"}),400
    if get_db().execute("SELECT 1 FROM weekly_default_projects WHERE name=? AND id<>?",(name,project_id)).fetchone():return jsonify({"error":"项目名称已存在"}),409
    get_db().execute("UPDATE weekly_default_projects SET name=?,required=?,position=?,updated=? WHERE id=?",(name,1 if data.get("required",bool(row["required"])) else 0,pos,int(time.time()),project_id))
    return jsonify(dict(get_db().execute("SELECT * FROM weekly_default_projects WHERE id=?",(project_id,)).fetchone()))

@app.route("/api/weekly/default-projects/<project_id>", methods=["DELETE"])
@db_write
def api_weekly_default_project_delete(project_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    if not get_db().execute("DELETE FROM weekly_default_projects WHERE id=?",(project_id,)).rowcount:return jsonify({"error":"默认项目不存在"}),404
    return jsonify({"success":True})

def weekly_report(row):
    return dict(row) if row else None

def weekly_detail(report_id):
    db = get_db()
    report = weekly_report(db.execute("SELECT * FROM weekly_reports WHERE id=?", (report_id,)).fetchone())
    if not report:
        return None
    projects = [dict(r) for r in db.execute("SELECT * FROM weekly_projects WHERE report_id=? ORDER BY position, seq", (report_id,))]
    submissions = []
    for r in db.execute("SELECT * FROM weekly_submissions WHERE report_id=? ORDER BY person_name COLLATE NOCASE, seq", (report_id,)):
        item = dict(r)
        item["contents"] = json.loads(item["contents"] or "{}")
        submissions.append(item)
    report["projects"] = projects
    report["submissions"] = submissions
    return report

@app.route("/api/weekly", methods=["GET"])
def api_weekly_list():
    limit = request.args.get("limit")
    query = ("SELECT weekly_reports.*, "
             "(SELECT COUNT(*) FROM weekly_submissions "
             "WHERE weekly_submissions.report_id=weekly_reports.id) AS submission_count "
             "FROM weekly_reports ORDER BY week_start DESC, created DESC, seq DESC")
    params = ()
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return jsonify({"error": "limit 必须是正整数"}), 400
        if limit <= 0:
            return jsonify({"error": "limit 必须是正整数"}), 400
        query += " LIMIT ?"
        params = (limit,)
    rows = get_db().execute(query, params).fetchall()
    return jsonify([weekly_report(r) for r in rows])

@app.route("/api/weekly", methods=["POST"])
@db_write
def api_weekly_create():
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    start, end = (data.get("week_start") or "").strip(), (data.get("week_end") or "").strip()
    if not title or not start or not end: return jsonify({"error": "标题、开始日期和结束日期不能为空"}), 400
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', start) or not re.match(r'^\d{4}-\d{2}-\d{2}$', end) or start > end:
        return jsonify({"error": "日期格式无效或开始日期晚于结束日期"}), 400
    now = int(time.time()); item = {"id": uuid.uuid4().hex[:12], "title": title, "week_start": start, "week_end": end, "created": now, "updated": now}
    get_db().execute("INSERT INTO weekly_reports(id,title,week_start,week_end,created,updated) VALUES (?,?,?,?,?,?)", tuple(item.values()))
    defaults = get_db().execute("SELECT name,required,position FROM weekly_default_projects ORDER BY position,seq").fetchall()
    for project in defaults:
        pid = uuid.uuid4().hex[:12]
        get_db().execute("INSERT INTO weekly_projects(id,report_id,name,required,position,created,updated) VALUES(?,?,?,?,?,?,?)", (pid, item["id"], project["name"], project["required"], project["position"], now, now))
    return jsonify(weekly_detail(item["id"])), 201


@app.route("/api/weekly/import", methods=["POST"])
def api_weekly_import():
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "请选择 Markdown 文件"}), 400
    if os.path.splitext(upload.filename)[1].lower() != ".md":
        return jsonify({"error": "仅支持 .md 文件"}), 400
    raw = upload.stream.read(MAX_WEEKLY_IMPORT_BYTES + 1)
    if len(raw) > MAX_WEEKLY_IMPORT_BYTES:
        return jsonify({"error": "Markdown 文件不能超过 5 MiB"}), 413
    try:
        imported = parse_weekly_markdown(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return jsonify({"error": "Markdown 文件必须使用 UTF-8 编码"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db = get_db()
    with storage.transaction(db):
        duplicate = db.execute(
            "SELECT 1 FROM weekly_reports WHERE title=? AND week_start=? AND week_end=?",
            (imported["title"], imported["week_start"], imported["week_end"]),
        ).fetchone()
        if duplicate:
            return jsonify({"error": "已存在标题和时间范围相同的周报"}), 409

        now = int(time.time())
        report_id = uuid.uuid4().hex[:12]
        db.execute(
            "INSERT INTO weekly_reports(id,title,week_start,week_end,created,updated) "
            "VALUES(?,?,?,?,?,?)",
            (report_id, imported["title"], imported["week_start"],
             imported["week_end"], now, now),
        )
        projects = {}
        max_position = -1
        defaults = db.execute(
            "SELECT name,required,position FROM weekly_default_projects ORDER BY position,seq"
        ).fetchall()
        for default in defaults:
            project_id = uuid.uuid4().hex[:12]
            max_position = max(max_position, default["position"])
            db.execute(
                "INSERT INTO weekly_projects(id,report_id,name,required,position,created,updated) "
                "VALUES(?,?,?,?,?,?,?)",
                (project_id, report_id, default["name"], default["required"],
                 default["position"], now, now),
            )
            projects[default["name"]] = {
                "id": project_id, "required": bool(default["required"]),
            }
        for imported_project in imported["projects"]:
            if imported_project["name"] in projects:
                continue
            max_position += 1
            project_id = uuid.uuid4().hex[:12]
            db.execute(
                "INSERT INTO weekly_projects(id,report_id,name,required,position,created,updated) "
                "VALUES(?,?,?,?,?,?,?)",
                (project_id, report_id, imported_project["name"], 0,
                 max_position, now, now),
            )
            projects[imported_project["name"]] = {"id": project_id, "required": False}

        imported_by_project = {project["name"]: project for project in imported["projects"]}
        for person in imported["people"]:
            contents = {}
            for project_name, project in projects.items():
                value = imported_by_project.get(project_name, {}).get("contents", {}).get(person, "")
                contents[project["id"]] = value if value.strip() else ("无" if project["required"] else "")
            submission_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO weekly_submissions"
                "(id,report_id,person_name,contents,revision,created,updated) "
                "VALUES(?,?,?,?,?,?,?)",
                (submission_id, report_id, person,
                 json.dumps(contents, ensure_ascii=False), 1, now, now),
            )
    return jsonify(weekly_detail(report_id)), 201

@app.route("/api/weekly/<report_id>", methods=["GET"])
def api_weekly_detail(report_id):
    data = weekly_detail(report_id)
    return jsonify(data) if data else (jsonify({"error": "周报不存在"}), 404)

@app.route("/api/weekly/<report_id>", methods=["PUT"])
@db_write
def api_weekly_update(report_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    report = get_db().execute("SELECT * FROM weekly_reports WHERE id=?", (report_id,)).fetchone()
    if not report: return jsonify({"error": "周报不存在"}), 404
    data = request.get_json() or {}; title = (data.get("title", report["title"]) or "").strip(); start = (data.get("week_start", report["week_start"]) or "").strip(); end = (data.get("week_end", report["week_end"]) or "").strip()
    if not title or not re.match(r'^\d{4}-\d{2}-\d{2}$', start) or not re.match(r'^\d{4}-\d{2}-\d{2}$', end) or start > end: return jsonify({"error": "标题或日期无效"}), 400
    get_db().execute("UPDATE weekly_reports SET title=?,week_start=?,week_end=?,updated=? WHERE id=?", (title, start, end, int(time.time()), report_id))
    return jsonify(weekly_detail(report_id))

@app.route("/api/weekly/<report_id>", methods=["DELETE"])
@db_write
def api_weekly_delete(report_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    if not get_db().execute("DELETE FROM weekly_reports WHERE id=?", (report_id,)).rowcount: return jsonify({"error": "周报不存在"}), 404
    return jsonify({"success": True})

@app.route("/api/weekly/<report_id>/projects", methods=["POST"])
@db_write
def api_weekly_project_create(report_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    data = request.get_json() or {}; name = (data.get("name") or "").strip()
    if not name or not get_db().execute("SELECT 1 FROM weekly_reports WHERE id=?", (report_id,)).fetchone(): return jsonify({"error": "周报不存在或项目名称为空"}), 400
    if get_db().execute("SELECT 1 FROM weekly_projects WHERE report_id=? AND name=?", (report_id, name)).fetchone(): return jsonify({"error": "项目名称已存在"}), 409
    pos = get_db().execute("SELECT COALESCE(MAX(position),-1)+1 FROM weekly_projects WHERE report_id=?", (report_id,)).fetchone()[0]; now = int(time.time()); pid = uuid.uuid4().hex[:12]
    get_db().execute("INSERT INTO weekly_projects(id,report_id,name,required,position,created,updated) VALUES(?,?,?,?,?,?,?)", (pid, report_id, name, 1 if data.get("required", False) else 0, pos, now, now))
    return jsonify(weekly_detail(report_id)), 201

@app.route("/api/weekly/<report_id>/projects/<project_id>", methods=["PUT"])
@db_write
def api_weekly_project_update(report_id, project_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    row = get_db().execute("SELECT * FROM weekly_projects WHERE id=? AND report_id=?", (project_id, report_id)).fetchone()
    if not row: return jsonify({"error": "项目不存在"}), 404
    data = request.get_json() or {}; name = (data.get("name", row["name"]) or "").strip(); required = 1 if data.get("required", bool(row["required"])) else 0
    if not name: return jsonify({"error": "项目名称不能为空"}), 400
    if get_db().execute("SELECT 1 FROM weekly_projects WHERE report_id=? AND name=? AND id<>?", (report_id, name, project_id)).fetchone(): return jsonify({"error": "项目名称已存在"}), 409
    pos = int(data.get("position", row["position"])); now = int(time.time()); get_db().execute("UPDATE weekly_projects SET name=?,required=?,position=?,updated=? WHERE id=?", (name, required, pos, now, project_id)); return jsonify(weekly_detail(report_id))

@app.route("/api/weekly/<report_id>/projects/<project_id>", methods=["DELETE"])
@db_write
def api_weekly_project_delete(report_id, project_id):
    if not require_local(): return jsonify({"error": "仅限本机访问"}), 403
    if not get_db().execute("DELETE FROM weekly_projects WHERE id=? AND report_id=?", (project_id, report_id)).rowcount: return jsonify({"error": "项目不存在"}), 404
    rows = get_db().execute("SELECT id,contents FROM weekly_submissions WHERE report_id=?", (report_id,)).fetchall()
    for row in rows:
        contents = json.loads(row["contents"] or "{}"); contents.pop(project_id, None); get_db().execute("UPDATE weekly_submissions SET contents=?,revision=revision+1,updated=? WHERE id=?", (json.dumps(contents, ensure_ascii=False), int(time.time()), row["id"]))
    return jsonify(weekly_detail(report_id))

@app.route("/api/weekly/<report_id>/submissions", methods=["GET"])
def api_weekly_submissions(report_id):
    data = weekly_detail(report_id)
    if not data: return jsonify({"error": "周报不存在"}), 404
    return jsonify(data["submissions"])

@app.route("/api/weekly/<report_id>/people", methods=["GET"])
def api_weekly_people(report_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM weekly_reports WHERE id=?", (report_id,)).fetchone():
        return jsonify({"error": "周报不存在"}), 404
    rows = db.execute(
        "SELECT person_name FROM weekly_submissions WHERE report_id=? "
        "ORDER BY person_name COLLATE NOCASE, seq", (report_id,)
    ).fetchall()
    return jsonify([row["person_name"] for row in rows])

@app.route("/api/weekly/<report_id>/submissions", methods=["POST"])
@db_write
def api_weekly_submission_save(report_id):
    report = weekly_detail(report_id)
    if not report: return jsonify({"error": "周报不存在"}), 404
    data = request.get_json() or {}; name = re.sub(r'\s+', ' ', (data.get("person_name") or "").strip()); contents = data.get("contents") or {}; submission_id = data.get("submission_id"); expected_revision = data.get("expected_revision")
    if not name or len(name) > 100: return jsonify({"error": "人员名称不能为空且不能超过 100 个字符"}), 400
    allowed = {p["id"]: p for p in report["projects"]}
    if not isinstance(contents, dict): return jsonify({"error": "项目内容格式无效"}), 400
    for pid, project in allowed.items():
        value = contents.get(pid, "")
        if not isinstance(value, str): return jsonify({"error": "项目内容格式无效"}), 400
        if project["required"] and not value.strip(): return jsonify({"error": "请填写必填项目：" + project["name"]}), 400
    contents = {pid: contents.get(pid, "") for pid in allowed}; encoded = json.dumps(contents, ensure_ascii=False); now = int(time.time())
    if submission_id is not None:
        if not isinstance(submission_id, str) or type(expected_revision) is not int or expected_revision < 1:
            return jsonify({"error": "提交版本无效，请重新加载后再保存"}), 409
        old = get_db().execute("SELECT id FROM weekly_submissions WHERE id=? AND report_id=?", (submission_id, report_id)).fetchone()
        if not old:
            return jsonify({"error": "该人员的周报已发生变化，请重新加载后再保存"}), 409
        duplicate = get_db().execute("SELECT 1 FROM weekly_submissions WHERE report_id=? AND person_name=? AND id<>?", (report_id, name, submission_id)).fetchone()
        if duplicate:
            return jsonify({"error": "人员名称已存在：" + name}), 409
        changed = get_db().execute("UPDATE weekly_submissions SET person_name=?,contents=?,revision=revision+1,updated=? WHERE id=? AND revision=?", (name, encoded, now, submission_id, expected_revision)).rowcount
        if not changed:
            return jsonify({"error": "该人员的周报已被其他人修改，请重新加载后再保存"}), 409
        sid = submission_id
    else:
        if get_db().execute("SELECT 1 FROM weekly_submissions WHERE report_id=? AND person_name=?", (report_id, name)).fetchone():
            return jsonify({"error": "该人员已有提交，请使用“修改已有提交”加载最新内容"}), 409
        sid = uuid.uuid4().hex
        get_db().execute("INSERT INTO weekly_submissions(id,report_id,person_name,contents,revision,created,updated) VALUES(?,?,?,?,?,?,?)", (sid, report_id, name, encoded, 1, now, now))
    return jsonify(next(s for s in weekly_detail(report_id)["submissions"] if s["id"] == sid))

@app.route("/api/weekly/<report_id>/export")
def api_weekly_export(report_id):
    data = weekly_detail(report_id)
    if not data: return jsonify({"error": "周报不存在"}), 404
    view = request.args.get("view", "project")
    person = request.args.get("person")
    if person is not None:
        person = re.sub(r'\s+', ' ', person.strip())
        if not person:
            return jsonify({"error": "人员名称不能为空"}), 400
    lines = [f"# {data['title']}", f"\n时间：{data['week_start']} 至 {data['week_end']}"]
    by_person = {s["person_name"]: s for s in data["submissions"]}
    if person is not None:
        if person not in by_person:
            return jsonify({"error": "人员不存在：" + person}), 404
        by_person = {person: by_person[person]}
    if view == "person":
        for name, sub in sorted(by_person.items(), key=lambda x: x[0].lower()):
            filled = [(p, sub["contents"].get(p["id"], "")) for p in data["projects"]]
            filled = [(p, value) for p, value in filled if isinstance(value, str) and value.strip()]
            if not filled:
                continue
            lines += [f"\n## {name}"]
            for p, value in filled:
                lines += [f"\n### {p['name']}", value]
    else:
        for p in data["projects"]:
            filled = [(name, sub["contents"].get(p["id"], "")) for name, sub in sorted(by_person.items(), key=lambda x: x[0].lower())]
            filled = [(name, value) for name, value in filled if isinstance(value, str) and value.strip()]
            if not filled:
                continue
            lines += [f"\n## {p['name']}"]
            for name, value in filled:
                lines += [f"\n### {name}", value]
    filename = quote(data["title"] + ".md")
    return Response("\n".join(lines) + "\n", mimetype="text/markdown; charset=utf-8", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + filename})

@app.route("/api/pages", methods=["GET"])
def api_pages_list():
    pages = load_pages()
    pages.sort(key=lambda p: p.get("created", 0), reverse=True)
    return jsonify(pages)

@app.route("/api/pages", methods=["POST"])
@db_write
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
    storage.insert(get_db(), "pages", page)
    return jsonify(page), 201

@app.route("/api/pages/<page_id>", methods=["PUT"])
@db_write
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
    storage.update(get_db(), "pages", page)
    return jsonify(page)

@app.route("/api/pages/<page_id>", methods=["DELETE"])
def api_pages_delete(page_id):
    if not require_local():
        return jsonify({"error": "仅限本机访问"}), 403
    # Commit metadata first, as before; recursive filesystem removal holds no DB lock.
    with storage.transaction(get_db()):
        if not storage.delete(get_db(), "pages", page_id):
            return jsonify({"error": "页面不存在"}), 404
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
    with app.app_context():
        get_db()  # Fail before listening if migration has not completed.
    app.run(host="127.0.0.1", port=5000, debug=False)
