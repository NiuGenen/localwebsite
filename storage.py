"""SQLite persistence. Connections belong to one request; writes use short transactions."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager

SOURCES = {
    'todos': 'todo.json', 'features': 'features.json', 'temp_notes': 'temp_notes.json',
    'links': 'links.json', 'peers': 'peers.json', 'pages': 'custom_pages.json',
}
COLUMNS = {
    'todos': {'text': 'TEXT', 'priority': 'TEXT', 'done': 'INTEGER', 'status': 'TEXT', 'created': 'INTEGER', 'updated': 'INTEGER'},
    'features': {'title': 'TEXT', 'content': 'TEXT', 'created': 'INTEGER'},
    'temp_notes': {'title': 'TEXT', 'content': 'TEXT', 'created': 'INTEGER'},
    'links': {'title': 'TEXT', 'description': 'TEXT', 'url': 'TEXT', 'created': 'INTEGER'},
    'peers': {'name': 'TEXT', 'host': 'TEXT', 'port': 'INTEGER', 'dir_label': 'TEXT', 'first_seen': 'INTEGER', 'last_seen': 'INTEGER'},
    'pages': {'title': 'TEXT', 'description': 'TEXT', 'pinned': 'INTEGER', 'created': 'INTEGER'},
}
BOOLS = {'done', 'pinned'}
SCHEMA_VERSION = '5'



def connect(path, timeout=5):
    db = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    db.execute('PRAGMA foreign_keys=ON')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def create_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    for table, columns in COLUMNS.items():
        fields = ', '.join(f'{name} {kind} NOT NULL' for name, kind in columns.items())
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} '
                   f'(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, {fields}, extra TEXT NOT NULL)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS peer_address ON peers(host, port)')
    db.execute('CREATE INDEX IF NOT EXISTS peer_last_seen ON peers(last_seen)')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_reports (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL, week_start TEXT NOT NULL, week_end TEXT NOT NULL,
        created INTEGER NOT NULL, updated INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_projects (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        report_id TEXT NOT NULL, name TEXT NOT NULL, required INTEGER NOT NULL,
        position INTEGER NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
        UNIQUE(report_id, name), FOREIGN KEY(report_id) REFERENCES weekly_reports(id) ON DELETE CASCADE)''')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_people (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        report_id TEXT NOT NULL, name TEXT NOT NULL,
        created INTEGER NOT NULL, updated INTEGER NOT NULL,
        UNIQUE(report_id, name), FOREIGN KEY(report_id) REFERENCES weekly_reports(id) ON DELETE CASCADE)''')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_submissions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        report_id TEXT NOT NULL, person_id TEXT NOT NULL, contents TEXT NOT NULL,
        revision INTEGER NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
        UNIQUE(report_id, person_id), FOREIGN KEY(report_id) REFERENCES weekly_reports(id) ON DELETE CASCADE,
        FOREIGN KEY(person_id) REFERENCES weekly_people(id) ON DELETE CASCADE)''')
    db.execute('CREATE INDEX IF NOT EXISTS weekly_project_order ON weekly_projects(report_id, position, seq)')
    db.execute('CREATE INDEX IF NOT EXISTS weekly_submission_report ON weekly_submissions(report_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_default_projects (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL UNIQUE, required INTEGER NOT NULL,
        position INTEGER NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS weekly_default_people (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL UNIQUE, created INTEGER NOT NULL, updated INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS protected_paths (
        path TEXT PRIMARY KEY, created INTEGER NOT NULL, updated INTEGER NOT NULL)''')


def check_schema(db):
    create_schema(db)
    try:
        row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError as exc:
        raise RuntimeError('数据库尚未初始化，请停止旧后端并运行 scripts/migrate_sqlite.py') from exc
    if row is None or row['value'] != SCHEMA_VERSION:
        raise RuntimeError('数据库版本不兼容，请检查迁移状态')


def upgrade_schema(db, version):
    if version == SCHEMA_VERSION:
        return False
    changed = False
    if version == '1':
        columns = {row['name'] for row in db.execute('PRAGMA table_info(weekly_reports)')}
        if 'description' in columns:
            db.execute('ALTER TABLE weekly_reports DROP COLUMN description')
        version = '2'
        changed = True
    if version == '2':
        columns = {row['name'] for row in db.execute('PRAGMA table_info(weekly_submissions)')}
        if 'revision' not in columns:
            db.execute('ALTER TABLE weekly_submissions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
        version = '3'
        changed = True
    if version == '3':
        # Build a stable roster for every report from its existing submissions.
        submissions = db.execute(
            'SELECT report_id,person_name,MIN(created) AS created,MAX(updated) AS updated '
            'FROM weekly_submissions GROUP BY report_id,person_name ORDER BY MIN(seq)'
        ).fetchall()
        for row in submissions:
            db.execute(
                'INSERT INTO weekly_people(id,report_id,name,created,updated) VALUES(?,?,?,?,?)',
                (uuid.uuid4().hex[:12], row['report_id'], row['person_name'],
                 row['created'], row['updated']),
            )

        # The nearest non-empty historical report best represents the current team.
        latest = db.execute(
            'SELECT r.id FROM weekly_reports r WHERE EXISTS '
            '(SELECT 1 FROM weekly_people p WHERE p.report_id=r.id) '
            'ORDER BY r.week_end DESC,r.week_start DESC,r.seq DESC LIMIT 1'
        ).fetchone()
        if latest:
            people = db.execute(
                'SELECT name,created,updated FROM weekly_people WHERE report_id=? '
                'ORDER BY name COLLATE NOCASE,seq', (latest['id'],)
            ).fetchall()
            for person in people:
                db.execute(
                    'INSERT INTO weekly_default_people(id,name,created,updated) VALUES(?,?,?,?)',
                    (uuid.uuid4().hex[:12], person['name'], person['created'], person['updated']),
                )

        db.execute('DROP INDEX IF EXISTS weekly_submission_report')
        db.execute('ALTER TABLE weekly_submissions RENAME TO weekly_submissions_legacy')
        db.execute('''CREATE TABLE weekly_submissions (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            report_id TEXT NOT NULL, person_id TEXT NOT NULL, contents TEXT NOT NULL,
            revision INTEGER NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
            UNIQUE(report_id, person_id),
            FOREIGN KEY(report_id) REFERENCES weekly_reports(id) ON DELETE CASCADE,
            FOREIGN KEY(person_id) REFERENCES weekly_people(id) ON DELETE CASCADE)''')
        db.execute(
            'INSERT INTO weekly_submissions(seq,id,report_id,person_id,contents,revision,created,updated) '
            'SELECT s.seq,s.id,s.report_id,p.id,s.contents,s.revision,s.created,s.updated '
            'FROM weekly_submissions_legacy s JOIN weekly_people p '
            'ON p.report_id=s.report_id AND p.name=s.person_name'
        )
        db.execute('DROP TABLE weekly_submissions_legacy')
        db.execute('CREATE INDEX weekly_submission_report ON weekly_submissions(report_id)')
        version = '4'
        changed = True
    if version == '4':
        version = '5'
        changed = True
    if version != SCHEMA_VERSION:
        raise RuntimeError('数据库版本不兼容，请检查迁移状态')
    if changed:
        db.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (SCHEMA_VERSION,))
    return changed


def encode(table, item):
    columns = COLUMNS[table]
    if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
        raise ValueError(f'{table}: 每条记录必须包含非空字符串 id')
    values = []
    for field, kind in columns.items():
        value = item.get(field)
        if field in BOOLS:
            if not isinstance(value, bool):
                raise ValueError(f'{table}.{field}: 必须是布尔值')
            value = int(value)
        elif kind == 'INTEGER':
            if type(value) is not int:
                raise ValueError(f'{table}.{field}: 必须是整数')
        elif not isinstance(value, str):
            raise ValueError(f'{table}.{field}: 必须是字符串')
        values.append(value)
    extra = {k: v for k, v in item.items() if k != 'id' and k not in columns}
    return [item['id'], *values, json.dumps(extra, ensure_ascii=False)]


def decode(table, row):
    if row is None:
        return None
    item = json.loads(row['extra'])
    item['id'] = row['id']
    for field in COLUMNS[table]:
        item[field] = bool(row[field]) if field in BOOLS else row[field]
    return item


def all_records(db, table):
    if table not in COLUMNS:
        raise ValueError('Unknown table')
    return [decode(table, row) for row in db.execute(f'SELECT * FROM {table} ORDER BY seq')]


def get(db, table, item_id):
    if table not in COLUMNS:
        raise ValueError('Unknown table')
    return decode(table, db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone())


def insert(db, table, item):
    values = encode(table, item)
    names = ', '.join(['id', *COLUMNS[table], 'extra'])
    db.execute(f'INSERT INTO {table} ({names}) VALUES ({", ".join("?" for _ in values)})', values)


def update(db, table, item):
    values = encode(table, item)
    fields = ', '.join(f'{field}=?' for field in [*COLUMNS[table], 'extra'])
    return db.execute(f'UPDATE {table} SET {fields} WHERE id=?', values[1:] + values[:1]).rowcount


def delete(db, table, item_id):
    if table not in COLUMNS:
        raise ValueError('Unknown table')
    return db.execute(f'DELETE FROM {table} WHERE id=?', (item_id,)).rowcount


def migrate(path, source_dir):
    """Import once in one transaction. Caller must stop all legacy JSON writers."""
    path, source_dir = Path(path), Path(source_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        with transaction(db):
            create_schema(db)
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if version:
                changed = upgrade_schema(db, version['value'])
                check_schema(db)
                return changed
            records, originals = {}, {}
            for table, filename in SOURCES.items():
                source = source_dir / filename
                if source.exists():
                    raw = source.read_bytes()
                    items = json.loads(raw.decode('utf-8'))
                    if not isinstance(items, list):
                        raise ValueError(f'{filename}: 顶层必须是数组')
                    originals[filename] = raw
                else:
                    items = []
                for item in items:
                    if table == 'todos' and isinstance(item, dict) and 'status' not in item:
                        item['status'] = 'in_progress' if item.get('in_progress') else 'pending'
                    encode(table, item)
                records[table] = items
            for table, items in records.items():
                for item in items:
                    insert(db, table, item)
            # Keep exact source bytes outside the static root before committing the import.
            backup = path.parent / ('legacy-json-' + uuid.uuid4().hex)
            manifest = {}
            if originals:
                backup.mkdir(mode=0o700)
                for filename, raw in originals.items():
                    with (backup / filename).open('xb') as fh:
                        fh.write(raw)
                        fh.flush()
                        os.fsync(fh.fileno())
                    manifest[filename] = hashlib.sha256(raw).hexdigest()
                for directory in (backup, backup.parent):
                    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            db.executemany('INSERT INTO metadata(key,value) VALUES (?,?)', [
                ('schema_version', SCHEMA_VERSION), ('legacy_backup', str(backup.resolve())),
                ('legacy_hashes', json.dumps(manifest)),
            ])
        return True
    finally:
        db.close()


def archive_legacy(path, source_dir):
    """Remove only byte-identical originals already backed up by a committed migration."""
    db = connect(path)
    try:
        check_schema(db)
        meta = dict(db.execute('SELECT key,value FROM metadata'))
    finally:
        db.close()
    hashes = json.loads(meta['legacy_hashes'])
    for filename, digest in hashes.items():
        backup = Path(meta['legacy_backup']) / filename
        if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
            raise ValueError(f'{filename}: 迁移备份校验失败')
        source = Path(source_dir) / filename
        if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f'{filename}: 迁移后源数据发生变化，拒绝删除；请检查旧服务是否仍运行')
    for filename in hashes:
        (Path(source_dir) / filename).unlink(missing_ok=True)
    return meta['legacy_backup']
