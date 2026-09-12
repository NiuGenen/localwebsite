(function () {
    var list = document.getElementById('weekly-list');
    var empty = document.getElementById('weekly-empty');
    var create = document.getElementById('weekly-create');
    var defaults = document.getElementById('weekly-defaults');
    var modal = document.getElementById('weekly-modal');
    var head = document.getElementById('weekly-modal-head');
    var title = document.getElementById('weekly-title');
    var start = document.getElementById('weekly-start');
    var end = document.getElementById('weekly-end');
    var hint = document.getElementById('weekly-hint');
    var save = document.getElementById('weekly-save');
    var editingId = null;

    function appendMonthHeader(month) {
        var parts = month.split('-');
        var header = document.createElement('div');
        header.className = 'weekly-month-header';
        header.textContent = parts[0] + ' 年 ' + parseInt(parts[1], 10) + ' 月';
        list.appendChild(header);
    }

    function appendReport(report) {
        var row = document.createElement('div');
        row.className = 'weekly-list-row';
        var link = document.createElement('a');
        link.className = 'page-entry';
        link.href = '/weekly-detail.html?id=' + encodeURIComponent(report.id);
        link.innerHTML = '<div class="page-entry-link"><div class="page-entry-title"></div></div>';
        link.querySelector('.page-entry-title').textContent =
            report.title + '（' + report.week_start + ' 至 ' + report.week_end + '）';
        row.appendChild(link);

        if (create.style.display !== 'none') {
            var edit = document.createElement('button');
            edit.className = 'btn btn-sm';
            edit.textContent = '编辑';
            edit.onclick = function () { openEdit(report); };
            var remove = document.createElement('button');
            remove.className = 'btn btn-sm btn-danger';
            remove.textContent = '删除';
            remove.onclick = function () {
                if (confirm('删除周报「' + report.title + '」？其中的项目和提交内容也会删除。')) {
                    fetch('/api/weekly/' + report.id, { method: 'DELETE' }).then(load);
                }
            };
            row.append(edit, remove);
        }
        list.appendChild(row);
    }

    function load() {
        fetch('/api/weekly').then(function (response) {
            return response.json();
        }).then(function (reports) {
            list.innerHTML = '';
            empty.style.display = reports.length ? 'none' : '';
            var currentMonth = null;
            reports.forEach(function (report) {
                var month = report.week_end.slice(0, 7);
                if (month !== currentMonth) {
                    currentMonth = month;
                    appendMonthHeader(month);
                }
                appendReport(report);
            });
        }).catch(function () {});
    }

    function openCreate() {
        editingId = null;
        head.textContent = '创建周报';
        save.textContent = '创建';
        title.value = '';
        start.value = '';
        end.value = '';
        hint.textContent = '';
        modal.style.display = 'flex';
        title.focus();
    }

    function openEdit(report) {
        editingId = report.id;
        head.textContent = '编辑周报';
        save.textContent = '保存';
        title.value = report.title;
        start.value = report.week_start;
        end.value = report.week_end;
        hint.textContent = '';
        modal.style.display = 'flex';
        title.focus();
    }

    create.onclick = openCreate;
    document.getElementById('weekly-cancel').onclick = function () { modal.style.display = 'none'; };
    save.onclick = function () {
        if (!title.value.trim() || !start.value || !end.value) {
            hint.textContent = '请填写标题和日期';
            return;
        }
        save.disabled = true;
        fetch('/api/weekly' + (editingId ? '/' + editingId : ''), {
            method: editingId ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title.value, week_start: start.value, week_end: end.value })
        }).then(function (response) {
            return response.json();
        }).then(function (result) {
            if (result.error) {
                hint.textContent = result.error;
                return;
            }
            modal.style.display = 'none';
            load();
        }).finally(function () { save.disabled = false; });
    };

    fetch('/api/local').then(function (response) {
        return response.json();
    }).then(function (result) {
        if (result.local) {
            create.style.display = '';
            defaults.style.display = '';
        }
        load();
    }).catch(load);
})();
