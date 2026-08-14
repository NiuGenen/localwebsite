(function () {
    var gridEl = document.getElementById('features-grid');
    var loadingEl = document.getElementById('features-loading');
    var emptyEl = document.getElementById('features-empty');
    var errorEl = document.getElementById('features-error');
    var countEl = document.getElementById('features-count');
    var searchEl = document.getElementById('feature-search');
    var createBtn = document.getElementById('feature-create-btn');
    var modal = document.getElementById('feature-modal');
    var modalTitle = document.getElementById('feature-modal-title');
    var modalContent = document.getElementById('feature-modal-content');
    var modalHint = document.getElementById('feature-modal-hint');
    var modalConfirm = document.getElementById('feature-modal-confirm');
    var modalCancel = document.getElementById('feature-modal-cancel');

    var features = [];
    var keyword = '';

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function matches(item, kw) {
        if (!kw) return true;
        return (item.title || '').toLowerCase().indexOf(kw) !== -1 ||
               (item.content || '').toLowerCase().indexOf(kw) !== -1;
    }

    function render() {
        gridEl.innerHTML = '';
        var kw = keyword.toLowerCase().trim();
        var visible = features.filter(function (f) { return matches(f, kw); });
        countEl.textContent = visible.length + ' / ' + features.length + ' 项';

        if (features.length === 0) {
            emptyEl.style.display = '';
            countEl.textContent = '';
            return;
        }
        emptyEl.style.display = 'none';
        if (visible.length === 0) {
            gridEl.innerHTML = '<p class="features-empty">没有匹配「' + searchEl.value + '」的内容。</p>';
            return;
        }

        visible.forEach(function (f) {
            var card = document.createElement('div');
            card.className = 'card feature-card';

            var h3 = document.createElement('h3');
            h3.textContent = f.title;

            var content = document.createElement('div');
            content.className = 'feature-content';
            content.textContent = f.content;

            card.appendChild(h3);
            card.appendChild(content);
            gridEl.appendChild(card);
        });
    }

    function reload() {
        return fetch('/api/features')
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
        modalTitle.value = '';
        modalContent.value = '';
        modalHint.textContent = '';
        modalHint.className = 'fb-modal-hint';
        modal.style.display = 'flex';
        modalTitle.focus();
    }
    function closeModal() { modal.style.display = 'none'; }

    function doCreate() {
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
        modalConfirm.textContent = '创建中...';
        fetch('/api/features', {
            method: 'POST',
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
                modalHint.textContent = res.data.error || '创建失败';
                modalHint.className = 'fb-modal-hint fb-modal-hint-err';
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
    modalContent.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closeModal(); }
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    searchEl.addEventListener('input', function () {
        keyword = searchEl.value;
        render();
    });

    reload();
})();
