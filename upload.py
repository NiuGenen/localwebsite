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

@app.route("/api/local")
def api_local():
    client = request.headers.get("X-Real-IP", "") or request.remote_addr or ""
    return jsonify({"local": client in LOCAL_IPS})

# ===== 待办事项 API =====

def load_todos():
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
