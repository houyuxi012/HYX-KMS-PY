"""Bounded, atomic client audit storage. Audit failures fail the request closed."""
from contextlib import contextmanager
import logging
import os
import sqlite3
import time
from pathlib import Path

from hyx_kms_budget import KmsSourcePolicy, env_int

loggersrv = logging.getLogger('logsrv')
COLUMNS = 'clientMachineId,machineName,applicationId,skuId,licenseStatus,lastRequestTime,kmsEpid,requestCount'
_CAPACITY_WARNED = set()


def _capacity_warning(count, maximum):
    for threshold in (90, 80):
        if count * 100 >= maximum * threshold:
            if threshold not in _CAPACITY_WARNED:
                _CAPACITY_WARNED.add(threshold)
                loggersrv.warning('Client audit capacity at %d%% (%d/%d); archive records before new clients are refused',
                                  threshold, count, maximum)
            return


@contextmanager
def _private_connection(dbName):
    connection = sqlite3.connect(dbName, timeout=5)
    try:
        if os.name != 'nt' and str(dbName) != ':memory:':
            Path(dbName).chmod(0o600)
        with connection:
            yield connection
    finally:
        connection.close()



def sql_initialize(dbName):
    with _private_connection(dbName) as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TABLE IF NOT EXISTS clients(clientMachineId TEXT, machineName TEXT, applicationId TEXT, skuId TEXT, licenseStatus TEXT, lastRequestTime INTEGER, kmsEpid TEXT, requestCount INTEGER)')
        con.execute('''CREATE TABLE IF NOT EXISTS identity_admission_budget(
            scope TEXT NOT NULL,
            window_id INTEGER NOT NULL,
            used INTEGER NOT NULL CHECK (used >= 0),
            PRIMARY KEY(scope, window_id)
        )''')
        con.execute('''CREATE TABLE IF NOT EXISTS identity_archive(
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
        con.execute('''CREATE TABLE IF NOT EXISTS identity_archive_manifest(
            operationId TEXT PRIMARY KEY,
            archivedAt INTEGER NOT NULL,
            cutoff INTEGER NOT NULL,
            archivedCount INTEGER NOT NULL,
            archivedRequestCount INTEGER NOT NULL,
            operator TEXT NOT NULL,
            reason TEXT NOT NULL
        )''')
        con.execute(
            'CREATE INDEX IF NOT EXISTS identity_archive_identity '
            'ON identity_archive(clientMachineId, applicationId, archivedAt)'
        )
        indices = {row[1] for row in con.execute('PRAGMA index_list(clients)')}
        if 'clients_identity' not in indices:
            duplicates = con.execute('SELECT 1 FROM clients GROUP BY clientMachineId,applicationId HAVING count(*)>1 LIMIT 1').fetchone()
            if duplicates:
                # Preserve the entire pre-migration state before consolidating identities.
                con.execute('CREATE TABLE clients_before_identity_migration AS SELECT * FROM clients')
                con.execute('''CREATE TEMP TABLE merged_clients AS
                    SELECT clientMachineId,machineName,applicationId,skuId,licenseStatus,lastRequestTime,kmsEpid,total_requests AS requestCount
                    FROM (SELECT *,
                        sum(coalesce(requestCount,0)) OVER (PARTITION BY clientMachineId,applicationId) AS total_requests,
                        row_number() OVER (PARTITION BY clientMachineId,applicationId ORDER BY lastRequestTime DESC,rowid DESC) AS identity_rank
                        FROM clients)
                    WHERE identity_rank=1''')
                con.execute('DELETE FROM clients')
                con.execute('INSERT INTO clients SELECT * FROM merged_clients')
                con.execute('DROP TABLE merged_clients')
            con.execute('CREATE UNIQUE INDEX clients_identity ON clients(clientMachineId,applicationId)')
            con.execute('CREATE INDEX clients_last_seen ON clients(lastRequestTime)')


def _consume_identity_budget(con, scope, capacity, window_id):
    cursor = con.execute(
        '''INSERT INTO identity_admission_budget(scope, window_id, used)
           VALUES (?, ?, 1)
           ON CONFLICT(scope, window_id) DO UPDATE SET used=used+1
           WHERE used < ?''',
        (scope, window_id, capacity),
    )
    return cursor.rowcount == 1


def sql_update(dbName, infoDict, source=None):
    maximum = env_int('KMS_MAX_CLIENTS', 10000)
    with _private_connection(dbName) as con:
        con.execute('BEGIN IMMEDIATE')
        exists = con.execute('SELECT 1 FROM clients WHERE clientMachineId=:clientMachineId AND applicationId=:appId', infoDict).fetchone()
        count = None
        if not exists:
            window_id = int(time.time() // 60)
            con.execute(
                'DELETE FROM identity_admission_budget WHERE window_id < ?',
                (window_id - 10,),
            )
            if not _consume_identity_budget(
                    con, 'global', env_int('KMS_NEW_IDENTITY_PER_MIN', 60), window_id):
                raise ValueError('New identity creation budget exhausted; existing clients can still renew')
            if source:
                source_scope = 'source:' + KmsSourcePolicy.source_key(source)
                if not _consume_identity_budget(
                        con, source_scope,
                        env_int('KMS_NEW_IDENTITY_PER_SOURCE_PER_MIN', 10), window_id):
                    raise ValueError('New identity creation budget exhausted; existing clients can still renew')
            count = con.execute('SELECT count(*) FROM clients').fetchone()[0]
            if count >= maximum:
                raise ValueError('Client audit capacity reached; archive records before accepting new identities')
        con.execute('''INSERT INTO clients (clientMachineId,machineName,applicationId,skuId,licenseStatus,lastRequestTime,requestCount)
            VALUES (:clientMachineId,:machineName,:appId,:skuId,:licenseStatus,:requestTime,1)
            ON CONFLICT(clientMachineId,applicationId) DO UPDATE SET
            machineName=excluded.machineName,skuId=excluded.skuId,licenseStatus=excluded.licenseStatus,
            lastRequestTime=excluded.lastRequestTime,requestCount=coalesce(clients.requestCount,0)+1''', infoDict)
        if count is not None:
            _capacity_warning(count + 1, maximum)


def sql_update_epid(dbName, kmsRequest, response, appName):
    with _private_connection(dbName) as con:
        con.execute('UPDATE clients SET kmsEpid=? WHERE clientMachineId=? AND applicationId=?',
                    (response['kmsEpid'].decode('utf-16le'), str(kmsRequest['clientMachineId'].get()), appName))
