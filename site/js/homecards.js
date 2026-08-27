(function () {
    var container = document.getElementById('homecards');
    var headEl = document.getElementById('homecards-head');
    var createBtn = document.getElementById('homecard-create-btn');
    var editBtn = document.getElementById('homecard-edit-btn');
    var modal = document.getElementById('homecard-modal');
    var modalHead = document.getElementById('homecard-modal-head');
    var modalTitle = document.getElementById('homecard-modal-title');
    var modalUrl = document.getElementById('homecard-modal-url');
    var modalDesc = document.getElementById('homecard-modal-desc');
    var modalHint = document.getElementById('homecard-modal-hint');
    var modalConfirm = document.getElementById('homecard-modal-confirm');
    var modalCancel = document.getElementById('homecard-modal-cancel');

    if (!container || !headEl || !modal) return;

    var links = [];
    var isLocal = false;
    var editMode = false;
    var editingId = null;

    function setHint(msg) {
        modalHint.textContent = msg || '';
        modalHint.className = 'fb-modal-hint' + (msg ? ' fb-modal-hint-err' : '');
    }

    function render() {
        container.innerHTML = '';
        links.forEach(function (l) {
            var card = document.createElement('div');
            card.className = 'card card-linkcard';

            var icon = document.createElement('div');
            icon.className = 'card-icon';
            icon.textContent = '🌐';

            var h3 = document.createElement('h3');
            h3.textContent = l.title;

            var para = document.createElement('p');
            para.textContent = l.description || '（无简介）';

            var btn = document.createElement('a');
            btn.href = l.url;
            btn.target = '_blank';
            btn.rel = 'noopener noreferrer';
            btn.className = 'btn';
            btn.textContent = '进入网页';

            card.appendChild(icon);
            card.appendChild(h3);
            card.appendChild(para);
            card.appendChild(btn);

            if (editMode) {
                var actions = document.createElement('div');
                actions.className = 'homecard-actions';

                var actEditBtn = document.createElement('button');
                actEditBtn.type = 'button';
                actEditBtn.className = 'btn btn-sm homecard-edit-btn';
                actEditBtn.textContent = '编辑';
                actEditBtn.addEventListener('click', function () { openEdit(l); });

                var actDelBtn = document.createElement('button');
                actDelBtn.type = 'button';
                actDelBtn.className = 'btn btn-sm btn-danger homecard-del-btn';
                actDelBtn.textContent = '删除';
                actDelBtn.addEventListener('click', function () { doDelete(l); });

                actions.appendChild(actEditBtn);
                actions.appendChild(actDelBtn);
                card.appendChild(actions);
            }

            container.appendChild(card);
        });

        var hasCards = links.length > 0;
        headEl.style.display = (hasCards || isLocal) ? 'flex' : 'none';
        if (isLocal && createBtn) createBtn.style.display = hasCards || !editMode ? '' : 'none';
    }

    function reload() {
        return fetch('/api/links')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                links = data || [];
                render();
            })
            .catch(function () {});
    }

    function openModal() {
        editingId = null;
        modalHead.textContent = '添加网页卡片';
        modalConfirm.textContent = '添加';
        modalTitle.value = '';
        modalUrl.value = '';
        modalDesc.value = '';
        setHint('');
        modal.style.display = 'flex';
        modalTitle.focus();
    }

    function closeModal() { modal.style.display = 'none'; }

    function openEdit(l) {
        editingId = l.id;
        modalHead.textContent = '编辑网页卡片';
        modalConfirm.textContent = '保存';
        modalTitle.value = l.title;
        modalUrl.value = l.url;
        modalDesc.value = l.description;
        setHint('');
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
        var url = modalUrl.value.trim();
        var desc = modalDesc.value.trim();
        if (!title) {
            setHint('标题不能为空');
            modalTitle.focus();
            return;
        }
        if (!url) {
            setHint('目标网页链接不能为空');
            modalUrl.focus();
            return;
        }
        modalConfirm.disabled = true;
        modalConfirm.textContent = '保存中...';
        var api = '/api/links' + (editingId ? '/' + encodeURIComponent(editingId) : '');
        var method = editingId ? 'PUT' : 'POST';
        fetch(api, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title, url: url, description: desc })
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    closeModal();
                    return reload();
                }
                setHint(res.data.error || '保存失败');
            })
            .catch(function () { setHint('网络错误'); })
            .finally(function () {
                modalConfirm.disabled = false;
                modalConfirm.textContent = editingId ? '保存' : '添加';
            });
    }

    function doDelete(l) {
        if (!confirm('确定删除卡片「' + l.title + '」？此操作不可恢复。')) return;
        fetch('/api/links/' + encodeURIComponent(l.id), { method: 'DELETE' })
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

    if (createBtn) createBtn.addEventListener('click', openModal);
    if (editBtn) editBtn.addEventListener('click', toggleEditMode);
    modalConfirm.addEventListener('click', doSave);
    modalCancel.addEventListener('click', closeModal);
    modalTitle.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); doSave(); }
        if (e.key === 'Escape') { closeModal(); }
    });
    modalUrl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); doSave(); }
        if (e.key === 'Escape') { closeModal(); }
    });
    modalDesc.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closeModal(); }
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    fetch('/api/local')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            isLocal = !!d.local;
            if (isLocal) {
                createBtn.style.display = '';
                editBtn.style.display = '';
            }
            reload();
        })
        .catch(function () { reload(); });
})();
