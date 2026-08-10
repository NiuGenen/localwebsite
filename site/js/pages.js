(function () {
    var gridEl = document.getElementById('page-grid');
    var emptyEl = document.getElementById('page-empty');
    var loadingEl = document.getElementById('page-loading');
    var createBtn = document.getElementById('page-create-btn');
    var modal = document.getElementById('page-modal');
    var modalTitle = document.getElementById('page-modal-title');
    var modalDesc = document.getElementById('page-modal-desc');
    var modalHint = document.getElementById('page-modal-hint');
    var modalConfirm = document.getElementById('page-modal-confirm');
    var modalCancel = document.getElementById('page-modal-cancel');

    var isLocal = false;

    function snippet(text) {
        var t = (text || '').replace(/[#*_`>~\[\]()!-]/g, ' ').replace(/\s+/g, ' ').trim();
        return t.length > 80 ? t.slice(0, 80) + '…' : t;
    }

    function updatePinBtn(btn, pinned) {
        btn.textContent = pinned ? '从首页取消' : '添加到首页';
        btn.classList.toggle('pinned', !!pinned);
        btn.title = pinned ? '将该页面从首页移除' : '将该页面添加到首页';
    }

    function makePinBtn(page) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'page-pin-btn' + (page.pinned ? ' pinned' : '');
        updatePinBtn(btn, !!page.pinned);
        btn.addEventListener('click', function () {
            btn.disabled = true;
            fetch('/api/pages/' + encodeURIComponent(page.id), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pinned: !page.pinned })
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.id) {
                        page.pinned = !!d.pinned;
                        updatePinBtn(btn, page.pinned);
                    } else {
                        alert('操作失败: ' + (d.error || '未知错误'));
                    }
                })
                .catch(function () { alert('网络错误'); })
                .finally(function () { btn.disabled = false; });
        });
        return btn;
    }

    function loadPages() {
        loadingEl.style.display = '';
        emptyEl.style.display = 'none';
        gridEl.innerHTML = '';
        fetch('/api/pages')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (pages) {
                loadingEl.style.display = 'none';
                if (!pages || pages.length === 0) {
                    emptyEl.style.display = '';
                    return;
                }
                pages.forEach(function (p) {
                    var wrap = document.createElement('div');
                    wrap.className = 'page-entry';

                    var a = document.createElement('a');
                    a.href = '/custom.html?id=' + encodeURIComponent(p.id);
                    a.className = 'page-entry-link';
                    var title = document.createElement('div');
                    title.className = 'page-entry-title';
                    title.textContent = p.title;
                    var desc = document.createElement('div');
                    desc.className = 'page-entry-desc';
                    desc.textContent = snippet(p.description) || '（无简介）';
                    a.appendChild(title);
                    a.appendChild(desc);
                    wrap.appendChild(a);

                    if (isLocal) {
                        wrap.appendChild(makePinBtn(p));
                    }

                    gridEl.appendChild(wrap);
                });
            })
            .catch(function (err) {
                loadingEl.style.display = 'none';
                gridEl.innerHTML = '<p style="color:#c00;">加载自定义页面失败: ' + err.message + '</p>';
            });
    }

    fetch('/api/local')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            isLocal = !!d.local;
            if (isLocal) createBtn.style.display = '';
        })
        .catch(function () {});

    function openModal() {
        modalTitle.value = '';
        modalDesc.value = '';
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }
    function closeModal() { modal.style.display = 'none'; }

    function doCreate() {
        var title = modalTitle.value.trim();
        var desc = modalDesc.value.trim();
        if (!title) {
            modalHint.textContent = '标题不能为空';
            modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        modalConfirm.disabled = true;
        modalConfirm.textContent = '创建中...';
        fetch('/api/pages', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title, description: desc })
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                if (res.ok) {
                    location.href = '/custom.html?id=' + encodeURIComponent(res.data.id);
                } else {
                    modalHint.textContent = res.data.error || '创建失败';
                    modalHint.className = 'fb-modal-hint fb-modal-hint-err';
                }
            })
            .catch(function () {
                modalHint.textContent = '网络错误';
                modalHint.className = 'fb-modal-hint fb-modal-hint-err';
            })
            .finally(function () {
                modalConfirm.disabled = false;
                modalConfirm.textContent = '创建';
            });
    }

    createBtn.addEventListener('click', openModal);
    modalConfirm.addEventListener('click', doCreate);
    modalCancel.addEventListener('click', closeModal);
    modalTitle.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); doCreate(); }
        if (e.key === 'Escape') { closeModal(); }
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    loadPages();
})();
