#!/usr/bin/env python3
"""Create a consistent online backup, including committed WAL data."""
import argparse
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--database', type=Path, default=Path(os.environ.get('LOCALWEBSITE_DB', ROOT / 'data' / 'app.db')))
    args = parser.parse_args()
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally overwriting an existing backup.
    with args.destination.open('xb'):
        pass
    try:
        source = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            destination = sqlite3.connect(args.destination)
            try:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('备份完整性检查失败')
            finally:
                destination.close()
        finally:
            source.close()
    except BaseException:
        args.destination.unlink(missing_ok=True)
        raise
    print(args.destination)


if __name__ == '__main__':
    main()
