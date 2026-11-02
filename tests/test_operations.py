"""Operational backup checks that do not require a running service."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'hyx_kms_py'))
from backup_database import create_backup
from archive_identities import archive_identities
from restore_database import restore_backup, verify_backup


class BackupTests(unittest.TestCase):
    def test_online_backup_is_consistent_private_and_manifested(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.db'
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute(
                    'CREATE TABLE clients(clientMachineId TEXT, applicationId TEXT)'
                )
                connection.executemany(
                    'INSERT INTO clients VALUES (?, ?)',
                    [('one', 'Windows'), ('two', 'Office')],
                )
            destination = Path(directory) / 'backup.db'
            manifest = create_backup(source, destination)
            self.assertEqual(manifest['integrity'], 'ok')
            self.assertEqual(manifest['clientCount'], 2)
            self.assertEqual(manifest['sha256'],
                             hashlib.sha256(destination.read_bytes()).hexdigest())
            if os.name != 'nt':
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
                self.assertEqual(destination.with_suffix('.db.json').stat().st_mode & 0o777, 0o600)
            stored = json.loads(destination.with_suffix('.db.json').read_text(encoding='utf-8'))
            self.assertEqual(stored, manifest)
            with closing(sqlite3.connect(destination)) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(connection.execute('SELECT count(*) FROM clients').fetchone()[0], 2)

    def test_restore_requires_acknowledgement_and_round_trips_verified_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.db'
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute(
                    'CREATE TABLE clients(clientMachineId TEXT, applicationId TEXT, requestCount INTEGER)'
                )
                connection.execute("INSERT INTO clients VALUES ('one', 'Windows', 7)")
            backup = Path(directory) / 'backup.db'
            create_backup(source, backup)
            verified, _, manifest = verify_backup(backup)
            self.assertEqual(verified, backup.resolve())
            self.assertEqual(manifest['clientCount'], 1)
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute("UPDATE clients SET requestCount=99")

            with self.assertRaisesRegex(ValueError, 'Stop the KMS and web services'):
                restore_backup(backup, source)
            result = restore_backup(backup, source, service_stopped=True)
            self.assertEqual(result['clientCount'], 1)
            self.assertTrue(Path(result['preRestoreBackup']).is_file())
            with closing(sqlite3.connect(source)) as connection:
                self.assertEqual(connection.execute('SELECT requestCount FROM clients').fetchone()[0], 7)
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            if os.name != 'nt':
                self.assertEqual(source.stat().st_mode & 0o777, 0o600)

    def test_restore_rejects_tampering_and_requires_sidecar_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.db'
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute('CREATE TABLE clients(clientMachineId TEXT, applicationId TEXT)')
                connection.execute("INSERT INTO clients VALUES ('one', 'Windows')")
            backup = Path(directory) / 'backup.db'
            create_backup(source, backup)
            destination = Path(directory) / 'destination.db'
            stale = Path(str(destination) + '-wal')
            stale.write_bytes(b'stale')
            with self.assertRaisesRegex(ValueError, 'discard-stale-sidecars'):
                restore_backup(backup, destination, service_stopped=True)
            restore_backup(
                backup, destination, service_stopped=True, discard_stale_sidecars=True,
            )
            self.assertFalse(stale.exists())
            with backup.open('ab') as handle:
                handle.write(b'tampered')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                verify_backup(backup)


class IdentityArchiveTests(unittest.TestCase):
    def test_archive_is_dry_run_by_default_and_preserves_audit_totals(self):
        from hyx_kms_sql import sql_initialize, sql_update

        now = 200 * 86400
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, KMS_MAX_CLIENTS='2'):
            database = Path(directory) / 'clients.db'
            sql_initialize(database)
            base = dict(
                machineName='host', appId='Windows', skuId='SKU',
                licenseStatus='Activated',
            )
            sql_update(database, dict(
                base, clientMachineId='old', requestTime=1,
            ))
            sql_update(database, dict(
                base, clientMachineId='recent', requestTime=now - 1,
            ))
            dry_run = archive_identities(
                database, 30, 'operator', 'retention policy', now=now,
            )
            self.assertTrue(dry_run['dryRun'])
            self.assertEqual(dry_run['eligibleCount'], 1)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM clients').fetchone()[0], 2)

            result = archive_identities(
                database, 30, 'operator', 'retention policy',
                confirm=True, now=now,
            )
            self.assertEqual(result['eligibleCount'], 1)
            self.assertEqual(result['eligibleRequestCount'], 1)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute('SELECT clientMachineId FROM clients').fetchall(),
                    [('recent',)],
                )
                self.assertEqual(
                    connection.execute(
                        'SELECT clientMachineId,requestCount,archiveReason '
                        'FROM identity_archive'
                    ).fetchone(),
                    ('old', 1, 'retention policy'),
                )
                self.assertEqual(
                    connection.execute(
                        'SELECT archivedCount,archivedRequestCount,operator '
                        'FROM identity_archive_manifest'
                    ).fetchone(),
                    (1, 1, 'operator'),
                )
            sql_update(database, dict(
                base, clientMachineId='replacement', requestTime=now,
            ))

    def test_archive_permission_failure_rolls_back_before_commit(self):
        from hyx_kms_sql import sql_initialize, sql_update

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, KMS_MAX_CLIENTS='2'):
            database = Path(directory) / 'clients.db'
            sql_initialize(database)
            base = dict(
                machineName='host', appId='Windows', skuId='SKU',
                licenseStatus='Activated', requestTime=1,
            )
            sql_update(database, dict(base, clientMachineId='old'))
            with patch.object(Path, 'chmod', side_effect=PermissionError('read-only')):
                with self.assertRaises(PermissionError):
                    archive_identities(
                        database, 30, 'operator', 'retention policy',
                        confirm=True, now=200 * 86400,
                    )
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute('SELECT clientMachineId FROM clients').fetchall(),
                    [('old',)],
                )
                self.assertEqual(
                    connection.execute('SELECT count(*) FROM identity_archive').fetchone()[0],
                    0,
                )


class ContainerLaunchTests(unittest.TestCase):
    def test_run_script_defaults_web_to_https_443_with_hardened_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dump = directory / 'docker-args.txt'
            docker = directory / 'docker'
            docker.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$HYX_DOCKER_ARGS"\n',
                encoding='utf-8',
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                'PATH': str(directory) + os.pathsep + environment['PATH'],
                'HYX_DOCKER_ARGS': str(dump),
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '127.0.0.0/8',
            })
            result = subprocess.run(
                ['bash', str(ROOT / 'docker/hyx-kms-py/run.sh')],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = dump.read_text(encoding='utf-8').splitlines()
            self.assertIn('127.0.0.1:443:8080', arguments)
            self.assertIn('127.0.0.1:1688:1688', arguments)
            self.assertIn('--read-only', arguments)
            self.assertIn('--cap-drop=ALL', arguments)
            self.assertIn('--security-opt=no-new-privileges:true', arguments)
            self.assertIn('LOGFILE=STDOUT', arguments)
            self.assertFalse(any('WEB_AUTH' in argument for argument in arguments))
            self.assertFalse(any('HYX-KMS-PY-auth' in argument for argument in arguments))
            self.assertEqual(arguments[-1], 'hyx-kms-py:latest')

    def test_run_script_uses_explicit_release_image(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dump = directory / 'docker-args.txt'
            docker = directory / 'docker'
            docker.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$HYX_DOCKER_ARGS"\n',
                encoding='utf-8',
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                'PATH': str(directory) + os.pathsep + environment['PATH'],
                'HYX_DOCKER_ARGS': str(dump),
                'HYX_KMS_IMAGE': 'hyx-kms-py:2026.11.02-rc.2-amd64',
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '127.0.0.0/8',
            })
            result = subprocess.run(
                ['bash', str(ROOT / 'docker/hyx-kms-py/run.sh')],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = dump.read_text(encoding='utf-8').splitlines()
        self.assertEqual(arguments[-1], 'hyx-kms-py:2026.11.02-rc.2-amd64')


if __name__ == '__main__':
    unittest.main()
