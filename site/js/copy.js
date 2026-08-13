(function () {
    window.copyText = function (text) {
        return new Promise(function (resolve, reject) {
            function fallback() {
                var ta = document.createElement('textarea');
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.top = '0';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                ta.setSelectionRange(0, ta.value.length);
                var ok = false;
                try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
                document.body.removeChild(ta);
                if (ok) resolve(); else reject(new Error('复制失败'));
            }
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(resolve, fallback);
            } else {
                fallback();
            }
        });
    };
})();
