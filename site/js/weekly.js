(function () {
    var list = document.getElementById('weekly-list');
    var empty = document.getElementById('weekly-empty');
    var create = document.getElementById('weekly-create');
    var defaults = document.getElementById('weekly-defaults');
    var importButton = document.getElementById('weekly-import');
    var importModal = document.getElementById('weekly-import-modal');
    var importFile = document.getElementById('weekly-import-file');
    var importHint = document.getElementById('weekly-import-hint');
    var importSave = document.getElementById('weekly-import-save');
    var modal = document.getElementById('weekly-modal');
    var head = document.getElementById('weekly-modal-head');
    var title = document.getElementById('weekly-title');
    var start = document.getElementById('weekly-start');
    var end = document.getElementById('weekly-end');
    var hint = document.getElementById('weekly-hint');
    var save = document.getElementById('weekly-save');
    var previousPage = document.getElementById('weekly-page-prev');
    var nextPage = document.getElementById('weekly-page-next');
    var pageInfo = document.getElementById('weekly-page-info');
    var pagination = document.getElementById('weekly-pagination');
    var editingId = null;
    var reports = [];
    var currentPage = 0;
    var MONTHS_PER_PAGE = 2;

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
        link.innerHTML = '<div class="page-entry-link"><div class="page-entry-title"></div><div class="weekly-submission-count"></div></div>';
        link.querySelector('.page-entry-title').textContent =
            report.title + '（' + report.week_start + ' 至 ' + report.week_end + '）';
        link.querySelector('.weekly-submission-count').textContent =
            '已提交人数：' + report.submission_count;
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

    function groupReportsByEndMonth() {
        var byMonth = {};
        reports.forEach(function (report) {
            var month = report.week_end.slice(0, 7);
            if (!byMonth[month]) byMonth[month] = [];
            byMonth[month].push(report);
        });
        return Object.keys(byMonth).sort().reverse().map(function (month) {
            return { month: month, reports: byMonth[month] };
        });
    }

    function render() {
        list.innerHTML = '';
        empty.style.display = reports.length ? 'none' : '';
        pagination.style.display = reports.length ? '' : 'none';
        if (!reports.length) return;

        var groups = groupReportsByEndMonth();
        var pageCount = Math.ceil(groups.length / MONTHS_PER_PAGE);
        currentPage = Math.max(0, Math.min(currentPage, pageCount - 1));
        groups.slice(currentPage * MONTHS_PER_PAGE, (currentPage + 1) * MONTHS_PER_PAGE)
            .forEach(function (group) {
                appendMonthHeader(group.month);
                group.reports.forEach(appendReport);
            });
        previousPage.disabled = currentPage === 0;
        nextPage.disabled = currentPage === pageCount - 1;
        pageInfo.textContent = (currentPage + 1) + '/' + pageCount;
    }

    function load() {
        fetch('/api/weekly').then(function (response) {
            return response.json();
        }).then(function (result) {
            reports = result;
            render();
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
    importButton.onclick = function () {
        importFile.value = '';
        importHint.textContent = '';
        importHint.className = 'fb-modal-hint';
        importModal.style.display = 'flex';
        importFile.focus();
    };
    document.getElementById('weekly-import-cancel').onclick = function () {
        importModal.style.display = 'none';
    };
    importSave.onclick = function () {
        if (!importFile.files.length) {
            importHint.textContent = '请选择 Markdown 文件';
            importHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        var body = new FormData();
        body.append('file', importFile.files[0]);
        importSave.disabled = true;
        fetch('/api/weekly/import', { method: 'POST', body: body }).then(function (response) {
            return response.json();
        }).then(function (result) {
            if (result.error) {
                importHint.textContent = result.error;
                importHint.className = 'fb-modal-hint fb-modal-hint-err';
                return;
            }
            location.href = '/weekly-detail.html?id=' + encodeURIComponent(result.id);
        }).catch(function () {
            importHint.textContent = '导入失败，请稍后重试';
            importHint.className = 'fb-modal-hint fb-modal-hint-err';
        }).finally(function () {
            importSave.disabled = false;
        });
    };
    previousPage.onclick = function () {
        if (currentPage > 0) {
            currentPage--;
            render();
        }
    };
    nextPage.onclick = function () {
        var pageCount = Math.ceil(groupReportsByEndMonth().length / MONTHS_PER_PAGE);
        if (currentPage + 1 < pageCount) {
            currentPage++;
            render();
        }
    };
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
            importButton.style.display = '';
        }
        load();
    }).catch(load);
})();
