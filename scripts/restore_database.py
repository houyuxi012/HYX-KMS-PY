#!/usr/bin/env python3
"""Verify and atomically restore a manifested HYX-KMS-PY SQLite backup."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from backup_database import create_backup


FORMAT = 'HYX-KMS-PY-backup-v1'


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(backup):
    backup = Path(backup).resolve(strict=True)
    manifest_path = backup.with_suffix(backup.suffix + '.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != FORMAT:
        raise ValueError('Unsupported backup manifest format')
    if manifest.get('backup') != backup.name:
        raise ValueError('Backup manifest does not describe this file')
    if not isinstance(manifest.get('sha256'), str) or _sha256(backup) != manifest['sha256']:
        raise ValueError('Backup SHA256 does not match its manifest')
    if manifest.get('integrity') != 'ok':
        raise ValueError('Backup manifest does not record a successful integrity check')
    with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as connection:
        result = connection.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise ValueError('Backup integrity check failed: %s' % result)
        if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clients'"
        ).fetchone() is None:
            raise ValueError('Backup does not contain the clients table')
        client_count = connection.execute('SELECT count(*) FROM clients').fetchone()[0]
    if manifest.get('clientCount') != client_count:
        raise ValueError('Backup client count does not match its manifest')
    return backup, manifest_path, manifest


def restore_backup(backup, destination, service_stopped=False, discard_stale_sidecars=False):
    if not service_stopped:
        raise ValueError('Stop the KMS and web services before restoring a database')
    backup, manifest_path, manifest = verify_backup(backup)
    destination = Path(destination).resolve()
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if backup == destination:
        raise ValueError('Backup and destination must be different files')

    sidecars = [Path(str(destination) + suffix) for suffix in ('-wal', '-shm', '-journal')]
    stale_sidecars = [path for path in sidecars if path.exists()]
    if stale_sidecars and not discard_stale_sidecars:
        raise ValueError(
            'Stale SQLite sidecar files exist; confirm the service is stopped and use '
            '--discard-stale-sidecars: ' + ', '.join(map(str, stale_sidecars))
        )

    previous = None
    previous_owner = None
    if destination.exists():
        stat_result = destination.stat()
        previous_owner = (stat_result.st_uid, stat_result.st_gid)
        previous = create_backup(
            destination,
            destination.with_name(
                destination.name + '.pre-restore-'
                + manifest['createdAt'].replace(':', '').replace('+', '_').replace('.', '-')
            ),
        )

    fd, temporary_name = tempfile.mkstemp(
        prefix='.' + destination.name + '.restore-', suffix='.tmp', dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as source, \
             closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Restored temporary database failed integrity check')
            restored_count = target.execute('SELECT count(*) FROM clients').fetchone()[0]
            if restored_count != manifest['clientCount']:
                raise RuntimeError('Restored temporary database has an unexpected client count')
        os.chmod(temporary, 0o600)
        if previous_owner is not None and hasattr(os, 'chown'):
            os.chown(temporary, *previous_owner)
        with temporary.open('rb+') as handle:
            os.fsync(handle.fileno())
        for path in stale_sidecars:
            path.unlink()
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return {
        'format': 'HYX-KMS-PY-restore-v1',
        'backup': str(backup),
        'backupManifest': str(manifest_path),
        'destination': str(destination),
        'clientCount': manifest['clientCount'],
        'sha256': _sha256(backup),
        'preRestoreBackup': str(destination.parent / previous['backup']) if previous else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('backup', help='verified backup database path')
    parser.add_argument('destination', help='destination SQLite database path')
    parser.add_argument(
        '--service-stopped', action='store_true',
        help='required acknowledgement that KMS and web services are stopped',
    )
    parser.add_argument(
        '--discard-stale-sidecars', action='store_true',
        help='remove stale -wal, -shm and -journal files after the stopped-service acknowledgement',
    )
    args = parser.parse_args()
    try:
        result = restore_backup(
            args.backup,
            args.destination,
            service_stopped=args.service_stopped,
            discard_stale_sidecars=args.discard_stale_sidecars,
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print('restore failed: %s' % error, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
