(function () {
    var mermaidLoader = null;
    var seq = 0;

    function ensureMermaid() {
        if (window.mermaid) { return Promise.resolve(); }
        if (mermaidLoader) { return mermaidLoader; }
        mermaidLoader = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = '/js/mermaid.min.js';
            s.onload = function () {
                try {
                    window.mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });
                    resolve();
                } catch (e) { reject(e); }
            };
            s.onerror = function () { reject(new Error('mermaid 加载失败')); };
            document.head.appendChild(s);
        });
        return mermaidLoader;
    }

    function utf8B64(str) {
        return btoa(unescape(encodeURIComponent(str)));
    }

    function errText(e) {
        var s = (e && (e.message || e.str || String(e))) || '未知错误';
        return String(s).slice(0, 200);
    }

    function markError(afterEl, msg) {
        var note = document.createElement('div');
        note.className = 'md-diagram-error';
        note.textContent = msg;
        if (afterEl && afterEl.parentNode) {
            afterEl.parentNode.insertBefore(note, afterEl.nextSibling);
        }
    }

    function renderOne(code) {
        var src = code.textContent || '';
        var pre = code.parentNode;
        seq += 1;
        return window.mermaid.render('mdg' + seq, src).then(function (res) {
            var svg = (res && res.svg) || res;
            if (typeof svg !== 'string' || !pre || !pre.parentNode) return;
            var img = document.createElement('img');
            img.className = 'mermaid-img';
            img.alt = '图';
            img.loading = 'lazy';
            img.src = 'data:image/svg+xml;base64,' + utf8B64(svg);
            pre.parentNode.replaceChild(img, pre);
        }).catch(function (e) {
            markError(pre, '图渲染失败：' + errText(e));
        });
    }

    window.renderMermaidIn = function (container) {
        if (!container) return Promise.resolve();
        var blocks = container.querySelectorAll('pre code.language-mermaid');
        if (!blocks.length) return Promise.resolve();
        return ensureMermaid().then(function () {
            var nodes = Array.prototype.slice.call(blocks);
            return nodes.reduce(function (chain, code) {
                return chain.then(function () { return renderOne(code); });
            }, Promise.resolve());
        }).catch(function (e) {
            Array.prototype.slice.call(blocks).forEach(function (code) {
                markError(code.parentNode, '图渲染失败：' + errText(e));
            });
        });
    };
})();
