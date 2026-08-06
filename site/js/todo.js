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

    function getSorted() {
        var done = todos.filter(function (t) { return t.done; });
        var active = todos.filter(function (t) { return !t.done; });
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
        return active.sort(cmp).concat(done.sort(cmp));
    }

    function setError(msg) {
        if (msg) { errorEl.textContent = msg; errorEl.style.display = ''; }
        else { errorEl.style.display = 'none'; }
    }

    function render() {
        listEl.innerHTML = '';
        var sorted = getSorted();
        var pending = todos.filter(function (t) { return !t.done; }).length;
        countEl.textContent = todos.length + ' 项（未完成 ' + pending + '）';
        if (sorted.length === 0) {
            emptyEl.style.display = '';
            return;
        }
        emptyEl.style.display = 'none';

        sorted.forEach(function (item) {
            var li = document.createElement('li');
            li.className = 'todo-item' + (item.done ? ' todo-done' : '');

            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'todo-toggle';
            toggle.title = item.done ? '标记为未完成' : '标记为完成';
            toggle.innerHTML = item.done ? '&#9745;' : '&#9744;';
            toggle.addEventListener('click', function () {
                item.done = !item.done;
                apiUpdate(item.id, { done: item.done }).catch(function (e) { setError(e); });
            });
            li.appendChild(toggle);

            var text = document.createElement('span');
            text.className = 'todo-text';
            text.textContent = item.text;
            li.appendChild(text);

            var prio = document.createElement('button');
            prio.type = 'button';
            prio.className = 'todo-prio todo-prio-' + item.priority;
            prio.title = '点击调整优先级';
            prio.textContent = PRIORITY_LABEL[item.priority];
            prio.addEventListener('click', function () {
                var next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(item.priority) + 1) % PRIORITY_CYCLE.length];
                item.priority = next;
                prio.className = 'todo-prio todo-prio-' + item.priority;
                prio.textContent = PRIORITY_LABEL[next];
                apiUpdate(item.id, { priority: next }).catch(function (e) { setError(e); });
            });
            li.appendChild(prio);

            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'todo-delete';
            del.title = '删除';
            del.innerHTML = '&#10005;';
            del.addEventListener('click', function () {
                apiDelete(item.id).catch(function (e) { setError(e); });
            });
            li.appendChild(del);

            listEl.appendChild(li);
        });
    }

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
