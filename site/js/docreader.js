(function () {
    var frame = document.getElementById('docreader-frame');
    var loading = document.getElementById('docreader-loading');
    var errorEl = document.getElementById('docreader-error');
    var titleEl = document.getElementById('docreader-title');
    var backBtn = document.getElementById('docreader-back');
    var downloadLink = document.getElementById('docreader-download');

    function getQueryParam(name) {
        var m = location.search.match(new RegExp('[?&]' + name + '=([^&]*)'));
        if (!m) return null;
        try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
    }

    function fileName(path) {
        var parts = path.replace(/\\/g, '/').split('/');
        return parts[parts.length - 1] || path;
    }

    function showError(msg) {
        loading.style.display = 'none';
        frame.style.display = 'none';
        errorEl.style.display = '';
        errorEl.textContent = msg;
    }

    function encPath(p) {
        return p.split('/').map(function (s) { return encodeURIComponent(s); }).join('/');
    }

    if (backBtn) {
        backBtn.addEventListener('click', function () {
            if (history.length > 1) history.back();
            else location.href = '/files/';
        });
    }

    var path = getQueryParam('path');
    if (!path) {
        showError('缺少文件路径参数。');
        return;
    }
    titleEl.textContent = fileName(path);
    downloadLink.href = '/files/' + encPath(path);

    fetch('/api/doc?path=' + encodeURIComponent(path))
        .then(function (r) {
            if (!r.ok) {
                return r.json().then(function (d) {
                    throw new Error(d.error || ('HTTP ' + r.status));
                });
            }
            return r.text();
        })
        .then(function (html) {
            loading.style.display = 'none';
            frame.style.display = '';
            var url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
            frame.src = url;
            frame.addEventListener('load', function () { URL.revokeObjectURL(url); });
        })
        .catch(function (err) {
            showError('文档读取失败: ' + err.message);
        });
})();
