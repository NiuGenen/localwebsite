#!/usr/bin/env python3
"""Stop legacy backends before importing. Repeated imports never overwrite live SQLite data."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(os.environ.get('LOCALWEBSITE_DB', ROOT / 'data' / 'app.db')))
    parser.add_argument('--source', type=Path, default=ROOT / 'site')
    parser.add_argument('--archive-legacy', action='store_true', help='校验备份后移除静态目录中的旧 JSON')
    args = parser.parse_args()
    try:
        changed = storage.migrate(args.database, args.source)
        print('迁移完成' if changed else '数据库已初始化，跳过导入')
        db = storage.connect(args.database)
        try:
            for table in storage.SOURCES:
                print(f'{table}: {len(storage.all_records(db, table))}')
        finally:
            db.close()
        if args.archive_legacy:
            print('旧 JSON 备份目录:', storage.archive_legacy(args.database, args.source))
    except Exception as exc:
        print(f'迁移失败: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
