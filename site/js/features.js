(function () {
    var gridEl = document.getElementById('features-grid');
    var loadingEl = document.getElementById('features-loading');
    var emptyEl = document.getElementById('features-empty');
    var errorEl = document.getElementById('features-error');
    var countEl = document.getElementById('features-count');
    var searchEl = document.getElementById('feature-search');
    var createBtn = document.getElementById('feature-create-btn');
    var editBtn = document.getElementById('feature-edit-btn');
    var modal = document.getElementById('feature-modal');
    var modalHead = document.getElementById('feature-modal-head');
    var modalTitle = document.getElementById('feature-modal-title');
    var modalContent = document.getElementById('feature-modal-content');
    var modalHint = document.getElementById('feature-modal-hint');
    var modalConfirm = document.getElementById('feature-modal-confirm');
    var modalCancel = document.getElementById('feature-modal-cancel');

    var features = [];
    var keyword = '';
    var searchTimer = null;
    var isLocal = false;
    var editMode = false;
    var editingId = null;

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function render() {
        gridEl.innerHTML = '';
        countEl.textContent = features.length + ' 项';

        if (keyword && features.length === 0) {
            gridEl.innerHTML = '<p class="features-empty">没有匹配「' + searchEl.value.trim() + '」的内容。</p>';
            return;
        }
        if (features.length === 0) {
            emptyEl.style.display = '';
            countEl.textContent = '';
            return;
        }
        emptyEl.style.display = 'none';

        features.forEach(function (f) {
            var card = document.createElement('div');
            card.className = 'card feature-card';

            var h3 = document.createElement('h3');
            h3.textContent = f.title;

            var content = document.createElement('div');
            content.className = 'feature-content';
            content.textContent = f.content;

            card.appendChild(h3);
            card.appendChild(content);

            if (editMode) {
                var actions = document.createElement('div');
                actions.className = 'feature-actions';

                var actEditBtn = document.createElement('button');
                actEditBtn.type = 'button';
                actEditBtn.className = 'btn btn-sm feature-edit-btn';
                actEditBtn.textContent = '编辑';
                actEditBtn.addEventListener('click', function () { openEdit(f); });

                var actDelBtn = document.createElement('button');
                actDelBtn.type = 'button';
                actDelBtn.className = 'btn btn-sm btn-danger feature-del-btn';
                actDelBtn.textContent = '删除';
                actDelBtn.addEventListener('click', function () { doDelete(f); });

                actions.appendChild(actEditBtn);
                actions.appendChild(actDelBtn);
                card.appendChild(actions);
            }

            gridEl.appendChild(card);
        });
    }

    function reload() {
        var url = '/api/features';
        if (keyword) url += '?q=' + encodeURIComponent(keyword);
        return fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                features = data || [];
                render();
                setError('');
            })
            .catch(function (e) {
                setError('加载功能列表失败: ' + e.message);
            });
    }

    function openModal() {
        editingId = null;
        modalHead.textContent = '创建功能';
        modalConfirm.textContent = '创建';
        modalTitle.value = '';
        modalContent.value = '';
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }
    function closeModal() { modal.style.display = 'none'; }

    function openEdit(f) {
        editingId = f.id;
        modalHead.textContent = '编辑功能';
        modalConfirm.textContent = '保存';
        modalTitle.value = f.title;
        modalContent.value = f.content;
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }

    function toggleEditMode() {
        editMode = !editMode;
        editBtn.textContent = editMode ? '完成编辑' : '编辑';
        render();
    }

    function doSave() {
        var title = modalTitle.value.trim();
        var content = modalContent.value.trim();
        if (!title) {
            modalHint.textContent = '标题不能为空';
            modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            modalTitle.focus();
            return;
        }
        if (!content) {
            modalHint.textContent = '内容不能为空';
            modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            modalContent.focus();
            return;
        }
        modalConfirm.disabled = true;
        modalConfirm.textContent = '保存中...';
        var url = '/api/features' + (editingId ? '/' + encodeURIComponent(editingId) : '');
        var method = editingId ? 'PUT' : 'POST';
        fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title, content: content })
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    closeModal();
                    return reload();
                }
                modalHint.textContent = res.data.error || '保存失败';
                modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .catch(function () {
                modalHint.textContent = '网络错误';
                modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .finally(function () {
                modalConfirm.disabled = false;
                modalConfirm.textContent = editingId ? '保存' : '创建';
            });
    }

    function doDelete(f) {
        if (!confirm('确定删除功能「' + f.title + '」？此操作不可恢复。')) return;
        fetch('/api/features/' + encodeURIComponent(f.id), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success) {
                    reload();
                } else {
                    alert('删除失败: ' + (d.error || '未知错误'));
                }
            })
            .catch(function () { alert('删除失败: 网络错误'); });
    }

    createBtn.addEventListener('click', openModal);
    editBtn.addEventListener('click', toggleEditMode);
    modalConfirm.addEventListener('click', doSave);
    modalCancel.addEventListener('click', closeModal);
    modalTitle.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); doSave(); }
        if (e.key === 'Escape') { closeModal(); }
    });
    modalContent.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closeModal(); }
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    searchEl.addEventListener('input', function () {
        keyword = searchEl.value.trim();
        clearTimeout(searchTimer);
        searchTimer = setTimeout(reload, 200);
    });

    fetch('/api/local')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            isLocal = !!d.local;
            if (isLocal) editBtn.style.display = '';
        })
        .catch(function () {});

    reload();
})();
