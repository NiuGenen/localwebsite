(function () {
    var gridEl = document.getElementById('peers-grid');
    var loadingEl = document.getElementById('peers-loading');
    var emptyEl = document.getElementById('peers-empty');
    var errorEl = document.getElementById('peers-error');
    var countEl = document.getElementById('peers-count');
    var cmdEl = document.getElementById('peers-cmd');
    var onelinerEl = document.getElementById('peers-oneliner');
    var peers = [];
    var loadTimer = null;

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function fillCommand() {
        if (onelinerEl) {
            onelinerEl.textContent = 'curl -O ' + window.location.protocol + '//' + window.location.host
                + '/peer.py && python3 peer.py';
        }
        if (!cmdEl) return;
        cmdEl.textContent = '# 方式一：直接运行，共享脚本所在目录，机器名取本机主机名\n'
            + 'python3 peer.py\n\n'
            + '# 方式二：指定共享目录，机器名默认\n'
            + 'python3 peer.py --dir /path/to/share\n\n'
            + '# 方式三：指定共享目录与机器名\n'
            + 'python3 peer.py --dir /path/to/share --name "我的机器"';
    }

    function fmtSeen(ts) {
        if (!ts) return '-';
        var d = new Date(ts * 1000);
        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function render() {
        gridEl.innerHTML = '';
        countEl.textContent = peers.length + ' 台机器';

        if (peers.length === 0) {
            emptyEl.style.display = '';
            emptyEl.textContent = '当前没有在线共享的机器。运行上面脚本后，这里会自动出现。';
            countEl.textContent = '';
            return;
        }
        emptyEl.style.display = 'none';

        peers.forEach(function (p) {
            var card = document.createElement('div');
            card.className = 'card peer-card';

            var head = document.createElement('div');
            head.className = 'peer-head';

            var icon = document.createElement('div');
            icon.className = 'card-icon';
            icon.textContent = '🖥️';

            var status = document.createElement('span');
            status.className = 'peer-status peer-status-on';
            status.textContent = '● 在线';

            head.appendChild(icon);
            head.appendChild(status);

            var h3 = document.createElement('h3');
            h3.textContent = p.name;

            var meta = document.createElement('div');
            meta.className = 'peer-meta';
            meta.textContent = p.host + ':' + p.port;

            var dir = document.createElement('div');
            dir.className = 'peer-dir';
            dir.textContent = p.dir_label || '（未填写共享目录）';

            var seen = document.createElement('div');
            seen.className = 'peer-seen';
            seen.textContent = '最近心跳 ' + fmtSeen(p.last_seen);

            card.appendChild(head);
            card.appendChild(h3);
            card.appendChild(meta);
            card.appendChild(dir);
            card.appendChild(seen);

            var btn = document.createElement('a');
            btn.href = '/peer.html?id=' + encodeURIComponent(p.id);
            btn.className = 'btn';
            btn.textContent = '浏览共享';
            card.appendChild(btn);

            gridEl.appendChild(card);
        });
    }

    function loadPeers() {
        return fetch('/api/peers')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                peers = data || [];
                loadingEl.style.display = 'none';
                render();
                setError('');
            })
            .catch(function (e) {
                loadingEl.style.display = 'none';
                setError('加载共享列表失败: ' + e.message);
            });
    }

    fillCommand();
    loadPeers();
    loadTimer = setInterval(loadPeers, 15000);
})();
