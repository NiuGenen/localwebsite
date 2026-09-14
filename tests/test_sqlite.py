import concurrent.futures
import io
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

    def add_weekly_person(self, client, report_id, name, headers):
        response = client.post('/api/weekly/' + report_id + '/people',
                               json={'name': name}, headers=headers)
        self.assertEqual(response.status_code, 201, response.json)
        return next(person for person in response.json['people'] if person['name'] == name)

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

    def test_weekly_people_roster_defaults_status_and_submission_validation(self):
        self.init()
        with backend.app.test_client() as client:
            local = {'X-Real-IP': '127.0.0.1'}
            remote = {'X-Real-IP': '192.0.2.1'}
            denied = client.post('/api/weekly/default-people', json={'name': '张三'}, headers=remote)
            self.assertEqual(denied.status_code, 403)
            zhang_default = client.post('/api/weekly/default-people', json={'name': ' 张  三 '}, headers=local)
            self.assertEqual(zhang_default.status_code, 201, zhang_default.json)
            self.assertEqual(zhang_default.json['name'], '张 三')
            li_default = client.post('/api/weekly/default-people', json={'name': '李四'}, headers=local)
            self.assertEqual(li_default.status_code, 201)
            self.assertEqual(client.post('/api/weekly/default-people', json={'name': '李四'}, headers=local).status_code, 409)

            report = client.post('/api/weekly', json={
                'title': '人员名单', 'week_start': '2026-09-14', 'week_end': '2026-09-20'
            }, headers=local).json
            self.assertEqual([person['name'] for person in report['people']], ['张 三', '李四'])
            self.assertEqual([person['submitted'] for person in report['people']], [0, 0])
            unknown = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_name': '王五', 'contents': {}
            })
            self.assertEqual(unknown.status_code, 400)
            saved = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': report['people'][0]['id'], 'contents': {}
            })
            self.assertEqual(saved.status_code, 200, saved.json)
            current = client.get('/api/weekly/' + report['id']).json
            self.assertEqual([(p['name'], p['submitted']) for p in current['people']],
                             [('张 三', 1), ('李四', 0)])
            self.assertEqual(client.get('/api/weekly/' + report['id'] + '/people').json, ['张 三'])
            roster_person = next(p for p in current['people'] if p['name'] == '张 三')
            renamed_roster = client.put(
                '/api/weekly/' + report['id'] + '/people/' + roster_person['id'],
                json={'name': '张三（本周）'}, headers=local,
            )
            self.assertEqual(renamed_roster.status_code, 200, renamed_roster.json)
            self.assertEqual(renamed_roster.json['submissions'][0]['person_name'], '张三（本周）')
            self.assertEqual(renamed_roster.json['submissions'][0]['id'], saved.json['id'])
            stale_delete = client.delete(
                '/api/weekly/' + report['id'] + '/people/' + roster_person['id'],
                json={'expected_revision': 99}, headers=local,
            )
            self.assertEqual(stale_delete.status_code, 409)
            removed = client.delete(
                '/api/weekly/' + report['id'] + '/people/' + roster_person['id'],
                json={'expected_revision': 1}, headers=local,
            )
            self.assertEqual(removed.status_code, 200)
            self.assertEqual(client.get('/api/weekly/' + report['id']).json['submissions'], [])

            renamed = client.put('/api/weekly/default-people/' + li_default.json['id'],
                                 json={'name': '王五'}, headers=local)
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual([p['name'] for p in client.get('/api/weekly/' + report['id']).json['people']],
                             ['李四'])
            next_report = client.post('/api/weekly', json={
                'title': '下一周', 'week_start': '2026-09-21', 'week_end': '2026-09-27'
            }, headers=local).json
            self.assertEqual([p['name'] for p in next_report['people']], ['张 三', '王五'])

    def test_weekly_schema_upgrade_drops_description_and_preserves_relations(self):
        self.init()
        db = storage.connect(self.database)
        try:
            with storage.transaction(db):
                db.execute("DROP TABLE weekly_submissions")
                db.execute("DROP TABLE weekly_people")
                db.execute("DROP TABLE weekly_default_people")
                db.execute('''CREATE TABLE weekly_submissions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    report_id TEXT NOT NULL, person_name TEXT NOT NULL, contents TEXT NOT NULL,
                    created INTEGER NOT NULL, updated INTEGER NOT NULL,
                    UNIQUE(report_id, person_name),
                    FOREIGN KEY(report_id) REFERENCES weekly_reports(id) ON DELETE CASCADE)''')
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
            self.assertIn('revision', {row['name'] for row in db.execute('PRAGMA table_info(weekly_submissions)')})
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], '4')
            self.assertEqual(db.execute('SELECT title FROM weekly_reports').fetchone()[0], '旧周报')
            self.assertEqual(db.execute('SELECT name FROM weekly_projects').fetchone()[0], '项目')
            self.assertEqual(db.execute('SELECT name FROM weekly_people').fetchone()[0], '张三')
            self.assertEqual(db.execute('SELECT name FROM weekly_default_people').fetchone()[0], '张三')
            self.assertEqual(db.execute('SELECT revision FROM weekly_submissions').fetchone()[0], 1)
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
            person = self.add_weekly_person(client, latest['id'], '张三', h)
            saved = client.post('/api/weekly/' + latest['id'] + '/submissions', json={
                'person_id': person['id'], 'contents': {}
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json['revision'], 1)
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

    def test_weekly_submission_optimistic_lock_prevents_lost_updates(self):
        self.init()
        with backend.app.test_client() as client:
            local = {'X-Real-IP': '127.0.0.1'}
            report = client.post('/api/weekly', json={
                'title': '并发测试', 'week_start': '2026-09-07', 'week_end': '2026-09-13'
            }, headers=local).json
            detail = client.post('/api/weekly/' + report['id'] + '/projects', json={
                'name': '研发', 'required': False
            }, headers=local).json
            project_id = detail['projects'][0]['id']
            person = self.add_weekly_person(client, report['id'], '张三', local)
            created = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': person['id'], 'contents': {project_id: '初始内容'}
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json['revision'], 1)

            first = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'submission_id': created.json['id'], 'expected_revision': 1,
                'person_id': person['id'], 'contents': {project_id: '先保存的内容'}
            })
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json['revision'], 2)

            stale = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'submission_id': created.json['id'], 'expected_revision': 1,
                'person_id': person['id'], 'contents': {project_id: '过期页面的内容'}
            })
            self.assertEqual(stale.status_code, 409)
            self.assertIn('重新加载', stale.json['error'])
            current = client.get('/api/weekly/' + report['id']).json['submissions'][0]
            self.assertEqual(current['contents'][project_id], '先保存的内容')
            self.assertEqual(current['revision'], 2)

            duplicate = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': person['id'], 'contents': {project_id: '绕过编辑入口'}
            })
            self.assertEqual(duplicate.status_code, 409)

            deleted = client.delete(
                '/api/weekly/' + report['id'] + '/projects/' + project_id, headers=local
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json['submissions'][0]['revision'], 3)

    def test_local_weekly_person_management_renames_and_deletes_submission(self):
        self.init()
        with backend.app.test_client() as client:
            local = {'X-Real-IP': '127.0.0.1'}
            remote = {'X-Real-IP': '192.0.2.1'}
            report = client.post('/api/weekly', json={
                'title': '人员管理', 'week_start': '2026-09-07', 'week_end': '2026-09-13'
            }, headers=local).json
            detail = client.post('/api/weekly/' + report['id'] + '/projects', json={
                'name': '研发', 'required': False
            }, headers=local).json
            project_id = detail['projects'][0]['id']
            first_person = self.add_weekly_person(client, report['id'], '张三', local)
            second_person = self.add_weekly_person(client, report['id'], '李四', local)
            first = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': first_person['id'], 'contents': {project_id: '保留的内容'}
            }).json
            second = client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': second_person['id'], 'contents': {project_id: '其他内容'}
            }).json
            path = '/api/weekly/' + report['id'] + '/submissions/' + first['id']

            denied = client.put(path, json={
                'person_name': '王五', 'expected_revision': first['revision']
            }, headers=remote)
            self.assertEqual(denied.status_code, 403)
            denied = client.delete(path, json={
                'expected_revision': first['revision']
            }, headers=remote)
            self.assertEqual(denied.status_code, 403)

            renamed = client.put(path, json={
                'person_name': ' 王   五 ', 'expected_revision': first['revision']
            }, headers=local)
            self.assertEqual(renamed.status_code, 200, renamed.json)
            self.assertEqual(renamed.json['person_name'], '王 五')
            self.assertEqual(renamed.json['contents'][project_id], '保留的内容')
            self.assertEqual(renamed.json['revision'], 2)

            duplicate = client.put(path, json={
                'person_name': second['person_name'], 'expected_revision': 2
            }, headers=local)
            self.assertEqual(duplicate.status_code, 409)
            empty = client.put(path, json={
                'person_name': ' ', 'expected_revision': 2
            }, headers=local)
            self.assertEqual(empty.status_code, 400)
            stale = client.put(path, json={
                'person_name': '过期名称', 'expected_revision': 1
            }, headers=local)
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json['code'], 'revision_conflict')
            stale_delete = client.delete(path, json={
                'expected_revision': 1
            }, headers=local)
            self.assertEqual(stale_delete.status_code, 409)
            self.assertEqual(stale_delete.json['code'], 'revision_conflict')

            removed = client.delete(path, json={
                'expected_revision': 2
            }, headers=local)
            self.assertEqual(removed.status_code, 200)
            self.assertEqual(client.get('/api/weekly/' + report['id'] + '/people').json, ['李四'])
            current = client.get('/api/weekly/' + report['id']).json
            self.assertEqual([item['person_name'] for item in current['submissions']], ['李四'])
            self.assertEqual(client.get('/api/weekly?limit=1').json[0]['submission_count'], 1)
            exported = client.get('/api/weekly/' + report['id'] + '/export').get_data(as_text=True)
            self.assertNotIn('王 五', exported)
            self.assertNotIn('保留的内容', exported)
            self.assertEqual(client.delete(path, json={
                'expected_revision': 2
            }, headers=local).status_code, 404)

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
            zhang = self.add_weekly_person(client, report['id'], '张三', h)
            li = self.add_weekly_person(client, report['id'], '李四', h)
            client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': zhang['id'],
                'contents': {project_ids['已填写项目']: '完成内容', project_ids['空项目']: '   '}
            })
            client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': li['id'],
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

    def test_weekly_markdown_import_applies_defaults_and_fills_required_projects(self):
        self.init()
        with backend.app.test_client() as client:
            local = {'X-Real-IP': '127.0.0.1'}
            remote = {'X-Real-IP': '192.0.2.1'}
            client.post('/api/weekly/default-projects',
                        json={'name': '研发', 'required': True}, headers=local)
            client.post('/api/weekly/default-projects',
                        json={'name': '例行事项', 'required': False}, headers=local)
            client.post('/api/weekly/default-people',
                        json={'name': '王五'}, headers=local)
            markdown = '''# 导入周报

时间：2026-09-14 至 2026-09-20

## 研发

### 张三
完成核心功能

## 临时项目

### 张三
处理临时任务

### 李四
协助验证
'''
            denied = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(markdown.encode()), 'weekly.md')
            }, headers=remote, content_type='multipart/form-data')
            self.assertEqual(denied.status_code, 403)

            response = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(('\ufeff' + markdown).encode()), 'weekly.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(response.status_code, 201, response.json)
            report = response.json
            self.assertEqual(report['title'], '导入周报')
            self.assertEqual(
                [(project['name'], bool(project['required'])) for project in report['projects']],
                [('研发', True), ('例行事项', False), ('临时项目', False)],
            )
            project_ids = {project['name']: project['id'] for project in report['projects']}
            submissions = {item['person_name']: item for item in report['submissions']}
            self.assertEqual(set(submissions), {'张三', '李四'})
            self.assertEqual([person['name'] for person in report['people']], ['张三', '李四', '王五'])
            self.assertFalse(next(person for person in report['people'] if person['name'] == '王五')['submitted'])
            self.assertEqual(submissions['张三']['contents'][project_ids['研发']], '完成核心功能')
            self.assertEqual(submissions['张三']['contents'][project_ids['临时项目']], '处理临时任务')
            self.assertEqual(submissions['张三']['contents'][project_ids['例行事项']], '')
            self.assertEqual(submissions['李四']['contents'][project_ids['研发']], '无')
            self.assertEqual(submissions['李四']['revision'], 1)

            duplicate = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(markdown.encode()), 'weekly.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(len(client.get('/api/weekly').json), 1)

            invalid = '# 另一周报\n\n时间：2026-09-21 至 2026-09-27\n\n### 张三\n内容\n'
            bad = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(invalid.encode()), 'bad.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(len(client.get('/api/weekly').json), 1)
            wrong_encoding = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(b'\xff\xfe\xfa'), 'bad.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(wrong_encoding.status_code, 400)
            wrong_extension = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(markdown.encode()), 'weekly.txt')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(wrong_extension.status_code, 400)
            repeated_project = '''# 重复项目周报

时间：2026-09-21 至 2026-09-27

## 研发
### 张三
内容
## 研发
### 李四
内容
'''
            repeated = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(repeated_project.encode()), 'repeated.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(repeated.status_code, 400)
            self.assertIn('项目重复', repeated.json['error'])
            oversized = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(b'x' * (backend.MAX_WEEKLY_IMPORT_BYTES + 1)), 'large.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(oversized.status_code, 413)
            self.assertEqual(len(client.get('/api/weekly').json), 1)

    def test_default_weekly_markdown_export_can_be_imported_again(self):
        self.init()
        with backend.app.test_client() as client:
            local = {'X-Real-IP': '127.0.0.1'}
            report = client.post('/api/weekly', json={
                'title': '往返周报', 'week_start': '2026-09-07', 'week_end': '2026-09-13'
            }, headers=local).json
            detail = client.post('/api/weekly/' + report['id'] + '/projects', json={
                'name': '研发', 'required': False
            }, headers=local).json
            project_id = detail['projects'][0]['id']
            person = self.add_weekly_person(client, report['id'], '张三', local)
            client.post('/api/weekly/' + report['id'] + '/submissions', json={
                'person_id': person['id'], 'contents': {project_id: '完成内容\n第二行'}
            })
            exported = client.get('/api/weekly/' + report['id'] + '/export').data
            self.assertEqual(client.delete('/api/weekly/' + report['id'], headers=local).status_code, 200)

            imported = client.post('/api/weekly/import', data={
                'file': (io.BytesIO(exported), 'roundtrip.md')
            }, headers=local, content_type='multipart/form-data')
            self.assertEqual(imported.status_code, 201, imported.json)
            restored = imported.json
            self.assertEqual(restored['title'], '往返周报')
            restored_project = next(p for p in restored['projects'] if p['name'] == '研发')
            self.assertEqual(restored['submissions'][0]['person_name'], '张三')
            self.assertEqual(
                restored['submissions'][0]['contents'][restored_project['id']],
                '完成内容\n第二行',
            )

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
