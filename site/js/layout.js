(function () {
    var KEY = 'site_content_width';
    var MIN = 900;
    var MAX = 1800;
    var DEFAULT = 900;
    var slider = document.getElementById('width-slider');
    var label = document.getElementById('width-value');

    function clamp(v) {
        v = parseInt(v, 10);
        if (!isFinite(v)) return DEFAULT;
        return Math.min(MAX, Math.max(MIN, v));
    }

    function apply(w) {
        document.body.style.setProperty('--content-width', w + 'px');
        if (slider) slider.value = w;
        if (label) label.textContent = w;
    }

    apply(clamp(localStorage.getItem(KEY)));

    if (slider) {
        slider.addEventListener('input', function () {
            var w = clamp(slider.value);
            localStorage.setItem(KEY, w);
            apply(w);
        });
    }
})();
