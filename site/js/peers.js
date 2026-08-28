(function () {
    var gridEl = document.getElementById('peers-grid');
    var loadingEl = document.getElementById('peers-loading');
    var emptyEl = document.getElementById('peers-empty');
    var errorEl = document.getElementById('peers-error');
    var countEl = document.getElementById('peers-count');
    var cmdEl = document.getElementById('peers-cmd');
    var peers = [];
    var loadTimer = null;

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function escHtml(s) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(s));
        return div.innerHTML;
    }

    function buildCommand(central) {
        return 'python3 peer.py --dir /path/to/share --port 9000 --name 我的机器 \\\n'
            + '    --central ' + escHtml(central) + ' --secret <密钥>';
    }

    function fillCommand() {
        if (!cmdEl) return;
        var central = window.location.protocol + '//' + window.location.host;
        fetch('/api/peers/info')
            .then(function (r) { return r.json(); })
            .then(function (info) {
                var secret = (info && info.secret) || '<你的密钥>';
                cmdEl.textContent = 'python3 peer.py --dir /path/to/share --port 9000 --name 我的机器 \\\n'
                    + '    --central ' + central + ' --secret ' + secret;
            })
            .catch(function () {
                cmdEl.textContent = buildCommand(central);
            });
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
            countEl.textContent = '';
            return;
        }
        emptyEl.style.display = 'none';

        peers.forEach(function (p) {
            var card = document.createElement('div');
            card.className = 'card peer-card' + (p.online ? '' : ' peer-offline');

            var head = document.createElement('div');
            head.className = 'peer-head';

            var icon = document.createElement('div');
            icon.className = 'card-icon';
            icon.textContent = '🖥️';

            var status = document.createElement('span');
            status.className = 'peer-status ' + (p.online ? 'peer-status-on' : 'peer-status-off');
            status.textContent = p.online ? '● 在线' : '○ 离线';

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

            if (p.online) {
                var btn = document.createElement('a');
                btn.href = '/peer.html?id=' + encodeURIComponent(p.id);
                btn.className = 'btn';
                btn.textContent = '浏览共享';
                card.appendChild(btn);
            }

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
