(function () {
    var listEl = document.getElementById('todo-list');
    var emptyEl = document.getElementById('todo-empty');
    var errorEl = document.getElementById('todo-error');
    var countEl = document.getElementById('todo-count');
    var inputEl = document.getElementById('todo-input');
    var addPriorityEl = document.getElementById('todo-add-priority');
    var addBtn = document.getElementById('todo-add-btn');
    var sortBtns = document.querySelectorAll('.todo-sort-btn');

    var todos = [];
    var sortMode = 'time';

    var PRIORITY_ORDER = { high: 0, medium: 1, low: 2 };
    var PRIORITY_LABEL = { high: '高', medium: '中', low: '低' };
    var PRIORITY_CYCLE = ['high', 'medium', 'low'];

    var STATUS_CYCLE = { pending: 'in_progress', in_progress: 'paused', paused: 'pending' };
    var STATUS_LABEL = { pending: '开始', in_progress: '进行中', paused: '暂停' };
    var STATUS_TITLE = { pending: '标记为进行中', in_progress: '标记为暂停', paused: '重新开始' };
    var GROUP_META = {
        in_progress: { label: '进行中', icon: '⏳' },
        paused: { label: '暂停', icon: '⏸' },
        pending: { label: '未开始', icon: '📋' },
        done: { label: '已完成', icon: '✅' }
    };

    function getStatus(item) {
        return item.status || (item.in_progress ? 'in_progress' : 'pending');
    }

    function groupKey(item) {
        return item.done ? 'done' : getStatus(item);
    }

    function getSorted() {
        var done = todos.filter(function (t) { return t.done; });
        var cmp;
        if (sortMode === 'name') {
            cmp = function (a, b) { return a.text.localeCompare(b.text, 'zh'); };
        } else if (sortMode === 'priority') {
            cmp = function (a, b) {
                var p = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
                return p !== 0 ? p : b.created - a.created;
            };
        } else {
            cmp = function (a, b) { return b.created - a.created; };
        }
        var inProgress = [];
        var paused = [];
        var pending = [];
        todos.forEach(function (t) {
            if (t.done) return;
            var s = getStatus(t);
            if (s === 'in_progress') inProgress.push(t);
            else if (s === 'paused') paused.push(t);
            else pending.push(t);
        });
        return inProgress.sort(cmp).concat(paused.sort(cmp), pending.sort(cmp), done.sort(cmp));
    }

    function setError(msg) {
        if (msg && msg.message) msg = msg.message;
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function render() {
        listEl.innerHTML = '';
        var sorted = getSorted();
        var pendingCount = todos.filter(function (t) { return !t.done; }).length;
        var inProgressCount = 0;
        var pausedCount = 0;
        todos.forEach(function (t) {
            if (t.done) return;
            var s = getStatus(t);
            if (s === 'in_progress') inProgressCount++;
            else if (s === 'paused') pausedCount++;
        });
        countEl.textContent = todos.length + ' 项（未完成 ' + pendingCount + '，进行中 ' + inProgressCount + '，暂停 ' + pausedCount + '）';
        if (sorted.length === 0) {
            emptyEl.style.display = '';
            return;
        }
        emptyEl.style.display = 'none';

        var groupCounts = { in_progress: 0, paused: 0, pending: 0, done: 0 };
        sorted.forEach(function (t) { groupCounts[groupKey(t)]++; });

        var currentGroup = null;
        sorted.forEach(function (item) {
            var gkey = groupKey(item);
            if (gkey !== currentGroup) {
                currentGroup = gkey;
                var meta = GROUP_META[gkey];
                var header = document.createElement('li');
                header.className = 'todo-group-header';
                header.textContent = meta.icon + ' ' + meta.label + ' · ' + groupCounts[gkey];
                listEl.appendChild(header);
            }

            var li = document.createElement('li');
            var status = getStatus(item);
            var statusClass = status === 'in_progress' ? ' todo-inprogress' : (status === 'paused' ? ' todo-paused' : '');
            li.className = 'todo-item' + (item.done ? ' todo-done' : '') + statusClass;
            li.__todoItem = item;

            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'todo-toggle';
            toggle.title = item.done ? '标记为未完成' : '标记为完成';
            toggle.innerHTML = item.done ? '&#9745;' : '&#9744;';
            li.appendChild(toggle);

            var progress = document.createElement('button');
            progress.type = 'button';
            progress.className = 'todo-progress' + (status === 'in_progress' ? ' todo-progress-active' : (status === 'paused' ? ' todo-progress-paused' : ''));
            progress.title = STATUS_TITLE[status];
            progress.textContent = STATUS_LABEL[status];
            li.appendChild(progress);

            var text = document.createElement('span');
            text.className = 'todo-text';
            text.textContent = item.text;
            li.appendChild(text);

            var prio = document.createElement('button');
            prio.type = 'button';
            prio.className = 'todo-prio todo-prio-' + item.priority;
            prio.title = '点击调整优先级';
            prio.textContent = PRIORITY_LABEL[item.priority];
            li.appendChild(prio);

            var edit = document.createElement('button');
            edit.type = 'button';
            edit.className = 'todo-edit';
            edit.title = '编辑';
            edit.innerHTML = '&#9998;';
            li.appendChild(edit);

            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'todo-delete';
            del.title = '删除';
            del.innerHTML = '&#10005;';
            li.appendChild(del);

            listEl.appendChild(li);
        });
    }

    function startEdit(li, item) {
        var textEl = li.querySelector('.todo-text');
        var input = document.createElement('input');
        input.type = 'text';
        input.maxLength = 200;
        input.className = 'todo-edit-input';
        input.value = item.text;
        textEl.replaceWith(input);

        var editBtn = li.querySelector('.todo-edit');
        editBtn.classList.add('todo-edit-confirm');
        editBtn.title = '保存';
        editBtn.innerHTML = '&#10003;';

        var delBtn = li.querySelector('.todo-delete');
        delBtn.classList.add('todo-delete-cancel');
        delBtn.title = '取消';

        li.classList.add('todo-editing');
        input.focus();
        input.select();
    }

    function saveEdit(li) {
        var input = li.querySelector('.todo-edit-input');
        var text = input.value.trim();
        if (!text) { input.focus(); return; }
        var item = li.__todoItem;
        apiUpdate(item.id, { text: text }).catch(function (e) { setError(e); });
    }

    listEl.addEventListener('click', function (e) {
        var btn = e.target.closest('button');
        if (!btn || !listEl.contains(btn)) return;
        var li = btn.closest('.todo-item');
        if (!li) return;
        var item = li.__todoItem;
        if (!item) return;
        var editing = li.classList.contains('todo-editing');

        if (btn.classList.contains('todo-toggle')) {
            if (editing) return;
            item.done = !item.done;
            var patch = { done: item.done };
            if (item.done) { item.status = 'pending'; patch.status = 'pending'; }
            apiUpdate(item.id, patch).catch(function (err) { setError(err); });
        } else if (btn.classList.contains('todo-progress')) {
            if (editing || item.done) return;
            var next = STATUS_CYCLE[getStatus(item)];
            item.status = next;
            li.className = 'todo-item' + (next === 'in_progress' ? ' todo-inprogress' : (next === 'paused' ? ' todo-paused' : ''));
            btn.className = 'todo-progress' + (next === 'in_progress' ? ' todo-progress-active' : (next === 'paused' ? ' todo-progress-paused' : ''));
            btn.textContent = STATUS_LABEL[next];
            btn.title = STATUS_TITLE[next];
            apiUpdate(item.id, { status: next }).catch(function (err) { setError(err); });
        } else if (btn.classList.contains('todo-prio')) {
            if (editing) return;
            var next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(item.priority) + 1) % PRIORITY_CYCLE.length];
            item.priority = next;
            btn.className = 'todo-prio todo-prio-' + item.priority;
            btn.textContent = PRIORITY_LABEL[next];
            apiUpdate(item.id, { priority: next }).catch(function (err) { setError(err); });
        } else if (btn.classList.contains('todo-edit')) {
            if (editing) {
                saveEdit(li);
            } else {
                startEdit(li, item);
            }
        } else if (btn.classList.contains('todo-delete')) {
            if (editing) {
                reload();
            } else {
                apiDelete(item.id).catch(function (err) { setError(err); });
            }
        }
    });

    function reload() {
        return fetch('/api/todo')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                todos = data;
                render();
                setError('');
            })
            .catch(function (e) {
                setError('加载待办失败: ' + e.message);
            });
    }

    function apiUpdate(id, patch) {
        return fetch('/api/todo/' + id, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch)
        }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || 'HTTP ' + r.status); });
            return r.json();
        }).then(function () { return reload(); });
    }

    function apiDelete(id) {
        return fetch('/api/todo/' + id, { method: 'DELETE' }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || 'HTTP ' + r.status); });
        }).then(function () { return reload(); });
    }

    function addTodo() {
        var text = inputEl.value.trim();
        if (!text) { inputEl.focus(); return; }
        addBtn.disabled = true;
        fetch('/api/todo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, priority: addPriorityEl.value })
        }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || 'HTTP ' + r.status); });
            return r.json();
        }).then(function () {
            inputEl.value = '';
            return reload();
        }).catch(function (e) {
            setError('添加失败: ' + e.message);
        }).finally(function () {
            addBtn.disabled = false;
        });
    }

    addBtn.addEventListener('click', addTodo);
    inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); addTodo(); }
    });

    sortBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            sortMode = btn.getAttribute('data-sort');
            sortBtns.forEach(function (b) { b.classList.toggle('active', b === btn); });
            render();
        });
    });

    reload();
})();
