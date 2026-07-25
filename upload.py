import os
import re
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 禁止上传/创建的黑名单（相对 files/，前缀匹配）=====
BLOCKED_PATHS = ["binary-translation"]

# ===== 路径工具 =====

def safe_join(base, child):
    if not child or child.strip() == "":
        return base
    result = os.path.realpath(os.path.join(base, child))
    base_real = os.path.realpath(base)
    if not result.startswith(base_real + os.sep):
        return None
    return result

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

def list_subdirs(base):
    dirs = []
    for root, dirnames, _ in os.walk(base):
        dirnames.sort()
        for d in dirnames:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, base)
            dirs.append(rel)
    return dirs

def render_page(message=None, error=None):
    return render_template_string(UPLOAD_FORM, message=message, error=error)

# ===== 文件浏览 API =====

@app.route("/api/files")
def api_list_files():
    path = request.args.get("path", "").strip().strip("/")
    target_dir = UPLOAD_DIR
    if path:
        joined = os.path.join(UPLOAD_DIR, path)
        target_dir = os.path.normpath(joined)
        if not target_dir.startswith(UPLOAD_DIR.rstrip("/") + "/"):
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
    return jsonify({"entries": entries, "path": path})

# ===== API =====

@app.route("/upload/api/dirs")
def api_dirs():
    all_dirs = list_subdirs(UPLOAD_DIR)
    allowed = [d for d in all_dirs if not is_blocked(d)]
    return jsonify({"dirs": allowed})

@app.route("/upload/api/mkdir", methods=["POST"])
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

    new_dir = os.path.join(parent_dir, name)
    new_dir_norm = os.path.normpath(new_dir)
    base_str = UPLOAD_DIR.rstrip("/") + "/"
    if not new_dir_norm.startswith(base_str):
        return jsonify({"error": "无效的路径"}), 400

    try:
        os.makedirs(new_dir_norm, exist_ok=True)
        rel_path = os.path.relpath(new_dir_norm, UPLOAD_DIR)
        return jsonify({"success": True, "path": rel_path})
    except Exception as e:
        return jsonify({"error": f"创建失败: {e}"}), 500

# ===== 上传页面 =====

UPLOAD_FORM = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>文件上传</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    <header>
        <h1>本地文件站</h1>
        <nav>
            <a href="/">首页</a>
            <a href="/files/">文件下载</a>
            <a href="/upload" class="active">文件上传</a>
            <a href="/reader.html">Markdown阅读</a>
            <a href="/info.html">关于</a>
        </nav>
    </header>
    <main>
        <section class="content upload-panel">
            <h2>文件上传</h2>
            <form method="post" enctype="multipart/form-data" action="/upload" id="upload-form">
                <div class="form-row">
                    <label for="dir-select">目标目录</label>
                    <div class="dir-select-group">
                        <select name="dir" id="dir-select">
                            <option value="">根目录 (files/)</option>
                        </select>
                        <button type="button" class="btn btn-sm" id="refresh-dirs-btn">刷新</button>
                    </div>
                </div>
                <div class="form-row">
                    <label for="new-folder-name">新建文件夹</label>
                    <div class="dir-create-group">
                        <input type="text" id="new-folder-name" placeholder="输入文件夹名称">
                        <button type="button" class="btn btn-sm btn-success" id="create-folder-btn">创建</button>
                    </div>
                    <p class="form-hint" id="mkdir-hint"></p>
                </div>
                <div class="form-row">
                    <label for="file-input">选择文件</label>
                    <input type="file" name="file" id="file-input" required>
                </div>
                <div class="form-actions">
                    <button type="submit" class="btn btn-primary">上传</button>
                </div>
            </form>
            {% if message %}
            <div class="upload-msg upload-msg-ok">{{ message }}</div>
            {% endif %}
            {% if error %}
            <div class="upload-msg upload-msg-err">{{ error }}</div>
            {% endif %}
        </section>
    </main>
    <footer>
        <p>&copy; 2026 本地文件站</p>
    </footer>
    <script>
(function () {
    var dirSelect = document.getElementById('dir-select');
    var refreshBtn = document.getElementById('refresh-dirs-btn');
    var createBtn = document.getElementById('create-folder-btn');
    var newFolderInput = document.getElementById('new-folder-name');
    var mkdirHint = document.getElementById('mkdir-hint');
    var form = document.getElementById('upload-form');

    function loadDirs(selectValue) {
        fetch('/upload/api/dirs')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var val = selectValue !== undefined ? selectValue : dirSelect.value;
                dirSelect.innerHTML = '<option value="">根目录 (files/)</option>';
                data.dirs.forEach(function (d) {
                    var opt = document.createElement('option');
                    opt.value = d;
                    opt.textContent = d + '/';
                    dirSelect.appendChild(opt);
                });
                if (val) dirSelect.value = val;
            })
            .catch(function () {
                mkdirHint.textContent = '加载目录列表失败';
                mkdirHint.className = 'form-hint hint-err';
            });
    }

    function setHint(msg, isErr) {
        mkdirHint.textContent = msg;
        mkdirHint.className = 'form-hint' + (isErr ? ' hint-err' : ' hint-ok');
    }

    refreshBtn.addEventListener('click', function () { loadDirs(); });

    createBtn.addEventListener('click', function () {
        var name = newFolderInput.value.trim();
        if (!name) { setHint('请输入文件夹名称', true); return; }
        createBtn.disabled = true;
        createBtn.textContent = '创建中...';
        setHint('', false);

        fetch('/upload/api/mkdir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent: dirSelect.value, name: name })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    setHint('已创建: ' + data.path, false);
                    newFolderInput.value = '';
                    loadDirs(data.path);
                } else {
                    setHint(data.error || '创建失败', true);
                }
            })
            .catch(function () {
                setHint('网络错误', true);
            })
            .finally(function () {
                createBtn.disabled = false;
                createBtn.textContent = '创建';
            });
    });

    newFolderInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); createBtn.click(); }
    });

    form.addEventListener('submit', function () {
        document.querySelector('.form-actions .btn').disabled = true;
    });

    loadDirs();
})();
    </script>
</body>
</html>
"""

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_page()

    if "file" not in request.files:
        return render_page(error="未选择文件")

    f = request.files["file"]
    if f.filename == "":
        return render_page(error="未选择文件")

    subdir = request.form.get("dir", "").strip()
    target_dir = UPLOAD_DIR

    if subdir:
        if is_blocked(subdir):
            return render_page(error="该目录不允许文件上传"), 403
        target_dir = safe_join_soft(UPLOAD_DIR, subdir)
        if not target_dir:
            return render_page(error="无效的目录路径"), 400

    save_path = os.path.join(target_dir, f.filename)
    save_path_norm = os.path.normpath(save_path)
    base_str = UPLOAD_DIR.rstrip("/") + "/"
    if not save_path_norm.startswith(base_str):
        return render_page(error="无效的文件路径"), 400

    f.save(save_path_norm)
    return render_page(message=f"文件 {f.filename} 上传成功")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
