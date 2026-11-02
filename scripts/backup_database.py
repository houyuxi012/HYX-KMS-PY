#!/usr/bin/env python3
"""Create and verify a consistent online SQLite backup with a SHA256 manifest."""
import argparse
from contextlib import closing
import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == destination:
        raise ValueError('Backup destination must differ from the source database')
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix='.' + destination.name + '.', suffix='.tmp', dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as source_db:
            with closing(sqlite3.connect(temporary)) as backup_db:
                source_db.backup(backup_db)
                backup_db.execute('PRAGMA journal_mode=DELETE')
                result = backup_db.execute('PRAGMA integrity_check').fetchone()[0]
                if result != 'ok':
                    raise RuntimeError('Backup integrity check failed: %s' % result)
                if backup_db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clients'"
                ).fetchone() is None:
                    raise RuntimeError('Backup does not contain the clients table')
                client_count = backup_db.execute('SELECT count(*) FROM clients').fetchone()[0]
        os.chmod(temporary, 0o600)
        with temporary.open('rb+') as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    manifest = {
        'format': 'HYX-KMS-PY-backup-v1',
        'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': str(source),
        'backup': destination.name,
        'sha256': _sha256(destination),
        'clientCount': client_count,
        'integrity': 'ok',
    }
    manifest_path = destination.with_suffix(destination.suffix + '.json')
    manifest_temporary = manifest_path.with_name('.' + manifest_path.name + '.tmp')
    manifest_temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    os.chmod(manifest_temporary, 0o600)
    os.replace(manifest_temporary, manifest_path)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='running SQLite database')
    parser.add_argument('destination', help='new backup database path')
    args = parser.parse_args()
    manifest = create_backup(args.source, args.destination)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
