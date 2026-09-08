(function () {
    var modal = null;

    function ensureModal() {
        if (modal) return modal;
        modal = document.createElement('div');
        modal.className = 'fb-modal-overlay';
        modal.style.display = 'none';
        modal.innerHTML =
            '<div class="fb-modal fb-modal-fulltext">' +
            '<h3 class="fb-modal-title" id="fulltext-modal-title"></h3>' +
            '<div class="fulltext-body" id="fulltext-modal-body"></div>' +
            '<div class="fb-modal-actions">' +
            '<button type="button" class="btn" id="fulltext-modal-close">关闭</button>' +
            '</div></div>';
        document.body.appendChild(modal);

        function close() { modal.style.display = 'none'; }
        modal.addEventListener('click', function (e) {
            if (e.target === modal) close();
        });
        modal.querySelector('#fulltext-modal-close').addEventListener('click', close);
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.style.display !== 'none') close();
        });
        return modal;
    }

    function isClamped(el) {
        return el.scrollHeight > el.clientHeight + 1;
    }

    window.attachFullText = function (para, title) {
        if (!para || !para.textContent || !para.parentNode) return;
        if (!isClamped(para)) {
            para.title = para.textContent;
            return;
        }
        para.title = para.textContent;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ft-more';
        btn.textContent = '⋯ 详情';

        var wrap = document.createElement('div');
        wrap.className = 'ft-more-row';
        wrap.appendChild(btn);

        para.parentNode.insertBefore(wrap, para.nextSibling);

        btn.addEventListener('click', function () {
            var m = ensureModal();
            m.querySelector('#fulltext-modal-title').textContent = title || '';
            m.querySelector('#fulltext-modal-body').textContent = para.textContent;
            m.style.display = 'flex';
        });
    };
})();
