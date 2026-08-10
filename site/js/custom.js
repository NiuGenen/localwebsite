(function () {
    var appEl = document.getElementById('custom-app');
    var errorEl = document.getElementById('custom-error');
    var titleEl = document.getElementById('custom-title');
    var descEl = document.getElementById('custom-desc');
    var manageEl = document.getElementById('custom-manage');
    var uploadEl = document.getElementById('custom-upload');
    var editBtn = document.getElementById('custom-edit-btn');
    var deleteBtn = document.getElementById('custom-delete-btn');
    var uploadBtn = document.getElementById('custom-upload-btn');
    var fileInput = document.getElementById('custom-file-input');
    var uploadMsgEl = document.getElementById('custom-upload-msg');
    var fileListEl = document.getElementById('custom-file-list');
    var emptyEl = document.getElementById('custom-empty');
    var loadingEl = document.getElementById('custom-loading');
    var filesEl = document.getElementById('custom-files');
    var readingEl = document.getElementById('custom-reading');
    var contentEl = document.getElementById('reader-content');
    var filenameEl = document.getElementById('reader-filename');
    var backBtn = document.getElementById('custom-back-btn');

    var modal = document.getElementById('custom-modal');
    var modalTitle = document.getElementById('custom-modal-title');
    var modalTitleInput = document.getElementById('custom-modal-title-input');
    var modalDescInput = document.getElementById('custom-modal-desc-input');
    var modalHint = document.getElementById('custom-modal-hint');
    var modalConfirm = document.getElementById('custom-modal-confirm');
    var modalCancel = document.getElementById('custom-modal-cancel');

    var pageId = null;
    var page = null;
    var isLocal = false;
    var msgTimer = null;

    function getQueryParam(name) {
        var m = location.search.match(new RegExp('[?&]' + name + '=([^&]*)'));
        return m ? decodeURIComponent(m[1]) : null;
    }

    function getFileName(path) {
        var parts = path.replace(/\\/g, '/').split('/');
        return parts[parts.length - 1] || path;
    }

    function show(el) { if (el) el.style.display = ''; }
    function hide(el) { if (el) el.style.display = 'none'; }

    function showError(msg) {
        errorEl.textContent = msg;
        show(errorEl);
        hide(appEl);
    }

    function setMsg(text, isErr) {
        clearTimeout(msgTimer);
        uploadMsgEl.textContent = text;
        uploadMsgEl.className = 'fb-msg ' + (isErr ? 'fb-msg-err' : 'fb-msg-ok');
        show(uploadMsgEl);
        msgTimer = setTimeout(function () { hide(uploadMsgEl); }, 4000);
    }

    function renderDesc() {
        if (page && page.description) {
            descEl.innerHTML = marked.parse(page.description);
        } else {
            descEl.innerHTML = '';
        }
        descEl.querySelectorAll('pre code').forEach(function (block) {
            hljs.highlightElement(block);
        });
    }

    function renderFiles(files) {
        fileListEl.innerHTML = '';
        hide(loadingEl);
        if (!files || files.length === 0) {
            show(emptyEl);
            return;
        }
        hide(emptyEl);
        files.forEach(function (f) {
            var li = document.createElement('li');
            var link = document.createElement('a');
            link.href = '#';
            link.className = 'md-file-link';
            link.textContent = f.name;
            link.addEventListener('click', function (e) {
                e.preventDefault();
                openDoc(f.name);
            });
            li.appendChild(link);
            fileListEl.appendChild(li);
        });
    }

    function loadFiles() {
        hide(emptyEl);
        show(loadingEl);
        fetch('/api/pages/' + encodeURIComponent(pageId) + '/files')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                renderFiles(data.files);
            })
            .catch(function (err) {
                hide(loadingEl);
                show(emptyEl);
                emptyEl.textContent = '加载文件清单失败: ' + err.message;
            });
    }

    function init() {
        pageId = getQueryParam('id');
        if (!pageId) {
            showError('缺少页面 id 参数');
            return;
        }

        // local check first (parallel to page load)
        fetch('/api/local').then(function (r) { return r.json(); })
            .then(function (d) { isLocal = !!d.local; applyLocal(); })
            .catch(function () { isLocal = false; applyLocal(); });

        fetch('/api/pages')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (pages) {
                page = pages.filter(function (p) { return p.id === pageId; })[0];
                if (!page) {
                    showError('页面不存在或已被删除');
                    return;
                }
                document.title = page.title + ' - 本地文件站';
                titleEl.textContent = page.title;
                renderDesc();
                show(appEl);
                loadFiles();
            })
            .catch(function (err) {
                showError('加载页面失败: ' + err.message);
            });
    }

    function applyLocal() {
        if (isLocal) {
            show(manageEl);
            show(uploadEl);
        }
    }

    // ===== 打开文档 =====
    function openDoc(name) {
        var path = 'custom/' + pageId + '/' + name;
        hide(filesEl);
        show(readingEl);
        filenameEl.textContent = name;

        fetch('/' + path)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status + (r.status === 404 ? ' (文件未找到)' : ''));
                return r.text();
            })
            .then(function (mdText) {
                marked.setOptions({
                    highlight: function (code, lang) {
                        if (lang && hljs.getLanguage(lang)) {
                            try { return hljs.highlight(code, { language: lang }).value; } catch (e) {}
                        }
                        try { return hljs.highlightAuto(code).value; } catch (e) {}
                        return code;
                    },
                    langPrefix: 'hljs language-'
                });
                contentEl.innerHTML = marked.parse(mdText);
                contentEl.querySelectorAll('pre code').forEach(function (block) {
                    hljs.highlightElement(block);
                });
            })
            .catch(function (err) {
                contentEl.innerHTML = '<p style="color:#c00;">加载文件失败: ' + err.message + '</p>';
            });
    }

    backBtn.addEventListener('click', function () {
        hide(readingEl);
        show(filesEl);
    });

    // ===== 上传 =====
    uploadBtn.addEventListener('click', function () {
        fileInput.click();
    });
    fileInput.addEventListener('change', function () {
        var files = fileInput.files;
        if (!files || files.length === 0) return;
        var fd = new FormData();
        for (var i = 0; i < files.length; i++) {
            fd.append('file', files[i]);
        }
        uploadBtn.disabled = true;
        setMsg('正在上传 ' + files.length + ' 个文件...', false);
        fetch('/api/pages/' + encodeURIComponent(pageId) + '/upload', { method: 'POST', body: fd })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    setMsg('上传成功: ' + res.data.names.join(', '), false);
                    loadFiles();
                } else {
                    setMsg('上传失败: ' + (res.data.error || '未知错误'), true);
                }
            })
            .catch(function () {
                setMsg('上传失败: 网络错误', true);
            })
            .finally(function () {
                uploadBtn.disabled = false;
            });
        fileInput.value = '';
    });

    // ===== 编辑 =====
    function openEditModal() {
        modalTitle.textContent = '编辑页面';
        modalTitleInput.value = page.title;
        modalDescInput.value = page.description || '';
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        show(modal);
        modalTitleInput.focus();
    }
    function closeModal() { hide(modal); }

    function savePage() {
        var title = modalTitleInput.value.trim();
        var desc = modalDescInput.value.trim();
        if (!title) {
            modalHint.textContent = '标题不能为空';
            modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        modalConfirm.disabled = true;
        modalConfirm.textContent = '保存中...';
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
                    closeModal();
                    page = res.data;
                    document.title = page.title + ' - 本地文件站';
                    titleEl.textContent = page.title;
                    renderDesc();
                    setMsg('已保存页面修改', false);
                } else {
                    modalHint.textContent = res.data.error || '保存失败';
                    modalHint.className = 'fb-modal-hint fb-modal-hint-err';
                }
            })
            .catch(function () {
                modalHint.textContent = '网络错误';
                modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .finally(function () {
                modalConfirm.disabled = false;
                modalConfirm.textContent = '保存';
            });
    }

    editBtn.addEventListener('click', openEditModal);
    modalConfirm.addEventListener('click', savePage);
    modalCancel.addEventListener('click', closeModal);
    modalTitleInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); savePage(); }
        if (e.key === 'Escape') { closeModal(); }
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    // ===== 删除 =====
    deleteBtn.addEventListener('click', function () {
        if (!confirm('确定删除页面「' + page.title + '」及其所有 markdown 文件？此操作不可恢复。')) return;
        deleteBtn.disabled = true;
        fetch('/api/pages/' + encodeURIComponent(pageId), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success) {
                    location.href = '/';
                } else {
                    alert('删除失败: ' + (d.error || '未知错误'));
                    deleteBtn.disabled = false;
                }
            })
            .catch(function () {
                alert('删除失败: 网络错误');
                deleteBtn.disabled = false;
            });
    });

    init();
})();
