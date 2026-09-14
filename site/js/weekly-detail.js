(function () {
    var id = new URLSearchParams(location.search).get('id');
    var data;
    var view = 'project';
    var content = document.getElementById('report-content');
    var fields = document.getElementById('project-fields');
    var modal = document.getElementById('submit-modal');
    var personModal = document.getElementById('person-modal');
    var nameEl = document.getElementById('person-name');
    var submitSave = document.getElementById('submit-save');
    var submitHint = document.getElementById('submit-hint');
    var editingSubmissionId = null;
    var editingRevision = null;
    var managedPerson = null;
    var personAdminModal = document.getElementById('person-admin-modal');
    var personAdminName = document.getElementById('person-admin-name');
    var personAdminHint = document.getElementById('person-admin-hint');
    var personAdminSave = document.getElementById('person-admin-save');

    function clearSubmitHint() {
        submitHint.textContent = '';
        submitHint.className = 'fb-modal-hint';
        submitHint.removeAttribute('role');
    }

    function showSubmitError(message, conflict) {
        submitHint.textContent = message;
        submitHint.className = conflict
            ? 'fb-modal-hint weekly-conflict-hint'
            : 'fb-modal-hint fb-modal-hint-err';
        submitHint.setAttribute('role', 'alert');
        submitHint.scrollIntoView({ block: 'nearest' });
    }

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

    function openSubmit(submission) {
        fields.innerHTML = '';
        editingSubmissionId = submission ? submission.id : null;
        editingRevision = submission ? submission.revision : null;
        nameEl.innerHTML = '';
        if (submission) {
            var selected = document.createElement('option');
            selected.value = submission.person_id;
            selected.textContent = submission.person_name;
            nameEl.appendChild(selected);
            nameEl.disabled = true;
        } else {
            nameEl.disabled = false;
            var placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '请选择人员（必填）';
            placeholder.disabled = true;
            placeholder.selected = true;
            nameEl.appendChild(placeholder);
            data.people.forEach(function (person) {
                var option = document.createElement('option');
                option.value = person.id;
                option.textContent = person.name + (person.submitted ? '（已提交）' : '');
                option.disabled = Boolean(person.submitted);
                nameEl.appendChild(option);
            });
        }
        clearSubmitHint();
        data.projects.forEach(function (project) {
            var value = submission ? (submission.contents[project.id] || '') : '';
            var expanded = project.required || Boolean(value.trim());
            var field = document.createElement('div');
            field.className = 'weekly-field';
            var heading = document.createElement('div');
            heading.className = 'weekly-field-head';
            var label = document.createElement('label');
            var textarea = document.createElement('textarea');
            var editor = document.createElement('div');
            var textareaId = 'weekly-project-' + project.id;
            label.htmlFor = textareaId;
            label.textContent = project.name + (project.required ? '（必填）' : '');
            textarea.id = textareaId;
            textarea.value = value;
            textarea.dataset.id = project.id;
            editor.className = 'weekly-field-editor';
            editor.hidden = !expanded;
            heading.appendChild(label);
            if (!project.required) {
                var status = document.createElement('span');
                var toggle = document.createElement('button');
                status.className = 'weekly-field-status';
                status.textContent = '（已填写）';
                toggle.type = 'button';
                toggle.className = 'btn btn-sm weekly-field-toggle';
                toggle.textContent = expanded ? '收起' : '填写';
                toggle.setAttribute('aria-controls', textareaId);
                toggle.setAttribute('aria-expanded', String(expanded));
                var updateStatus = function () {
                    status.hidden = !editor.hidden || !textarea.value.trim();
                };
                toggle.onclick = function () {
                    var willExpand = editor.hidden;
                    editor.hidden = !willExpand;
                    toggle.textContent = willExpand ? '收起' : '填写';
                    toggle.setAttribute('aria-expanded', String(willExpand));
                    updateStatus();
                    if (willExpand) textarea.focus();
                };
                textarea.addEventListener('input', updateStatus);
                updateStatus();
                heading.append(status, toggle);
            }
            editor.appendChild(textarea);
            field.append(heading, editor);
            fields.appendChild(field);
        });
        modal.style.display = 'flex';
        nameEl.focus();
        submitSave.disabled = !submission && !data.people.some(function (person) { return !person.submitted; });
        if (submitSave.disabled) showSubmitError('暂无未提交人员，请联系管理员维护本周人员名单。', false);
    }

    document.getElementById('submit-btn').onclick = function () { openSubmit(); };
    document.getElementById('edit-btn').onclick = function () {
        var select = document.getElementById('person-select');
        select.innerHTML = '';
        (data.submissions || []).forEach(function (submission) {
            var option = document.createElement('option');
            option.value = submission.id;
            option.textContent = submission.person_name;
            select.appendChild(option);
        });
        document.getElementById('person-hint').textContent = data.submissions.length ? '' : '暂无已有人员提交';
        personModal.style.display = 'flex';
    };
    document.getElementById('person-cancel').onclick = function () { personModal.style.display = 'none'; };
    document.getElementById('person-next').onclick = function () {
        var selected = data.submissions.find(function (submission) {
            return submission.id === document.getElementById('person-select').value;
        });
        if (selected) {
            personModal.style.display = 'none';
            openSubmit(selected);
        }
    };
    document.getElementById('submit-cancel').onclick = function () { modal.style.display = 'none'; };
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
    submitSave.onclick = function () {
        var contents = {};
        fields.querySelectorAll('textarea').forEach(function (textarea) {
            contents[textarea.dataset.id] = textarea.value;
        });
        var payload = { person_id: nameEl.value, contents: contents };
        if (editingSubmissionId) {
            payload.submission_id = editingSubmissionId;
            payload.expected_revision = editingRevision;
        }
        submitSave.disabled = true;
        fetch('/api/weekly/' + id + '/submissions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (response) {
            return response.json().then(function (result) {
                return { status: response.status, result: result };
            });
        }).then(function (outcome) {
            var result = outcome.result;
            if (result.error) {
                showSubmitError(result.error, outcome.status === 409);
                return;
            }
            modal.style.display = 'none';
            load();
        }).catch(function () {
            showSubmitError('提交失败，请稍后重试', false);
        }).finally(function () {
            submitSave.disabled = !editingSubmissionId &&
                !data.people.some(function (person) { return !person.submitted; });
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
