(function () {
    var HEADING_RE = /^( {0,3})(#{1,6})(?:[ \t]+(.*)|[ \t]*)$/;
    var FENCE_RE = /^ {0,3}(`{3,}|~{3,})/;
    var SETEXT_RE = /^ {0,3}(=+|-+)\s*$/;

    function normalize(value) {
        if (!value) return value || '';
        var lines = value.split(/\r?\n/);
        var headings = [];
        var fenceChar = null;
        var fenceSize = 0;

        lines.forEach(function (line, index) {
            var fence = line.match(FENCE_RE);
            if (fenceChar) {
                var marker = fence ? fence[1] : '';
                if (marker && marker.charAt(0) === fenceChar && marker.length >= fenceSize) {
                    fenceChar = null;
                    fenceSize = 0;
                }
                return;
            }
            if (fence) {
                fenceChar = fence[1].charAt(0);
                fenceSize = fence[1].length;
                return;
            }

            var heading = line.match(HEADING_RE);
            if (heading) {
                headings.push({kind:'atx', start:index, level:heading[2].length});
                return;
            }
            if (index && lines[index - 1].trim() && SETEXT_RE.test(line)
                    && !HEADING_RE.test(lines[index - 1])) {
                headings.push({
                    kind:'setext',
                    start:index - 1,
                    underline:index,
                    level:line.trim().charAt(0) === '=' ? 1 : 2
                });
            }
        });

        if (!headings.length) return value;
        var minimum = Math.min.apply(null, headings.map(function (item) { return item.level; }));
        if (minimum >= 4) return value;

        var shift = 4 - minimum;
        var replacements = {};
        var skipped = {};
        headings.forEach(function (item) {
            var newLevel = Math.min(6, item.level + shift);
            if (item.kind === 'atx') {
                var match = lines[item.start].match(HEADING_RE);
                replacements[item.start] = match[1] + '#'.repeat(newLevel) + ' ' + (match[3] || '');
            } else {
                replacements[item.start] = '#'.repeat(newLevel) + ' ' + lines[item.start].trim();
                skipped[item.underline] = true;
            }
        });
        var result = [];
        lines.forEach(function (line, index) {
            if (skipped[index]) return;
            result.push(Object.prototype.hasOwnProperty.call(replacements, index)
                ? replacements[index]
                : line);
        });
        return result.join('\n') + (/\r?\n$/.test(value) ? '\n' : '');
    }

    function escapeText(value) {
        var host = document.createElement('div');
        host.textContent = value || '';
        return host.innerHTML.replace(/\n/g, '<br>');
    }

    function render(value) {
        var normalized = normalize(value);
        if (!window.marked || !window.DOMPurify) return escapeText(normalized);
        var html = window.marked.parse(normalized, {gfm:true, breaks:true});
        return window.DOMPurify.sanitize(html);
    }

    window.WeeklyMarkdown = {normalize:normalize, render:render};
})();
