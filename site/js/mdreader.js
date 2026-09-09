(function () {
    var dropzone = document.getElementById('md-dropzone');
    var fileInput = document.getElementById('md-file-input');
    var viewEl = document.getElementById('md-reading');
    var dropEl = document.getElementById('md-drop-wrap');
    var contentEl = document.getElementById('reader-content');
    var filenameEl = document.getElementById('md-filename');
    var errEl = document.getElementById('md-error');
    var btnExport = document.getElementById('md-export');
    var btnReset = document.getElementById('md-reset');

    var currentText = '';
    var currentName = '';
    var diagramPromise = null;

    function show(el) { if (el) el.style.display = ''; }
    function hide(el) { if (el) el.style.display = 'none'; }

    function showErr(msg) {
        errEl.textContent = msg;
        show(errEl);
    }
    function clearErr() { hide(errEl); }

    function slugify(s) {
        s = (s || '').toLowerCase().trim()
            .replace(/\s+/g, '-')
            .replace(/[^\w\u4e00-\u9fff-]/g, '')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
        return s || 'sec';
    }

    function escHtml(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }

    function buildContentHtml(mdText, rewriteMdLinks) {
        var html = marked.parse(mdText);
        var host = document.createElement('div');
        host.innerHTML = html;

        var seen = {};
        host.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(function (h) {
            var id = slugify(h.textContent);
            var n = seen[id] = (seen[id] || 0) + 1;
            h.id = n > 1 ? id + '-' + n : id;
        });

        if (window.hljs) {
            host.querySelectorAll('pre code').forEach(function (b) {
                hljs.highlightElement(b);
            });
        }

        if (rewriteMdLinks) {
            host.querySelectorAll('a[href]').forEach(function (a) {
                var href = a.getAttribute('href') || '';
                if (!/^(https?:)?\/\//i.test(href) && href.charAt(0) !== '#'
                    && href.charAt(0) !== '/' && /\.md(#.*)?$/i.test(href)) {
                    a.setAttribute('href', href.replace(/\.md(#.*)?$/i, '.html$1'));
                }
            });
        }
        return host.innerHTML;
    }

    function readFileAsText(file) {
        return new Promise(function (resolve, reject) {
            var r = new FileReader();
            r.onload = function () { resolve(r.result); };
            r.onerror = function () { reject(new Error('读取文件失败')); };
            r.readAsText(file);
        });
    }

    function openDoc(file) {
        if (!file || !/\.(md|markdown)$/i.test(file.name)) {
            showErr('仅支持 .md 文件');
            return;
        }
        readFileAsText(file).then(function (text) {
            currentText = text;
            currentName = file.name;
            clearErr();
            contentEl.innerHTML = buildContentHtml(text, false);
            contentEl.scrollTop = 0;
            filenameEl.textContent = file.name;
            hide(dropEl);
            show(viewEl);
            show(btnExport);
            if (window.renderMermaidIn) {
                diagramPromise = renderMermaidIn(contentEl);
            } else {
                diagramPromise = Promise.resolve();
            }
        }).catch(function (e) {
            showErr('读取失败: ' + e.message);
        });
    }

    function reset() {
        currentText = '';
        currentName = '';
        diagramPromise = null;
        contentEl.innerHTML = '';
        clearErr();
        hide(viewEl);
        show(dropEl);
        if (fileInput) fileInput.value = '';
    }

    var EXPORT_CSS =
        'body{margin:0;background:#f5f5f5;color:#333;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;line-height:1.75;}' +
        '.mdpage{max-width:880px;margin:24px auto;background:#fff;padding:24px 36px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);word-break:break-word;}' +
        'h1,h2,h3,h4,h5,h6{color:#2c3e50;line-height:1.35;}' +
        'h1{font-size:1.8em;border-bottom:2px solid #eee;padding-bottom:.3em;}' +
        'h2{font-size:1.5em;border-bottom:1px solid #eee;padding-bottom:.2em;}' +
        'a{color:#3498db;}img{max-width:100%;height:auto;}' +
        '.mermaid-img{display:block;max-width:100%;height:auto;margin:1em auto;background:#fff;}' +
        'table{border-collapse:collapse;margin:1em 0;}' +
        'th,td{border:1px solid #ddd;padding:.5em .8em;text-align:left;}' +
        'th{background:#f6f8fa;}' +
        'blockquote{margin:1em 0;padding:.5em 1em;border-left:4px solid #3498db;background:#f8fafc;color:#555;}' +
        'pre{background:#f6f8fa;border:1px solid #e1e4e8;border-radius:6px;padding:1em;overflow-x:auto;}' +
        'code{background:#f0f0f0;padding:.15em .4em;border-radius:3px;font-family:"Fira Code",Menlo,Consolas,monospace;font-size:.88em;}' +
        'pre code{background:none;padding:0;}' +
        'hr{border:none;border-top:1px solid #eee;margin:1.5em 0;}' +
        '.hljs{color:#24292e;background:transparent}' +
        '.hljs-comment,.hljs-quote{color:#6a737d;font-style:italic}' +
        '.hljs-keyword,.hljs-selector-tag,.hljs-subst{color:#d73a49}' +
        '.hljs-number,.hljs-literal,.hljs-variable,.hljs-template-variable,.hljs-tag .hljs-attr{color:#005cc5}' +
        '.hljs-string,.hljs-doctag,.hljs-regexp{color:#032f62}' +
        '.hljs-title,.hljs-section,.hljs-selector-id{color:#6f42c1;font-weight:600}' +
        '.hljs-type,.hljs-class .hljs-title{color:#e36209}' +
        '.hljs-attribute,.hljs-name{color:#6f42c1}' +
        '.hljs-built_in,.hljs-symbol,.hljs-bullet{color:#e36209}' +
        '.hljs-meta{color:#6a737d}' +
        '.hljs-emphasis{font-style:italic}' +
        '.hljs-strong{font-weight:600}';

    function rewriteMdLinks(root) {
        if (!root) return;
        root.querySelectorAll('a[href]').forEach(function (a) {
            var href = a.getAttribute('href') || '';
            if (!/^(https?:)?\/\//i.test(href) && href.charAt(0) !== '#'
                && href.charAt(0) !== '/' && /\.md(#.*)?$/i.test(href)) {
                a.setAttribute('href', href.replace(/\.md(#.*)?$/i, '.html$1'));
            }
        });
    }

    function downloadHtml(fullHtml, name) {
        var blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function exportHtml() {
        if (!currentText) return;
        var base = (currentName || 'export').replace(/\.(md|markdown)$/i, '');
        var doExport = function () {
            // 复用当前已渲染的内容（含 mermaid <img data:svg>、代码高亮、标题锚点 id）
            var holder = document.createElement('div');
            holder.innerHTML = contentEl.innerHTML;
            rewriteMdLinks(holder);
            var full = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
                + '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
                + '<title>' + escHtml(currentName) + '</title>\n'
                + '<style>' + EXPORT_CSS + '</style>\n</head>\n<body>\n'
                + '<main class="mdpage">' + holder.innerHTML + '</main>\n</body>\n</html>';
            downloadHtml(full, base + '.html');
        };
        var wait = diagramPromise || Promise.resolve();
        wait.then(doExport).catch(doExport);
    }

    // ==== 拖拽 ====
    if (dropzone) {
        ['dragenter', 'dragover'].forEach(function (ev) {
            dropzone.addEventListener(ev, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('md-drop-active');
            });
        });
        ['dragleave', 'drop'].forEach(function (ev) {
            dropzone.addEventListener(ev, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('md-drop-active');
            });
        });
        dropzone.addEventListener('drop', function (e) {
            var files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) openDoc(files[0]);
            else showErr('未检测到文件');
        });
        dropzone.addEventListener('click', function () {
            if (fileInput) fileInput.click();
        });
    }
    if (fileInput) {
        fileInput.addEventListener('change', function () {
            if (fileInput.files && fileInput.files.length) openDoc(fileInput.files[0]);
            fileInput.value = '';
        });
    }

    // ==== 工具栏 ====
    if (btnExport) btnExport.addEventListener('click', exportHtml);
    if (btnReset) btnReset.addEventListener('click', reset);

    reset();
})();
