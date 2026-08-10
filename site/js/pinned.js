(function () {
    var container = document.getElementById('pinned-cards');
    if (!container) return;

    function firstLine(text) {
        var t = (text || '').split('\n')[0] || '';
        t = t.replace(/[#*_`>~\[\]()!-]/g, ' ').replace(/\s+/g, ' ').trim();
        return t;
    }

    fetch('/api/pages')
        .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function (pages) {
            var pinned = (pages || []).filter(function (p) { return !!p.pinned; });
            if (!pinned.length) return;
            pinned.forEach(function (p) {
                var card = document.createElement('div');
                card.className = 'card card-pinned';

                var icon = document.createElement('div');
                icon.className = 'card-icon';
                icon.textContent = '📄';

                var h3 = document.createElement('h3');
                h3.textContent = p.title;

                var para = document.createElement('p');
                para.textContent = firstLine(p.description) || '（无简介）';

                var btn = document.createElement('a');
                btn.href = '/custom.html?id=' + encodeURIComponent(p.id);
                btn.className = 'btn';
                btn.textContent = '阅读';

                card.appendChild(icon);
                card.appendChild(h3);
                card.appendChild(para);
                card.appendChild(btn);
                container.appendChild(card);
            });
        })
        .catch(function () {});
})();
