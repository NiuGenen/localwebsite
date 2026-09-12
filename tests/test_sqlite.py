import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import backend
import storage


def process_insert(database, offset):
    db = storage.connect(database)
    try:
        for i in range(20):
            with storage.transaction(db):
                storage.insert(db, 'features', {
                    'id': f'{offset}-{i}', 'title': '并发', 'content': '内容', 'created': i,
                })
    finally:
        db.close()


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'site'
        self.source.mkdir()
        self.database = self.root / 'data' / 'app.db'
        self.old_db = backend.app.config['DATABASE']
        self.old_custom = backend.CUSTOM_DIR
        backend.app.config['DATABASE'] = str(self.database)
        backend.CUSTOM_DIR = str(self.root / 'custom')
        backend.app.config['TESTING'] = True

    def tearDown(self):
        backend.app.config['DATABASE'] = self.old_db
        backend.CUSTOM_DIR = self.old_custom
        self.tmp.cleanup()

    def init(self):
        return storage.migrate(self.database, self.source)

    def request(self, method, path, payload=None, remote=False):
        with backend.app.test_client() as client:
            return client.open(path, method=method, json=payload,
                               headers={'X-Real-IP': '192.0.2.1' if remote else '127.0.0.1'})

    def records(self, table):
        db = storage.connect(self.database)
        try:
            return storage.all_records(db, table)
        finally:
            db.close()

    def test_migration_preserves_every_collection_order_and_legacy_fields(self):
        data = {
            'todos': [{'id': 'todo', 'text': '旧事项', 'priority': 'high', 'done': False,
                       'in_progress': True, 'created': 1, 'updated': 2}],
            'features': [{'id': str(i), 'title': '标题', 'content': '正文', 'created': 1} for i in (2, 1)],
            'temp_notes': [{'id': 'note', 'title': '笔记', 'content': '中文\n内容', 'created': 1}],
            'links': [{'id': 'link', 'title': '链接', 'description': '', 'url': '/files/', 'created': 1}],
            'pages': [{'id': 'page', 'title': '页面', 'description': '', 'pinned': True, 'created': 1}],
            'peers': [{'id': 'peer', 'host': '127.0.0.1', 'port': 9000, 'name': '节点',
                       'dir_label': '', 'first_seen': 1, 'last_seen': 2}],
        }
        originals = {}
        for table, items in data.items():
            raw = json.dumps(items, ensure_ascii=False).encode()
            originals[storage.SOURCES[table]] = raw
            (self.source / storage.SOURCES[table]).write_bytes(raw)
        self.assertTrue(self.init())
        data['todos'][0]['status'] = 'in_progress'
        for table, expected in data.items():
            self.assertEqual(self.records(table), expected)
        self.request('POST', '/api/features', {'title': '新增', 'content': '新增'})
        self.assertFalse(self.init())
        self.assertEqual(len(self.records('features')), 3)
        backup = Path(storage.archive_legacy(self.database, self.source))
        for name, raw in originals.items():
            self.assertEqual((backup / name).read_bytes(), raw)
            self.assertFalse((self.source / name).exists())
        storage.archive_legacy(self.database, self.source)  # restartable archive

    def test_invalid_migration_rolls_back_and_can_retry(self):
        path = self.source / 'features.json'
        for bad in ('{broken', '{}', '[{"id":"missing-fields"}]',
                    json.dumps([{'id': 'dup', 'title': 'x', 'content': 'x', 'created': 1}] * 2)):
            path.write_text(bad)
            with self.assertRaises((ValueError, sqlite3.IntegrityError)):
                self.init()
            self.assertEqual(path.read_text(), bad)
            db = storage.connect(self.database)
            try:
                with self.assertRaises(RuntimeError):
                    storage.check_schema(db)
            finally:
                db.close()
        path.write_text('[]')
        self.assertTrue(self.init())

    def test_archive_refuses_changed_source(self):
        path = self.source / 'features.json'
        path.write_text('[]')
        self.init()
        path.write_text('[ ]')
        with self.assertRaises(ValueError):
            storage.archive_legacy(self.database, self.source)
        self.assertTrue(path.exists())

    def test_duplicate_peer_address_rejects_entire_import(self):
        peer = {'id': 'a', 'host': '127.0.0.1', 'port': 9000, 'name': '节点',
                'dir_label': '', 'first_seen': 1, 'last_seen': 1}
        (self.source / 'peers.json').write_text(json.dumps([peer, dict(peer, id='b')]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.init()
        self.assertTrue((self.source / 'peers.json').exists())

    def test_online_backup_includes_wal_and_refuses_overwrite(self):
        self.init()
        db = storage.connect(self.database)
        destination = self.root / 'backup.db'
        script = Path(__file__).resolve().parent.parent / 'scripts' / 'backup_sqlite.py'
        try:
            db.execute('PRAGMA wal_autocheckpoint=0')
            with storage.transaction(db):
                storage.insert(db, 'features', {'id': 'wal', 'title': '标题', 'content': '内容', 'created': 1})
            self.assertTrue(Path(str(self.database) + '-wal').exists())
            command = [sys.executable, str(script), str(destination), '--database', str(self.database)]
            subprocess.run(command, check=True, capture_output=True)
            copy = storage.connect(destination)
            try:
                self.assertEqual(storage.all_records(copy, 'features'), self.records('features'))
            finally:
                copy.close()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        finally:
            db.close()

    def test_all_crud_and_permissions(self):
        self.init()
        for endpoint, table, payload, change in [
            ('todo', 'todos', {'text': '事项'}, {'done': True}),
            ('features', 'features', {'title': '功能', 'content': '内容'}, {'title': '新标题'}),
            ('temp', 'temp_notes', {'title': '文本', 'content': '内容'}, {'content': '新内容'}),
            ('links', 'links', {'title': '链接', 'url': '/files/'}, {'description': '简介'}),
            ('pages', 'pages', {'title': '页面'}, {'pinned': True}),
        ]:
            with self.subTest(endpoint=endpoint):
                if endpoint != 'todo':
                    self.assertEqual(self.request('POST', '/api/' + endpoint, payload, remote=True).status_code, 403)
                response = self.request('POST', '/api/' + endpoint, payload)
                self.assertEqual(response.status_code, 201, response.json)
                item = response.json
                path = '/api/' + endpoint + '/' + item['id']
                response = self.request('PUT', path, change)
                self.assertEqual(response.status_code, 200, response.json)
                for key, value in change.items():
                    self.assertEqual(response.json[key], value)
                self.assertEqual(len(self.request('GET', '/api/' + endpoint).json), 1)
                self.assertEqual(self.request('DELETE', path).status_code, 200)
                self.assertEqual(self.request('DELETE', path).status_code, 404)
                self.assertEqual(self.records(table), [])
        # Read restrictions on todo/features/temp are enforced by Nginx.

    def test_weekly_defaults_are_copied_only_when_report_is_created(self):
        self.init()
        with backend.app.test_client() as client:
            h = {'X-Real-IP': '127.0.0.1'}
            default = client.post('/api/weekly/default-projects', json={'name': '研发', 'required': True}, headers=h)
            self.assertEqual(default.status_code, 201)
            report = client.post('/api/weekly', json={'title': '第 1 周', 'description': '不应保存', 'week_start': '2026-09-07', 'week_end': '2026-09-13'}, headers=h)
            self.assertEqual(report.status_code, 201)
            self.assertNotIn('description', report.json)
            self.assertEqual([(p['name'], p['required']) for p in report.json['projects']], [('研发', True)])
            changed = client.put('/api/weekly/' + report.json['id'] + '/projects/' + report.json['projects'][0]['id'], json={'name': '研发（本周）', 'required': False, 'position': 0}, headers=h)
            self.assertEqual(changed.status_code, 200)
            updated = client.put('/api/weekly/' + report.json['id'], json={'description': '仍不应保存'}, headers=h)
            self.assertEqual(updated.status_code, 200)
            self.assertNotIn('description', updated.json)
            next_report = client.post('/api/weekly', json={'title': '第 2 周', 'week_start': '2026-09-14', 'week_end': '2026-09-20'}, headers=h)
            self.assertEqual([(p['name'], p['required']) for p in next_report.json['projects']], [('研发', True)])

    def test_weekly_schema_upgrade_drops_description_and_preserves_relations(self):
        self.init()
        db = storage.connect(self.database)
        try:
            with storage.transaction(db):
                db.execute("ALTER TABLE weekly_reports ADD COLUMN description TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
                db.execute("INSERT INTO weekly_reports(id,title,week_start,week_end,created,updated,description) VALUES(?,?,?,?,?,?,?)",
                           ('old-report', '旧周报', '2026-08-03', '2026-08-07', 1, 1, '直接删除的简介'))
                db.execute("INSERT INTO weekly_projects(id,report_id,name,required,position,created,updated) VALUES(?,?,?,?,?,?,?)",
                           ('old-project', 'old-report', '项目', 0, 0, 1, 1))
                db.execute("INSERT INTO weekly_submissions(id,report_id,person_name,contents,created,updated) VALUES(?,?,?,?,?,?)",
                           ('old-submission', 'old-report', '张三', '{}', 1, 1))
        finally:
            db.close()

        self.assertTrue(storage.migrate(self.database, self.source))
        db = storage.connect(self.database)
        try:
            self.assertNotIn('description', {row['name'] for row in db.execute('PRAGMA table_info(weekly_reports)')})
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], '2')
            self.assertEqual(db.execute('SELECT title FROM weekly_reports').fetchone()[0], '旧周报')
            self.assertEqual(db.execute('SELECT name FROM weekly_projects').fetchone()[0], '项目')
            self.assertEqual(db.execute('SELECT person_name FROM weekly_submissions').fetchone()[0], '张三')
        finally:
            db.close()
        self.assertFalse(storage.migrate(self.database, self.source))

    def test_weekly_list_limit_preserves_order_and_validates_input(self):
        self.init()
        with backend.app.test_client() as client:
            h = {'X-Real-IP': '127.0.0.1'}
            for day in range(1, 8):
                response = client.post('/api/weekly', json={
                    'title': f'第 {day} 周',
                    'week_start': f'2026-09-{day:02d}',
                    'week_end': f'2026-09-{day:02d}',
                }, headers=h)
                self.assertEqual(response.status_code, 201)
            latest = client.get('/api/weekly?limit=1').json[0]
            saved = client.post('/api/weekly/' + latest['id'] + '/submissions', json={
                'person_name': '张三', 'contents': {}
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(len(client.get('/api/weekly').json), 7)
            limited = client.get('/api/weekly?limit=5')
            self.assertEqual(limited.status_code, 200)
            self.assertEqual([item['title'] for item in limited.json],
                             ['第 7 周', '第 6 周', '第 5 周', '第 4 周', '第 3 周'])
            self.assertEqual([item['submission_count'] for item in limited.json], [1, 0, 0, 0, 0])
            for value in ('', '0', '-1', 'abc'):
                response = client.get('/api/weekly?limit=' + value)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['error'], 'limit 必须是正整数')

    def test_weekly_markdown_export_omits_unfilled_sections(self):
        self.init()
        with backend.app.test_client() as client:
            h = {'X-Real-IP': '127.0.0.1'}
            report = client.post('/api/weekly', json={
                'title': '周报', 'week_start': '2026-09-07', 'week_end': '2026-09-13'
            }, headers=h).json
            for name in ('已填写项目', '空项目'):
                client.post('/api/weekly/' + report['id'] + '/projects',
                            json={'name': name, 'required': False}, headers=h)
            detail = client.get('/api/weekly/' + report['id']).json
            project_ids = {p['name']: p['id'] for p in detail['projects']}
            client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_name': '张三',
                'contents': {project_ids['已填写项目']: '完成内容', project_ids['空项目']: '   '}
            })
            client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_name': '李四',
                'contents': {project_ids['已填写项目']: '', project_ids['空项目']: ''}
            })
            people = client.get('/api/weekly/' + report['id'] + '/people')
            self.assertEqual(people.status_code, 200)
            self.assertEqual(people.json, ['张三', '李四'])
            self.assertEqual(client.get('/api/weekly/missing/people').status_code, 404)
            for view in ('person', 'project'):
                exported = client.get('/api/weekly/' + report['id'] + '/export?view=' + view)
                text = exported.get_data(as_text=True)
                self.assertEqual(exported.status_code, 200)
                self.assertIn('完成内容', text)
                self.assertNotIn('（未填写）', text)
                self.assertNotIn('空项目', text)
                self.assertNotIn('李四', text)
            filtered = client.get('/api/weekly/' + report['id'] + '/export?person=张三')
            self.assertEqual(filtered.status_code, 200)
            self.assertIn('完成内容', filtered.get_data(as_text=True))
            missing = client.get('/api/weekly/' + report['id'] + '/export?person=王五')
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json['error'], '人员不存在：王五')
            self.assertEqual(client.get('/api/weekly/' + report['id'] + '/export?person=').status_code, 400)

    def test_threaded_api_adds_and_independent_field_updates(self):
        self.init()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda i: self.request('POST', '/api/todo', {'text': str(i)}), range(80)))
        self.assertTrue(all(r.status_code == 201 for r in responses))
        self.assertEqual(len(self.records('todos')), 80)
        item_id = responses[0].json['id']
        for i in range(10):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(self.request, 'PUT', '/api/todo/' + item_id, {'text': str(i)})
                b = pool.submit(self.request, 'PUT', '/api/todo/' + item_id, {'priority': 'high'})
                self.assertEqual(a.result().status_code, 200)
                self.assertEqual(b.result().status_code, 200)
            record = next(r for r in self.records('todos') if r['id'] == item_id)
            self.assertEqual((record['text'], record['priority']), (str(i), 'high'))

    def test_process_writers_and_rollback(self):
        self.init()
        context = multiprocessing.get_context('spawn')
        processes = [context.Process(target=process_insert, args=(str(self.database), i)) for i in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len(self.records('features')), 80)
        db = storage.connect(self.database)
        try:
            with self.assertRaises(RuntimeError):
                with storage.transaction(db):
                    storage.delete(db, 'features', '0-0')
                    raise RuntimeError('simulated failure')
        finally:
            db.close()
        self.assertEqual(len(self.records('features')), 80)

    def test_api_rollback_and_busy(self):
        self.init()
        item = self.request('POST', '/api/todo', {'text': '原始'}).json
        original_update = storage.update
        def fail_after_update(*args):
            original_update(*args)
            raise RuntimeError('simulated failure')
        with patch.object(storage, 'update', side_effect=fail_after_update):
            with self.assertRaises(RuntimeError):
                self.request('PUT', '/api/todo/' + item['id'], {'text': '失败'})
        self.assertEqual(self.records('todos')[0]['text'], '原始')
        db = storage.connect(self.database)
        original_connect = storage.connect
        try:
            db.execute('BEGIN IMMEDIATE')
            with patch.object(storage, 'connect', side_effect=lambda p: original_connect(p, timeout=0.01)):
                result = self.request('POST', '/api/todo', {'text': '锁超时'})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.headers['Retry-After'], '1')
            db.execute('ROLLBACK')
        finally:
            db.close()
        self.assertEqual(len(self.records('todos')), 1)

    def test_peer_heartbeats_unique_and_cleanup_race(self):
        self.init()
        payload = {'secret': backend.PEER_SECRET, 'name': '节点', 'host': '127.0.0.1', 'port': 9000}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            replies = list(pool.map(lambda _: self.request('POST', '/api/peers/register', payload), range(40)))
        self.assertEqual(sum(r.status_code == 201 for r in replies), 1)
        self.assertEqual(len({r.json['id'] for r in replies}), 1)
        self.assertEqual(len(self.records('peers')), 1)
        for _ in range(10):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(self.request, 'POST', '/api/peers/register', payload)
                b = pool.submit(self.request, 'GET', '/api/peers')
                self.assertEqual(a.result().status_code, 200)
                self.assertEqual(len(b.result().json), 1)
        # Cleanup can run before or after a heartbeat for an expired node. Either
        # ordering must leave the newly registered/live node intact.
        for _ in range(10):
            db = storage.connect(self.database)
            db.execute('UPDATE peers SET last_seen=0')
            db.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                heartbeat = pool.submit(self.request, 'POST', '/api/peers/register', payload)
                cleanup = pool.submit(self.request, 'GET', '/api/peers')
                self.assertIn(heartbeat.result().status_code, (200, 201))
                self.assertEqual(cleanup.result().status_code, 200)
            self.assertEqual(len(self.records('peers')), 1)
        db = storage.connect(self.database)
        try:
            db.execute('UPDATE peers SET last_seen=0')
        finally:
            db.close()
        self.assertEqual(self.request('GET', '/api/peers').json, [])
        self.assertEqual(self.request('POST', '/api/peers/register', payload).status_code, 201)
        self.assertEqual(self.request('POST', '/api/peers/unregister', payload).status_code, 200)
        self.assertEqual(self.request('POST', '/api/peers/unregister', payload).status_code, 404)


if __name__ == '__main__':
    unittest.main()
