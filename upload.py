import os
import re
import shutil
from flask import Flask, request, jsonify

app = Flask(__name__)
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
            entries.append({
                "name": name,
                "type": "dir" if is_dir else "file",
                "size": st.st_size if not is_dir else 0,
                "mtime": int(st.st_mtime)
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
