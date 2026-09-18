(function () {
    var id = new URLSearchParams(location.search).get('id');
    var data;
    var view = 'project';
    var content = document.getElementById('report-content');
    var personModal = document.getElementById('person-modal');
    var personSelect = document.getElementById('person-select');
    var personHint = document.getElementById('person-hint');
    var personNext = document.getElementById('person-next');
    var chooserMode = 'submit';
    var managedPerson = null;
    var personAdminModal = document.getElementById('person-admin-modal');
    var personAdminName = document.getElementById('person-admin-name');
    var personAdminHint = document.getElementById('person-admin-hint');
    var personAdminSave = document.getElementById('person-admin-save');

    function load() {
        return fetch('/api/weekly/' + encodeURIComponent(id)).then(function (response) {
            return response.json();
        }).then(function (result) {
            if (result.error) throw Error(result.error);
            data = result;
            document.getElementById('report-title').textContent = result.title;
            document.getElementById('report-meta').textContent = result.week_start + ' 至 ' + result.week_end;
            render();
            renderProjects();
            renderPeople();
            renderSubmissionStatus();
        });
    }

    function showPeopleError(message) {
        var hint = document.getElementById('people-admin-hint');
        hint.textContent = message;
        hint.className = 'fb-modal-hint fb-modal-hint-err';
        hint.setAttribute('role', 'alert');
    }

    function renderPeople() {
        var box = document.getElementById('people');
        var empty = document.getElementById('people-empty');
        if (!box || !data) return;
        box.innerHTML = '';
        document.getElementById('people-admin-hint').textContent = '';
        empty.style.display = data.people.length ? 'none' : '';
        data.people.forEach(function (person) {
            var submission = data.submissions.find(function (item) {
                return item.person_id === person.id;
            });
            var row = document.createElement('div');
            row.className = 'weekly-person-row';
            var label = document.createElement('span');
            label.textContent = person.name + (submission ? ' · 已提交' : ' · 未提交');
            var edit = document.createElement('button');
            edit.className = 'btn btn-sm';
            edit.textContent = '编辑';
            edit.onclick = function () {
                managedPerson = person;
                document.getElementById('person-admin-head').textContent = '修改人员名称';
                personAdminName.value = person.name;
                personAdminHint.textContent = '';
                personAdminHint.className = 'fb-modal-hint';
                personAdminModal.style.display = 'flex';
                personAdminName.focus();
                personAdminName.select();
            };
            var remove = document.createElement('button');
            remove.className = 'btn btn-sm btn-danger';
            remove.textContent = '删除';
            remove.onclick = function () {
                var message = submission
                    ? '删除人员“' + person.name + '”？该人员在本周报中的所有内容都会被删除，且不可恢复。'
                    : '删除人员“' + person.name + '”？';
                if (!confirm(message)) return;
                remove.disabled = true;
                fetch('/api/weekly/' + id + '/people/' + person.id, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ expected_revision: submission ? submission.revision : null })
                }).then(function (response) {
                    return response.json().then(function (result) {
                        return { status: response.status, result: result };
                    });
                }).then(function (outcome) {
                    if (outcome.result.error) {
                        if (outcome.result.code === 'revision_conflict') {
                            load().then(function () { showPeopleError(outcome.result.error); });
                        } else {
                            showPeopleError(outcome.result.error);
                        }
                        return;
                    }
                    load();
                }).catch(function () {
                    showPeopleError('删除失败，请稍后重试');
                }).finally(function () {
                    remove.disabled = false;
                });
            };
            row.append(label, edit, remove);
            box.appendChild(row);
        });
    }

    function renderSubmissionStatus() {
        var box = document.getElementById('submission-status-list');
        var empty = document.getElementById('submission-status-empty');
        var submitted = data.people.filter(function (person) { return Boolean(person.submitted); }).length;
        document.getElementById('submission-status-title').textContent =
            '提交状态（' + submitted + '/' + data.people.length + '）';
        box.innerHTML = '';
        empty.style.display = data.people.length ? 'none' : '';
        data.people.forEach(function (person) {
            var row = document.createElement('div');
            row.className = 'weekly-status-row';
            var name = document.createElement('span');
            name.textContent = person.name;
            var status = document.createElement('span');
            status.className = person.submitted ? 'weekly-status-done' : 'weekly-status-pending';
            status.textContent = person.submitted ? '已提交' : '未提交';
            row.append(name, status);
            box.appendChild(row);
        });
    }

    function renderProjects() {
        var box = document.getElementById('projects');
        if (!box || !data) return;
        box.innerHTML = '';
        data.projects.forEach(function (project, index) {
            var row = document.createElement('div');
            row.className = 'weekly-project-row';
            var label = document.createElement('span');
            label.textContent = (index + 1) + '. ' + project.name + ' · ' + (project.required ? '必填' : '选填');
            var edit = document.createElement('button');
            edit.className = 'btn btn-sm';
            edit.textContent = '编辑';
            edit.onclick = function () {
                var name = prompt('项目名称', project.name);
                if (!name) return;
                var order = prompt('显示顺序（从 1 开始）', index + 1);
                if (order === null) return;
                order = parseInt(order, 10);
                if (!isFinite(order) || order < 1) {
                    alert('顺序无效');
                    return;
                }
                fetch('/api/weekly/' + id + '/projects/' + project.id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, required: confirm('设为必填项目？'), position: order - 1 })
                }).then(load);
            };
            var remove = document.createElement('button');
            remove.className = 'btn btn-sm btn-danger';
            remove.textContent = '删除';
            remove.onclick = function () {
                if (confirm('删除项目「' + project.name + '」？')) {
                    fetch('/api/weekly/' + id + '/projects/' + project.id, { method: 'DELETE' }).then(load);
                }
            };
            row.append(label, edit, remove);
            box.appendChild(row);
        });
    }

    function render() {
        content.innerHTML = '';
        var submissions = data.submissions || [];
        if (!submissions.length) {
            content.textContent = '暂无提交内容。';
            return;
        }
        if (view === 'project') {
            data.projects.forEach(function (project) {
                var section = document.createElement('section');
                section.className = 'weekly-section';
                var heading = document.createElement('h3');
                heading.textContent = project.name + (project.required ? '（必填）' : '');
                section.appendChild(heading);
                submissions.forEach(function (submission) {
                    var value = submission.contents[project.id];
                    if (value && value.trim()) {
                        var name = document.createElement('h4');
                        name.textContent = submission.person_name;
                        var body = document.createElement('div');
                        body.className = 'weekly-body';
                        body.textContent = value;
                        section.append(name, body);
                    }
                });
                content.appendChild(section);
            });
        } else {
            submissions.forEach(function (submission) {
                var section = document.createElement('section');
                section.className = 'weekly-section';
                var heading = document.createElement('h3');
                heading.textContent = submission.person_name;
                section.appendChild(heading);
                data.projects.forEach(function (project) {
                    var value = submission.contents[project.id];
                    if (!value || !value.trim()) return;
                    var name = document.createElement('h4');
                    name.textContent = project.name;
                    var body = document.createElement('div');
                    body.className = 'weekly-body';
                    body.textContent = value;
                    section.append(name, body);
                });
                content.appendChild(section);
            });
        }
    }

    function openPersonChooser(mode) {
        if (!data) return;
        chooserMode = mode;
        personSelect.innerHTML = '';
        var editing = mode === 'edit';
        var choices = editing
            ? (data.submissions || [])
            : data.people.filter(function (person) { return !person.submitted; });
        document.getElementById('person-modal-title').textContent =
            editing ? '选择要修改的人员' : '选择提交人员';
        personHint.textContent = choices.length
            ? (editing ? '选择后进入该人员的内容修改页面。' : '选择后进入该人员的周报提交页面。')
            : (editing ? '暂无已有人员提交。' : '暂无未提交人员，请联系管理员维护本周人员名单。');
        personHint.className = choices.length ? 'fb-modal-hint' : 'fb-modal-hint fb-modal-hint-err';
        personNext.disabled = !choices.length;

        choices.forEach(function (item) {
            var option = document.createElement('option');
            option.value = item.id;
            option.textContent = editing ? item.person_name : item.name;
            option.dataset.personId = editing ? item.person_id : item.id;
            personSelect.appendChild(option);
        });
        personModal.style.display = 'flex';
        if (choices.length) personSelect.focus();
    }

    document.getElementById('submit-btn').onclick = function () { openPersonChooser('submit'); };
    document.getElementById('edit-btn').onclick = function () { openPersonChooser('edit'); };
    document.getElementById('person-cancel').onclick = function () { personModal.style.display = 'none'; };
    personNext.onclick = function () {
        var option = personSelect.options[personSelect.selectedIndex];
        if (!option) return;
        var target = '/weekly-submit.html?id=' + encodeURIComponent(id)
            + '&mode=' + chooserMode;
        target += chooserMode === 'edit'
            ? '&submission_id=' + encodeURIComponent(option.value)
            : '&person_id=' + encodeURIComponent(option.dataset.personId);
        location.href = target;
    };
    document.getElementById('person-admin-cancel').onclick = function () {
        personAdminModal.style.display = 'none';
    };
    personAdminSave.onclick = function () {
        var name = personAdminName.value.trim();
        if (!name) {
            personAdminHint.textContent = '人员名称不能为空';
            personAdminHint.className = 'fb-modal-hint fb-modal-hint-err';
            return;
        }
        personAdminSave.disabled = true;
        fetch('/api/weekly/' + id + '/people' + (managedPerson ? '/' + managedPerson.id : ''), {
            method: managedPerson ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name
            })
        }).then(function (response) {
            return response.json().then(function (result) {
                return { status: response.status, result: result };
            });
        }).then(function (outcome) {
            if (outcome.result.error) {
                personAdminHint.textContent = outcome.result.error;
                personAdminHint.className = outcome.status === 409
                    ? 'fb-modal-hint weekly-conflict-hint'
                    : 'fb-modal-hint fb-modal-hint-err';
                personAdminHint.setAttribute('role', 'alert');
                return;
            }
            personAdminModal.style.display = 'none';
            load();
        }).catch(function () {
            personAdminHint.textContent = '保存失败，请稍后重试';
            personAdminHint.className = 'fb-modal-hint fb-modal-hint-err';
        }).finally(function () {
            personAdminSave.disabled = false;
        });
    };
    document.getElementById('view-project').onclick = function () { view = 'project'; render(); };
    document.getElementById('view-person').onclick = function () { view = 'person'; render(); };
    document.getElementById('export-btn').onclick = function () {
        location.href = '/api/weekly/' + id + '/export?view=' + view;
    };

    fetch('/api/local').then(function (response) {
        return response.json();
    }).then(function (result) {
        if (result.local) {
            document.getElementById('local-admin').style.display = '';
            document.getElementById('add-project').onclick = function () {
                var name = prompt('项目名称');
                if (name) {
                    fetch('/api/weekly/' + id + '/projects', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, required: confirm('设置为必填项目？') })
                    }).then(load);
                }
            };
            document.getElementById('add-person').onclick = function () {
                managedPerson = null;
                document.getElementById('person-admin-head').textContent = '添加人员';
                personAdminName.value = '';
                personAdminHint.textContent = '';
                personAdminHint.className = 'fb-modal-hint';
                personAdminModal.style.display = 'flex';
                personAdminName.focus();
            };
        }
    });
    load();
})();
