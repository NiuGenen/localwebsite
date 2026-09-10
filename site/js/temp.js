(function () {
    var listEl = document.getElementById('temp-list');
    var loadingEl = document.getElementById('temp-loading');
    var emptyEl = document.getElementById('temp-empty');
    var errorEl = document.getElementById('temp-error');
    var createBtn = document.getElementById('temp-create-btn');
    var editBtn = document.getElementById('temp-edit-btn');
    var modal = document.getElementById('temp-modal');
    var modalHead = document.getElementById('temp-modal-head');
    var modalTitle = document.getElementById('temp-modal-title');
    var modalContent = document.getElementById('temp-modal-content');
    var modalHint = document.getElementById('temp-modal-hint');
    var modalConfirm = document.getElementById('temp-modal-confirm');
    var modalCancel = document.getElementById('temp-modal-cancel');

    var notes = [];
    var editMode = false;
    var editingId = null;

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function fmtDate(ts) {
        if (!ts) return '';
        var d = new Date(ts * 1000);
        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function render() {
        listEl.innerHTML = '';
        if (notes.length === 0) {
            emptyEl.style.display = '';
            return;
        }
        emptyEl.style.display = 'none';

        notes.forEach(function (n) {
            var item = document.createElement('div');
            item.className = 'temp-item';

            var h3 = document.createElement('h3');
            h3.textContent = n.title;

            var meta = document.createElement('div');
            meta.className = 'temp-meta';
            meta.textContent = fmtDate(n.created);

            var content = document.createElement('div');
            content.className = 'temp-content';
            content.textContent = n.content;

            item.appendChild(h3);
            item.appendChild(meta);
            item.appendChild(content);

            if (editMode) {
                var actions = document.createElement('div');
                actions.className = 'temp-actions';

                var actEdit = document.createElement('button');
                actEdit.type = 'button';
                actEdit.className = 'btn btn-sm temp-edit-btn';
                actEdit.textContent = '编辑';
                actEdit.addEventListener('click', function () { openEdit(n); });

                var actDel = document.createElement('button');
                actDel.type = 'button';
                actDel.className = 'btn btn-sm btn-danger temp-del-btn';
                actDel.textContent = '删除';
                actDel.addEventListener('click', function () { doDelete(n); });

                actions.appendChild(actEdit);
                actions.appendChild(actDel);
                item.appendChild(actions);
            }

            listEl.appendChild(item);
        });
    }

    function reload() {
        return fetch('/api/temp')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                notes = data || [];
                notes.sort(function (a, b) { return (b.created || 0) - (a.created || 0); });
                loadingEl.style.display = 'none';
                render();
                setError('');
            })
            .catch(function (e) {
                loadingEl.style.display = 'none';
                setError('加载失败: ' + e.message);
            });
    }

    function openModal() {
        editingId = null;
        modalHead.textContent = '新增内容';
        modalConfirm.textContent = '确定';
        modalTitle.value = '';
        modalContent.value = '';
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }

    function openEdit(n) {
        editingId = n.id;
        modalHead.textContent = '编辑内容';
        modalConfirm.textContent = '保存';
        modalTitle.value = n.title;
        modalContent.value = n.content;
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }

    function closeModal() { modal.style.display = 'none'; }

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
            modalHint.textContent = '文本内容不能为空';
            modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            modalContent.focus();
            return;
        }
        modalConfirm.disabled = true;
        modalConfirm.textContent = '保存中...';
        var url = '/api/temp' + (editingId ? '/' + encodeURIComponent(editingId) : '');
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
                modalConfirm.textContent = editingId ? '保存' : '确定';
            });
    }

    function doDelete(n) {
        if (!confirm('确定删除「' + n.title + '」？此操作不可恢复。')) return;
        fetch('/api/temp/' + encodeURIComponent(n.id), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success) reload();
                else alert('删除失败: ' + (d.error || '未知错误'));
            })
            .catch(function () { alert('删除失败: 网络错误'); });
    }

    createBtn.addEventListener('click', openModal);
    editBtn.addEventListener('click', toggleEditMode);
    modalConfirm.addEventListener('click', doSave);
    modalCancel.addEventListener('click', closeModal);
    modalTitle.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModal();
    });
    modalContent.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModal();
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    fetch('/api/local')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.local) editBtn.style.display = '';
        })
        .catch(function () {});

    reload();
})();
