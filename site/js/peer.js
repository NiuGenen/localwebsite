(function () {
    var tbody = document.getElementById('fb-tbody');
    var table = document.getElementById('fb-table');
    var loading = document.getElementById('fb-loading');
    var error = document.getElementById('fb-error');
    var empty = document.getElementById('fb-empty');
    var pathEl = document.getElementById('fb-path');
    var countEl = document.getElementById('fb-count');
    var titleEl = document.getElementById('fb-peer-title');

    var peerId = new URLSearchParams(window.location.search).get('id') || '';
    var peer = null;
    var currentPath = '';

    function getPath() {
        return window.location.hash.replace(/^#\/*/, '');
    }

    function humanSize(bytes) {
        if (bytes === 0) return '-';
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var i = 0;
        var size = bytes;
        while (size >= 1024 && i < units.length - 1) {
            size /= 1024;
            i++;
        }
        return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
    }

    function fmtDate(ts) {
        var d = new Date(ts * 1000);
        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function escHtml(s) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(s));
        return div.innerHTML;
    }

    function renderBreadcrumb(path) {
        var parts = path ? path.split('/') : [];
        var html = '<a href="#/" class="fb-bread-home"><i class="fas fa-folder"></i> ' + escHtml(peer.name) + '</a>';
        var acc = '';
        parts.forEach(function (p, i) {
            if (!p) return;
            acc += (acc ? '/' : '') + p;
            html += '<span class="fb-bread-sep">/</span>';
            if (i === parts.length - 1) {
                html += '<span class="fb-bread-current">' + escHtml(p) + '</span>';
            } else {
                html += '<a href="#/' + acc + '" class="fb-bread-link">' + escHtml(p) + '</a>';
            }
        });
        return html;
    }

    function getIconHtml(name, type) {
        if (type === 'dir') {
            return '<i class="fas fa-folder" style="color:#e67e22"></i>';
        }
        var ext = name.split('.').pop().toLowerCase();
        var iconMap = {
            pdf: 'fa-file-pdf', zip: 'fa-file-archive', tar: 'fa-file-archive',
            gz: 'fa-file-archive', tgz: 'fa-file-archive', rar: 'fa-file-archive',
            '7z': 'fa-file-archive', deb: 'fa-file-archive',
            png: 'fa-file-image', jpg: 'fa-file-image', jpeg: 'fa-file-image',
            gif: 'fa-file-image', svg: 'fa-file-image',
            md: 'fa-file-lines', txt: 'fa-file-lines',
            json: 'fa-file-code', bin: 'fa-file-binary',
            iso: 'fa-file', html: 'fa-file-code', htm: 'fa-file-code',
            py: 'fa-file-code', js: 'fa-file-code', css: 'fa-file-code'
        };
        var icon = iconMap[ext] || 'fa-file';
        return '<i class="fas ' + icon + '" style="color:#7f8c8d"></i>';
    }

    function downloadUrl(path) {
        return 'http://' + peer.host + ':' + peer.port + '/files/' + encodeURI(path);
    }

    function buildRow(entry, path) {
        var tr = document.createElement('tr');
        tr.className = entry.type === 'dir' ? 'fb-row-dir' : 'fb-row-file';

        var iconTd = document.createElement('td');
        iconTd.className = 'fb-col-icon';
        iconTd.innerHTML = getIconHtml(entry.name, entry.type);
        tr.appendChild(iconTd);

        var nameTd = document.createElement('td');
        nameTd.className = 'fb-col-name';
        if (entry.type === 'dir') {
            var childPath = path ? path + '/' + entry.name : entry.name;
            var link = document.createElement('a');
            link.href = '#/' + childPath;
            link.className = 'fb-link fb-link-dir';
            link.textContent = entry.name;
            nameTd.appendChild(link);
        } else {
            var filePath = path ? path + '/' + entry.name : entry.name;
            var flink = document.createElement('a');
            flink.href = downloadUrl(filePath);
            flink.className = 'fb-link fb-link-file';
            flink.target = '_blank';
            flink.rel = 'noopener';
            flink.textContent = entry.name;
            nameTd.appendChild(flink);
        }
        tr.appendChild(nameTd);

        var sizeTd = document.createElement('td');
        sizeTd.className = 'fb-col-size';
        sizeTd.textContent = entry.type === 'dir' ? '-' : humanSize(entry.size);
        tr.appendChild(sizeTd);

        var dateTd = document.createElement('td');
        dateTd.className = 'fb-col-date';
        dateTd.textContent = fmtDate(entry.mtime);
        tr.appendChild(dateTd);

        var opTd = document.createElement('td');
        opTd.className = 'fb-col-op';
        if (entry.type === 'file') {
            var dl = document.createElement('a');
            dl.href = downloadUrl(filePath);
            dl.target = '_blank';
            dl.rel = 'noopener';
            dl.className = 'fb-read-btn';
            dl.title = '下载';
            dl.innerHTML = '<i class="fas fa-download"></i>';
            opTd.appendChild(dl);
        }
        tr.appendChild(opTd);

        return tr;
    }

    function showError(msg) {
        loading.style.display = 'none';
        table.style.display = 'none';
        empty.style.display = 'none';
        error.style.display = '';
        error.textContent = msg;
    }

    function loadDir(path) {
        currentPath = path || '';
        loading.style.display = '';
        table.style.display = 'none';
        empty.style.display = 'none';
        error.style.display = 'none';
        tbody.innerHTML = '';

        var url = '/api/peers/' + encodeURIComponent(peerId) + '/tree'
            + (currentPath ? '?path=' + encodeURIComponent(currentPath) : '');
        fetch(url)
            .then(function (r) {
                if (!r.ok) {
                    return r.json().then(function (d) {
                        throw new Error(d.error || ('HTTP ' + r.status));
                    });
                }
                return r.json();
            })
            .then(function (data) {
                loading.style.display = 'none';
                var entries = data.entries || [];
                if (entries.length === 0) {
                    empty.style.display = '';
                    pathEl.innerHTML = renderBreadcrumb(currentPath);
                    countEl.textContent = '0 项';
                    return;
                }
                var dirs = entries.filter(function (e) { return e.type === 'dir'; });
                var files = entries.filter(function (e) { return e.type === 'file'; });
                dirs.forEach(function (d) { tbody.appendChild(buildRow(d, currentPath)); });
                files.forEach(function (f) { tbody.appendChild(buildRow(f, currentPath)); });
                table.style.display = '';
                pathEl.innerHTML = renderBreadcrumb(currentPath);
                countEl.textContent = entries.length + ' 项';
            })
            .catch(function (err) {
                showError('加载失败: ' + err.message);
                if (!currentPath) {
                    pathEl.innerHTML = '';
                    countEl.textContent = '';
                }
            });
    }

    function init() {
        if (!peerId) {
            showError('缺少节点 ID，请从「局域网共享」页面进入。');
            return;
        }
        loading.style.display = '';
        fetch('/api/peers')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (list) {
                var found = (list || []).filter(function (p) { return p.id === peerId; })[0];
                if (!found) {
                    showError('未找到该共享节点，可能已被移除。');
                    return;
                }
                if (!found.online) {
                    showError('该共享节点当前离线。');
                    return;
                }
                peer = found;
                titleEl.textContent = peer.name + ' · ' + peer.host + ':' + peer.port;
                titleEl.className = 'fb-peer-title';
                if (!window.location.hash) {
                    window.location.hash = '/';
                } else {
                    onHashChange();
                }
            })
            .catch(function (e) {
                showError('获取共享列表失败: ' + e.message);
            });
    }

    function onHashChange() {
        if (peer) loadDir(getPath());
    }

    window.addEventListener('hashchange', onHashChange);
    init();
})();
