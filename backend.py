import os
import re
import shutil
import time
import uuid
import json
from flask import Flask, request, jsonify

app = Flask(__name__)
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 本机访问判定（仅回环地址）=====
LOCAL_IPS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# ===== 待办事项数据文件 =====
TODO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "todo.json")
PRIORITIES = ("high", "medium", "low")
TODO_STATUSES = {"pending", "in_progress", "paused"}

# ===== 实用功能数据文件 =====
FEATURES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "features.json")

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

    try:
        names = sorted(os.listdir(target_dir))
    except Exception:
        return jsonify({"error": "cannot list directory"}), 500

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
