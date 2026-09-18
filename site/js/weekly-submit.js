(function () {
    var params = new URLSearchParams(location.search);
    var id = params.get('id');
    var mode = params.get('mode') === 'edit' ? 'edit' : 'submit';
    var personId = params.get('person_id');
    var submissionId = params.get('submission_id');
    var detailUrl = id ? '/weekly-detail.html?id=' + encodeURIComponent(id) : '/weekly.html';
    var card = document.getElementById('editor-card');
    var fatal = document.getElementById('editor-fatal');
    var fatalMessage = document.getElementById('editor-fatal-message');
    var fatalBack = document.getElementById('editor-fatal-back');
    var fields = document.getElementById('editor-fields');
    var personName = document.getElementById('editor-person-name');
    var hint = document.getElementById('editor-hint');
    var saveButtons = Array.prototype.slice.call(document.querySelectorAll('[data-editor-save]'));
    var backButtons = Array.prototype.slice.call(document.querySelectorAll('[data-editor-back]'));
    var data;
    var selectedPerson = null;
    var selectedSubmission = null;
    var dirty = false;
    var saving = false;

    function showFatal(message) {
        card.style.display = 'none';
        fatalMessage.textContent = message;
        fatalBack.href = id ? detailUrl : '/weekly.html';
        fatal.style.display = '';
    }

    function clearHint() {
        hint.textContent = '';
        hint.className = 'weekly-editor-form-hint';
        hint.hidden = true;
        hint.removeAttribute('role');
    }

    function showError(message, conflict) {
        hint.textContent = message;
        hint.className = conflict
            ? 'weekly-editor-form-hint weekly-conflict-hint'
            : 'weekly-editor-form-hint fb-modal-hint-err';
        hint.hidden = false;
        hint.setAttribute('role', 'alert');
        hint.scrollIntoView({block:'center', behavior:'smooth'});
    }

    function markDirty() {
        if (!saving) dirty = true;
    }

    function updateSaveState() {
        var disabled = saving || !(mode === 'edit' ? selectedSubmission : selectedPerson);
        saveButtons.forEach(function (button) { button.disabled = disabled; });
    }

    function setSaving(value) {
        saving = value;
        backButtons.forEach(function (button) { button.disabled = value; });
        updateSaveState();
    }

    function backToDetail() {
        if (saving) return;
        if (dirty && !confirm('当前内容尚未保存，确定返回周报详情吗？')) return;
        dirty = false;
        location.href = detailUrl;
    }

    function renderEmpty(message) {
        fields.innerHTML = '';
        var empty = document.createElement('p');
        empty.className = 'page-empty';
        empty.textContent = message;
        fields.appendChild(empty);
    }

    function renderFields() {
        fields.innerHTML = '';
        if (!data.projects.length) {
            renderEmpty('本周报尚未配置项目。');
            return;
        }

        data.projects.forEach(function (project) {
            var value = selectedSubmission ? (selectedSubmission.contents[project.id] || '') : '';
            var expanded = project.required || Boolean(value.trim());
            var field = document.createElement('div');
            var heading = document.createElement('div');
            var label = document.createElement('label');
            var textarea = document.createElement('textarea');
            var editor = document.createElement('div');
            var textareaId = 'weekly-project-' + project.id;

            field.className = 'weekly-field';
            heading.className = 'weekly-field-head';
            label.htmlFor = textareaId;
            label.textContent = project.name + (project.required ? '（必填）' : '');
            textarea.id = textareaId;
            textarea.value = value;
            textarea.dataset.id = project.id;
            if (project.required) textarea.setAttribute('aria-required', 'true');
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

            textarea.addEventListener('input', markDirty);
            editor.appendChild(textarea);
            field.append(heading, editor);
            fields.appendChild(field);
        });
    }

    function contentsFromFields() {
        var contents = {};
        fields.querySelectorAll('textarea').forEach(function (textarea) {
            contents[textarea.dataset.id] = textarea.value;
        });
        return contents;
    }

    function validateRequired(contents) {
        for (var i = 0; i < data.projects.length; i++) {
            var project = data.projects[i];
            if (project.required && !(contents[project.id] || '').trim()) {
                showError('请填写必填项目：' + project.name, false);
                var textarea = document.getElementById('weekly-project-' + project.id);
                if (textarea) textarea.focus();
                return false;
            }
        }
        return true;
    }

    function save() {
        if (saving) return;
        var contents = contentsFromFields();
        if (!validateRequired(contents)) return;

        var payload;
        if (mode === 'edit') {
            if (!selectedSubmission) {
                showError('未找到要修改的提交，请返回详情页重新选择人员。', false);
                return;
            }
            payload = {
                person_id: selectedSubmission.person_id,
                submission_id: selectedSubmission.id,
                expected_revision: selectedSubmission.revision,
                contents: contents
            };
        } else {
            if (!selectedPerson) {
                showError('未找到要提交的人员，请返回详情页重新选择。', false);
                return;
            }
            payload = {person_id: selectedPerson.id, contents: contents};
        }

        clearHint();
        setSaving(true);
        fetch('/api/weekly/' + encodeURIComponent(id) + '/submissions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(function (response) {
            return response.json().then(function (result) {
                return {status: response.status, result: result};
            });
        }).then(function (outcome) {
            if (outcome.result.error) {
                showError(outcome.result.error, outcome.status === 409);
                return;
            }
            dirty = false;
            location.href = detailUrl;
        }).catch(function () {
            showError('保存失败，请稍后重试。', false);
        }).finally(function () {
            setSaving(false);
        });
    }

    function initTarget() {
        if (mode === 'edit') {
            selectedSubmission = (data.submissions || []).find(function (submission) {
                return submission.id === submissionId
                    || (personId && submission.person_id === personId);
            });
            if (!selectedSubmission) {
                showFatal('未找到要修改的人员提交，请返回周报详情页重新选择。');
                return;
            }
            personName.textContent = selectedSubmission.person_name;
            renderFields();
        } else {
            selectedPerson = data.people.find(function (item) {
                return item.id === personId && !item.submitted;
            });
            if (!selectedPerson) {
                showFatal('未找到可提交的人员，请返回周报详情页重新选择。');
                return;
            }
            personName.textContent = selectedPerson.name;
            renderFields();
        }
        updateSaveState();
    }

    function load() {
        if (!id) {
            showFatal('缺少周报 ID，无法打开提交页面。');
            return;
        }
        if (mode === 'edit' && !submissionId && !personId) {
            showFatal('缺少修改人员信息，请返回周报详情页重新选择。');
            return;
        }
        if (mode === 'submit' && !personId) {
            showFatal('缺少提交人员信息，请返回周报详情页重新选择。');
            return;
        }

        fetch('/api/weekly/' + encodeURIComponent(id)).then(function (response) {
            return response.json().then(function (result) {
                if (!response.ok || result.error) throw Error(result.error || ('HTTP ' + response.status));
                return result;
            });
        }).then(function (result) {
            data = result;
            document.getElementById('editor-title').textContent =
                mode === 'edit' ? '修改周报' : '提交周报';
            document.getElementById('editor-meta').textContent =
                result.title + ' · ' + result.week_start + ' 至 ' + result.week_end;
            document.title = (mode === 'edit' ? '修改周报' : '提交周报') + ' - ' + result.title;
            card.style.display = '';
            initTarget();
        }).catch(function (error) {
            showFatal('周报加载失败：' + error.message);
        });
    }

    saveButtons.forEach(function (button) { button.onclick = save; });
    backButtons.forEach(function (button) { button.onclick = backToDetail; });
    window.addEventListener('beforeunload', function (event) {
        if (!dirty || saving) return;
        event.preventDefault();
        event.returnValue = '';
    });
    load();
})();
