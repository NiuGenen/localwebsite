(function () {
    var appEl = document.getElementById('custom-app');
    var errorEl = document.getElementById('custom-error');
    var titleEl = document.getElementById('custom-title');
    var descEl = document.getElementById('custom-desc');
    var manageEl = document.getElementById('custom-manage');
    var actionsEl = document.getElementById('fb-actions');
    var editBtn = document.getElementById('custom-edit-btn');
    var deleteBtn = document.getElementById('custom-delete-btn');
    var uploadDocBtn = document.getElementById('custom-upload-doc');
    var uploadImgBtn = document.getElementById('custom-upload-img');
    var docInput = document.getElementById('custom-doc-input');
    var imgInput = document.getElementById('custom-img-input');
    var mkdirBtn = document.getElementById('custom-mkdir-btn');
    var msgEl = document.getElementById('custom-upload-msg');
    var loadingEl = document.getElementById('custom-loading');
    var tableEl = document.getElementById('custom-table');
    var tbodyEl = document.getElementById('custom-tbody');
    var emptyEl = document.getElementById('custom-empty');
    var pathEl = document.getElementById('fb-path');
    var countEl = document.getElementById('fb-count');
    var filesEl = document.getElementById('custom-files');
    var readingEl = document.getElementById('custom-reading');
    var contentEl = document.getElementById('reader-content');
    var filenameEl = document.getElementById('reader-filename');
    var backBtn = document.getElementById('custom-back-btn');

    var editModal = document.getElementById('custom-modal');
    var editModalTitle = document.getElementById('custom-modal-title-input');
    var editModalDesc = document.getElementById('custom-modal-desc-input');
    var editModalHint = document.getElementById('custom-modal-hint');
    var editModalConfirm = document.getElementById('custom-modal-confirm');
    var editModalCancel = document.getElementById('custom-modal-cancel');

    var mkdirModal = document.getElementById('custom-mkdir-modal');
    var mkdirInput = document.getElementById('custom-mkdir-input');
    var mkdirHint = document.getElementById('custom-mkdir-hint');
    var mkdirConfirm = document.getElementById('custom-mkdir-confirm');
    var mkdirCancel = document.getElementById('custom-mkdir-cancel');

    var pageId = null;
    var page = null;
    var currentPath = '';
    var isLocal = false;
    var msgTimer = null;

    function getQueryParam(name) {
        var m = location.search.match(new RegExp('[?&]' + name + '=([^&]*)'));
        return m ? decodeURIComponent(m[1]) : null;
    }

    function show(el) { if (el) el.style.display = ''; }
    function hide(el) { if (el) el.style.display = 'none'; }

    function escHtml(s) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(s));
        return div.innerHTML;
    }

    function humanSize(bytes) {
        if (bytes === 0) return '-';
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var i = 0;
        var size = bytes;
        while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
        return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
    }

    function fmtDate(ts) {
        var d = new Date(ts * 1000);
        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function showError(msg) {
        errorEl.textContent = msg;
        show(errorEl);
        hide(appEl);
    }

    function setMsg(text, isErr) {
        clearTimeout(msgTimer);
        msgEl.textContent = text;
        msgEl.className = 'fb-msg ' + (isErr ? 'fb-msg-err' : 'fb-msg-ok');
        show(msgEl);
        msgTimer = setTimeout(function () { hide(msgEl); }, 4000);
    }

    // ===== marked 渲染器：相对路径加前缀 =====
    function setupRenderer() {
        var base = 'custom/' + pageId + '/';
        function resolveUrl(href) {
            if (!href) return href;
            if (/^(https?:)?\/\//i.test(href)) return href;
            if (href.indexOf('data:') === 0) return href;
            if (href.charAt(0) === '#' || href.charAt(0) === '/') return href;
            return '/' + base + href;
        }
        marked.use({
            renderer: {
                image: function (token) {
                    return marked.Renderer.prototype.image.call(this, Object.assign({}, token, { href: resolveUrl(token.href) }));
                },
                link: function (token) {
                    return marked.Renderer.prototype.link.call(this, Object.assign({}, token, { href: resolveUrl(token.href) }));
                }
            }
        });
    }

    function renderHtml(el, mdText) {
        el.innerHTML = marked.parse(mdText);
        el.querySelectorAll('pre code').forEach(function (block) {
            hljs.highlightElement(block);
        });
    }

    // ===== 页面元数据 =====
    function renderDesc() {
        if (page && page.description) {
            renderHtml(descEl, page.description);
        } else {
            descEl.innerHTML = '';
        }
    }

    // ===== 文件浏览器 =====
    function renderBreadcrumb() {
        var parts = currentPath ? currentPath.split('/') : [];
        var html = '<a href="#" class="fb-bread-home" data-nav="">' + escHtml(page ? page.title : '根目录') + '</a>';
        var acc = '';
        parts.forEach(function (p, i) {
            if (!p) return;
            acc += (acc ? '/' : '') + p;
            html += '<span class="fb-bread-sep">/</span>';
            if (i === parts.length - 1) {
                html += '<span class="fb-bread-current">' + escHtml(p) + '</span>';
            } else {
                html += '<a href="#" class="fb-bread-link" data-nav="' + escHtml(acc) + '">' + escHtml(p) + '</a>';
            }
        });
        return html;
    }

    function getIconHtml(name, isDir) {
        if (isDir) return '<i class="fa-folder-icon">📁</i>';
        var ext = name.split('.').pop().toLowerCase();
        if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].indexOf(ext) >= 0) return '<i class="fa-img-icon">🖼️</i>';
        if (ext === 'md') return '<i class="fa-md-icon">📝</i>';
        return '<i class="fa-file-icon">📄</i>';
    }

    function buildRow(entry) {
        var tr = document.createElement('tr');
        var isDir = entry.type === 'dir';

        var iconTd = document.createElement('td');
        iconTd.className = 'fb-col-icon';
        iconTd.innerHTML = getIconHtml(entry.name, isDir);
        tr.appendChild(iconTd);

        var nameTd = document.createElement('td');
        nameTd.className = 'fb-col-name';
        if (isDir) {
            var dirLink = document.createElement('a');
            dirLink.href = '#';
            dirLink.className = 'fb-link fb-link-dir';
            dirLink.textContent = entry.name;
            dirLink.addEventListener('click', function (e) {
                e.preventDefault();
                navigate(entry.name);
            });
            nameTd.appendChild(dirLink);
        } else {
            var rel = currentPath ? currentPath + '/' + entry.name : entry.name;
            var isMd = entry.name.toLowerCase().endsWith('.md');
            if (isMd) {
                var mdLink = document.createElement('a');
                mdLink.href = '#';
                mdLink.className = 'fb-link fb-link-file';
                mdLink.textContent = entry.name;
                mdLink.addEventListener('click', function (e) {
                    e.preventDefault();
                    openDoc(rel);
                });
                nameTd.appendChild(mdLink);
            } else {
                var fileLink = document.createElement('a');
                fileLink.href = '/custom/' + encodeURIComponent(pageId) + '/' + rel;
                fileLink.className = 'fb-link fb-link-file';
                fileLink.target = '_blank';
                fileLink.textContent = entry.name;
                nameTd.appendChild(fileLink);
            }
        }
        tr.appendChild(nameTd);

        var sizeTd = document.createElement('td');
        sizeTd.className = 'fb-col-size';
        sizeTd.textContent = isDir ? '-' : humanSize(entry.size);
        tr.appendChild(sizeTd);

        var dateTd = document.createElement('td');
        dateTd.className = 'fb-col-date';
        dateTd.textContent = fmtDate(entry.mtime);
        tr.appendChild(dateTd);

        var opTd = document.createElement('td');
        opTd.className = 'fb-col-op';
        var delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'fb-rename-btn';
        delBtn.title = '删除';
        delBtn.innerHTML = '&#10005;';
        delBtn.disabled = !isLocal;
        delBtn.addEventListener('click', function () {
            doDelete(entry.name, isDir);
        });
        opTd.appendChild(delBtn);
        tr.appendChild(opTd);

        return tr;
    }

    function loadTree() {
        show(loadingEl);
        hide(tableEl);
        hide(emptyEl);
        tbodyEl.innerHTML = '';

        var url = '/api/pages/' + encodeURIComponent(pageId) + '/tree'
            + (currentPath ? '?path=' + encodeURIComponent(currentPath) : '');
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                hide(loadingEl);
                pathEl.innerHTML = renderBreadcrumb();
                var entries = data.entries;
                if (!entries || entries.length === 0) {
                    show(emptyEl);
                    countEl.textContent = '0 项';
                    return;
                }
                var dirs = entries.filter(function (e) { return e.type === 'dir'; });
                var files = entries.filter(function (e) { return e.type === 'file'; });
                dirs.forEach(function (d) { tbodyEl.appendChild(buildRow(d)); });
                files.forEach(function (f) { tbodyEl.appendChild(buildRow(f)); });
                show(tableEl);
                countEl.textContent = entries.length + ' 项';
            })
            .catch(function (err) {
                hide(loadingEl);
                show(emptyEl);
                emptyEl.textContent = '加载失败: ' + err.message;
            });
    }

    function navigate(dir) {
        currentPath = currentPath ? currentPath + '/' + dir : dir;
        loadTree();
    }

    pathEl.addEventListener('click', function (e) {
        var link = e.target.closest('[data-nav]');
        if (!link) return;
        e.preventDefault();
        currentPath = link.getAttribute('data-nav');
        loadTree();
    });

    function applyLocal() {
        if (isLocal) {
            show(manageEl);
            show(actionsEl);
        }
    }

    // ===== 上传 =====
    function uploadFiles(input) {
        var files = input.files;
        if (!files || files.length === 0) return;
        var fd = new FormData();
        if (currentPath) fd.append('path', currentPath);
        for (var i = 0; i < files.length; i++) {
            fd.append('file', files[i]);
        }
        uploadDocBtn.disabled = true;
        uploadImgBtn.disabled = true;
        setMsg('正在上传 ' + files.length + ' 个文件...', false);
        fetch('/api/pages/' + encodeURIComponent(pageId) + '/upload', { method: 'POST', body: fd })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    setMsg('上传成功: ' + res.data.names.join(', '), false);
                    loadTree();
                } else {
                    setMsg('上传失败: ' + (res.data.error || '未知错误'), true);
                }
            })
            .catch(function () { setMsg('上传失败: 网络错误', true); })
            .finally(function () {
                uploadDocBtn.disabled = false;
                uploadImgBtn.disabled = false;
            });
        input.value = '';
    }

    uploadDocBtn.addEventListener('click', function () { docInput.click(); });
    uploadImgBtn.addEventListener('click', function () { imgInput.click(); });
    docInput.addEventListener('change', function () { uploadFiles(docInput); });
    imgInput.addEventListener('change', function () { uploadFiles(imgInput); });

    // ===== 新建文件夹 =====
    function openMkdir() {
        mkdirInput.value = '';
        mkdirHint.textContent = '';
        mkdirHint.className = 'fb-modal-hint';
        show(mkdirModal);
        mkdirInput.focus();
    }
    function closeMkdir() { hide(mkdirModal); }

    function doMkdir() {
        var name = mkdirInput.value.trim();
        if (!name) {
            mkdirHint.textContent = '请输入文件夹名称';
            mkdirHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        mkdirConfirm.disabled = true;
        mkdirConfirm.textContent = '创建中...';
        fetch('/api/pages/' + encodeURIComponent(pageId) + '/mkdir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentPath, name: name })
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    closeMkdir();
                    setMsg('已创建文件夹', false);
                    loadTree();
                } else {
                    mkdirHint.textContent = res.data.error || '创建失败';
                    mkdirHint.className = 'fb-modal-hint fb-modal-hint-err';
                }
            })
            .catch(function () {
                mkdirHint.textContent = '网络错误';
                mkdirHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .finally(function () {
                mkdirConfirm.disabled = false;
                mkdirConfirm.textContent = '创建';
            });
    }

    mkdirBtn.addEventListener('click', openMkdir);
    mkdirConfirm.addEventListener('click', doMkdir);
    mkdirCancel.addEventListener('click', closeMkdir);
    mkdirInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); doMkdir(); }
        if (e.key === 'Escape') { closeMkdir(); }
    });
    mkdirModal.addEventListener('click', function (e) {
        if (e.target === mkdirModal) closeMkdir();
    });

    // ===== 删除 =====
    function doDelete(name, isDir) {
        var rel = currentPath ? currentPath + '/' + name : name;
        if (!confirm('确定删除' + (isDir ? '文件夹' : '文件') + '「' + name + '」？' + (isDir ? '其内容将被一并删除，' : '') + '此操作不可恢复。')) return;
        fetch('/api/pages/' + encodeURIComponent(pageId) + '/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: rel })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success) {
                    setMsg('已删除', false);
                    loadTree();
                } else {
                    setMsg('删除失败: ' + (d.error || '未知错误'), true);
                }
            })
            .catch(function () { setMsg('删除失败: 网络错误', true); });
    }

    // ===== 阅读视图 =====
    function openDoc(rel) {
        hide(filesEl);
        show(readingEl);
        var name = rel.split('/').pop();
        filenameEl.textContent = name;
        contentEl.innerHTML = '<p>加载中...</p>';

        fetch('/custom/' + encodeURIComponent(pageId) + '/' + rel)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status + (r.status === 404 ? ' (文件未找到)' : ''));
                return r.text();
            })
            .then(function (mdText) {
                renderHtml(contentEl, mdText);
            })
            .catch(function (err) {
                contentEl.innerHTML = '<p style="color:#c00;">加载文件失败: ' + err.message + '</p>';
            });
    }

    backBtn.addEventListener('click', function () {
        hide(readingEl);
        show(filesEl);
    });

    // ===== 编辑页面 =====
    function openEditModal() {
        editModalTitle.value = page.title;
        editModalDesc.value = page.description || '';
        editModalHint.textContent = '';
        editModalHint.className = 'fb-modal-hint';
        show(editModal);
        editModalTitle.focus();
    }
    function closeEditModal() { hide(editModal); }

    function savePage() {
        var title = editModalTitle.value.trim();
        var desc = editModalDesc.value.trim();
        if (!title) {
            editModalHint.textContent = '标题不能为空';
            editModalHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        editModalConfirm.disabled = true;
        editModalConfirm.textContent = '保存中...';
        fetch('/api/pages/' + encodeURIComponent(pageId), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title, description: desc })
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    closeEditModal();
                    page = res.data;
                    document.title = page.title + ' - 本地文件站';
                    titleEl.textContent = page.title;
                    renderDesc();
                    setMsg('已保存页面修改', false);
                } else {
                    editModalHint.textContent = res.data.error || '保存失败';
                    editModalHint.className = 'fb-modal-hint fb-modal-hint-err';
                }
            })
            .catch(function () {
                editModalHint.textContent = '网络错误';
                editModalHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .finally(function () {
                editModalConfirm.disabled = false;
                editModalConfirm.textContent = '保存';
            });
    }

    editBtn.addEventListener('click', openEditModal);
    editModalConfirm.addEventListener('click', savePage);
    editModalCancel.addEventListener('click', closeEditModal);
    editModal.addEventListener('click', function (e) {
        if (e.target === editModal) closeEditModal();
    });

    // ===== 删除页面 =====
    deleteBtn.addEventListener('click', function () {
        if (!confirm('确定删除页面「' + page.title + '」及其所有文件？此操作不可恢复。')) return;
        deleteBtn.disabled = true;
        fetch('/api/pages/' + encodeURIComponent(pageId), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success) location.href = '/';
                else { alert('删除失败: ' + (d.error || '未知错误')); deleteBtn.disabled = false; }
            })
            .catch(function () { alert('删除失败: 网络错误'); deleteBtn.disabled = false; });
    });

    // ===== init =====
    function init() {
        pageId = getQueryParam('id');
        if (!pageId) { showError('缺少页面 id 参数'); return; }
        setupRenderer();

        fetch('/api/local')
            .then(function (r) { return r.json(); })
            .then(function (d) { isLocal = !!d.local; applyLocal(); })
            .catch(function () { isLocal = false; applyLocal(); });

        fetch('/api/pages')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (pages) {
                page = pages.filter(function (p) { return p.id === pageId; })[0];
                if (!page) { showError('页面不存在或已被删除'); return; }
                document.title = page.title + ' - 本地文件站';
                titleEl.textContent = page.title;
                renderDesc();
                show(appEl);
                loadTree();
            })
            .catch(function (err) { showError('加载页面失败: ' + err.message); });
    }

    init();
})();
