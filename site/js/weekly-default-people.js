(function () {
    var list = document.getElementById('default-person-list');
    var empty = document.getElementById('default-person-empty');
    var error = document.getElementById('default-person-error');
    var modal = document.getElementById('default-person-modal');
    var head = document.getElementById('default-person-head');
    var name = document.getElementById('default-person-name');
    var hint = document.getElementById('default-person-hint');
    var editing = null;

    function request(url, options) {
        return fetch(url, options).then(function (response) {
            return response.json().then(function (result) {
                if (!response.ok) throw Error(result.error || '操作失败');
                return result;
            });
        });
    }

    function load() {
        request('/api/weekly/default-people').then(function (items) {
            list.innerHTML = '';
            error.textContent = '';
            empty.style.display = items.length ? 'none' : '';
            items.forEach(function (person) {
                var row = document.createElement('div');
                row.className = 'weekly-person-row';
                var label = document.createElement('span');
                label.textContent = person.name;
                var edit = document.createElement('button');
                edit.className = 'btn btn-sm';
                edit.textContent = '编辑';
                edit.onclick = function () {
                    editing = person;
                    head.textContent = '编辑默认人员';
                    name.value = person.name;
                    hint.textContent = '';
                    modal.style.display = 'flex';
                    name.focus(); name.select();
                };
                var remove = document.createElement('button');
                remove.className = 'btn btn-sm btn-danger';
                remove.textContent = '删除';
                remove.onclick = function () {
                    if (!confirm('删除默认人员“' + person.name + '”？已有周报不会受到影响。')) return;
                    request('/api/weekly/default-people/' + person.id, { method: 'DELETE' })
                        .then(load).catch(function (err) { error.textContent = err.message; });
                };
                row.append(label, edit, remove);
                list.appendChild(row);
            });
        }).catch(function (err) { error.textContent = err.message; });
    }

    document.getElementById('default-person-add').onclick = function () {
        editing = null; head.textContent = '添加默认人员'; name.value = ''; hint.textContent = '';
        modal.style.display = 'flex'; name.focus();
    };
    document.getElementById('default-person-cancel').onclick = function () { modal.style.display = 'none'; };
    document.getElementById('default-person-save').onclick = function () {
        var value = name.value.trim();
        if (!value) { hint.textContent = '人员名称不能为空'; return; }
        var url = '/api/weekly/default-people' + (editing ? '/' + editing.id : '');
        request(url, {
            method: editing ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: value })
        }).then(function () { modal.style.display = 'none'; load(); })
            .catch(function (err) { hint.textContent = err.message; });
    };
    fetch('/api/local').then(function (response) { return response.json(); }).then(function (result) {
        if (!result.local) { location.href = '/weekly.html'; return; }
        load();
    }).catch(function () { location.href = '/weekly.html'; });
})();
