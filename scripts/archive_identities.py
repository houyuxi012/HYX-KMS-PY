#!/usr/bin/env python3
"""Move old client identities into an auditable archive without losing counters."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


CLIENT_COLUMNS = (
    'clientMachineId', 'machineName', 'applicationId', 'skuId',
    'licenseStatus', 'lastRequestTime', 'kmsEpid', 'requestCount',
)


def _ensure_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS identity_archive(
        archiveId INTEGER PRIMARY KEY AUTOINCREMENT,
        operationId TEXT NOT NULL,
        clientMachineId TEXT NOT NULL,
        machineName TEXT,
        applicationId TEXT NOT NULL,
        skuId TEXT,
        licenseStatus TEXT,
        lastRequestTime INTEGER,
        kmsEpid TEXT,
        requestCount INTEGER,
        archivedAt INTEGER NOT NULL,
        archiveReason TEXT NOT NULL
    )''')
    connection.execute('''CREATE TABLE IF NOT EXISTS identity_archive_manifest(
        operationId TEXT PRIMARY KEY,
        archivedAt INTEGER NOT NULL,
        cutoff INTEGER NOT NULL,
        archivedCount INTEGER NOT NULL,
        archivedRequestCount INTEGER NOT NULL,
        operator TEXT NOT NULL,
        reason TEXT NOT NULL
    )''')
    connection.execute(
        'CREATE INDEX IF NOT EXISTS identity_archive_identity '
        'ON identity_archive(clientMachineId, applicationId, archivedAt)'
    )


def archive_identities(
        database, older_than_days, operator, reason, confirm=False,
        limit=1000, now=None):
    database = Path(database).resolve(strict=True)
    if not 1 <= older_than_days <= 3650:
        raise ValueError('older_than_days must be 1..3650')
    if not 1 <= limit <= 100000:
        raise ValueError('limit must be 1..100000')
    operator = operator.strip()
    reason = reason.strip()
    if (
            not operator or not reason or
            len(operator) > 128 or len(reason) > 512 or
            not operator.isprintable() or not reason.isprintable()):
        raise ValueError('operator and reason are required')
    now = int(time.time() if now is None else now)
    cutoff = now - older_than_days * 86400
    operation_id = str(uuid.uuid4())

    with closing(sqlite3.connect(database, timeout=10)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        _ensure_schema(connection)
        rows = connection.execute(
            'SELECT rowid,%s FROM clients '
            'WHERE coalesce(lastRequestTime,0) < ? '
            'ORDER BY lastRequestTime,rowid LIMIT ?' % ','.join(CLIENT_COLUMNS),
            (cutoff, limit),
        ).fetchall()
        archived_count = len(rows)
        archived_requests = sum(int(row[-1] or 0) for row in rows)
        result = {
            'format': 'HYX-KMS-PY-identity-archive-v1',
            'operationId': operation_id,
            'dryRun': not confirm,
            'database': str(database),
            'cutoff': cutoff,
            'olderThanDays': older_than_days,
            'eligibleCount': archived_count,
            'eligibleRequestCount': archived_requests,
            'operator': operator,
            'reason': reason,
        }
        if not confirm:
            connection.rollback()
            return result

        connection.executemany(
            '''INSERT INTO identity_archive(
                operationId,clientMachineId,machineName,applicationId,skuId,
                licenseStatus,lastRequestTime,kmsEpid,requestCount,
                archivedAt,archiveReason
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            [tuple([operation_id] + list(row[1:]) + [now, reason]) for row in rows],
        )
        connection.executemany('DELETE FROM clients WHERE rowid=?', [(row[0],) for row in rows])
        connection.execute(
            '''INSERT INTO identity_archive_manifest(
                operationId,archivedAt,cutoff,archivedCount,archivedRequestCount,operator,reason
            ) VALUES (?,?,?,?,?,?,?)''',
            (operation_id, now, cutoff, archived_count, archived_requests, operator, reason),
        )
        if os.name != 'nt':
            Path(database).chmod(0o600)
        connection.commit()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--older-than-days', type=int, required=True)
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument(
        '--confirm', action='store_true',
        help='apply the archive transaction; without this flag only count eligible rows',
    )
    args = parser.parse_args()
    try:
        result = archive_identities(
            args.database, args.older_than_days, args.operator, args.reason,
            confirm=args.confirm, limit=args.limit,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        print('archive failed: %s' % error, file=__import__('sys').stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
