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
    def run_with_fake_executable(self, script, executable, updates):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dump = directory / 'arguments.txt'
            fake = directory / executable
            fake.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$HYX_COMMAND_ARGS"\n',
                encoding='utf-8',
            )
            fake.chmod(0o755)
            environment = os.environ.copy()
            for name in (
                'HYX_KMS_IMAGE', 'KMS_BIND_ADDRESS', 'KMS_HEALTH_HOST',
                'KMS_IPV6', 'KMS_IPV6_PUBLISH_ADDRESS', 'KMS_PUBLISH_ADDRESS',
                'WEB_IPV6', 'WEB_IPV6_PUBLISH_ADDRESS', 'WEB_PUBLISH_ADDRESS',
            ):
                environment.pop(name, None)
            environment.update(updates)
            environment.update({
                'PATH': str(directory) + os.pathsep + environment['PATH'],
                'HYX_COMMAND_ARGS': str(dump),
            })
            result = subprocess.run(
                ['bash', str(script)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            arguments = dump.read_text(encoding='utf-8').splitlines() if dump.exists() else []
            return result, arguments

    def test_run_script_defaults_web_to_https_443_with_hardened_runtime(self):
        result, arguments = self.run_with_fake_executable(
            ROOT / 'docker/hyx-kms-py/run.sh',
            'docker',
            {
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '127.0.0.0/8',
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('127.0.0.1:443:8080', arguments)
        self.assertIn('127.0.0.1:1688:1688', arguments)
        self.assertIn('--read-only', arguments)
        self.assertIn('--cap-drop=ALL', arguments)
        self.assertIn('--security-opt=no-new-privileges:true', arguments)
        self.assertIn('LOGFILE=STDOUT', arguments)
        self.assertIn('KMS_HEALTH_HOST=', arguments)
        self.assertIn('KMS_IPV6=false', arguments)
        self.assertFalse(any('WEB_AUTH' in argument for argument in arguments))
        self.assertFalse(any('HYX-KMS-PY-auth' in argument for argument in arguments))
        self.assertEqual(arguments[-1], 'hyx-kms-py:latest')

    def test_run_script_uses_explicit_release_image(self):
        result, arguments = self.run_with_fake_executable(
            ROOT / 'docker/hyx-kms-py/run.sh',
            'docker',
            {
                'HYX_KMS_IMAGE': 'hyx-kms-py:2026.11.02-rc.3-amd64',
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '127.0.0.0/8',
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(arguments[-1], 'hyx-kms-py:2026.11.02-rc.3-amd64')

    def test_run_script_publishes_dual_stack_ports(self):
        result, arguments = self.run_with_fake_executable(
            ROOT / 'docker/hyx-kms-py/run.sh',
            'docker',
            {
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '10.0.0.0/8,2001:db8::/32',
                'KMS_IPV6': 'true',
                'WEB_IPV6': 'true',
                'KMS_PUBLISH_ADDRESS': '0.0.0.0',
                'WEB_PUBLISH_ADDRESS': '0.0.0.0',
                'KMS_IPV6_PUBLISH_ADDRESS': '2001:db8::10',
                'WEB_IPV6_PUBLISH_ADDRESS': '[2001:db8::20]',
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-p', arguments)
        self.assertIn('0.0.0.0:1688:1688', arguments)
        self.assertIn('[2001:db8::10]:1688:1688', arguments)
        self.assertIn('0.0.0.0:443:8080', arguments)
        self.assertIn('[2001:db8::20]:443:8080', arguments)
        self.assertIn('KMS_IPV6=true', arguments)

    def test_run_script_ipv6_publish_defaults_to_loopback(self):
        result, arguments = self.run_with_fake_executable(
            ROOT / 'docker/hyx-kms-py/run.sh',
            'docker',
            {
                'WEB_TLS_VOLUME': 'test-tls',
                'WEB_TLS_SERVER_NAME': 'localhost',
                'KMS_ALLOWED_NETWORKS': '127.0.0.0/8,::1/128',
                'KMS_IPV6': 'true',
                'WEB_IPV6': 'true',
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[::1]:1688:1688', arguments)
        self.assertIn('[::1]:443:8080', arguments)
        self.assertNotIn('[::]:1688:1688', arguments)
        self.assertNotIn('[::]:443:8080', arguments)

    def container_start_arguments(self, ip_address):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = ROOT / 'docker/hyx-kms-py/start.sh'
            script = directory / 'start.sh'
            script.write_text(
                source.read_text(encoding='utf-8').replace(
                    '/opt/HYX-KMS-PY', str(ROOT),
                ),
                encoding='utf-8',
            )
            result, arguments = self.run_with_fake_executable(
                script,
                'python3',
                {
                    'IP': ip_address,
                    'PORT': '1688',
                    'KMS_IPV6': 'true',
                    'SQLITE': 'false',
                    'LCID': '1033',
                    'CLIENT_COUNT': '26',
                    'ACTIVATION_INTERVAL': '120',
                    'RENEWAL_INTERVAL': '10080',
                    'HWID': '364F463A8863D35F',
                    'LOGLEVEL': 'INFO',
                    'LOGFILE': 'STDOUT',
                },
            )
        return result, arguments

    def test_container_start_script_adds_matching_ipv6_listener(self):
        result, arguments = self.container_start_arguments('0.0.0.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        listener_index = arguments.index('connect')
        self.assertEqual(arguments[listener_index:listener_index + 3], [
            'connect', '-n', '::,1688',
        ])

    def test_container_start_script_keeps_loopback_additions_local(self):
        for primary, expected in (
            ('::', '0.0.0.0,1688'),
            ('127.0.0.1', '::1,1688'),
            ('::1', '127.0.0.1,1688'),
        ):
            with self.subTest(primary=primary):
                result, arguments = self.container_start_arguments(primary)
                self.assertEqual(result.returncode, 0, result.stderr)
                listener_index = arguments.index('connect')
                self.assertEqual(arguments[listener_index:listener_index + 3], [
                    'connect', '-n', expected,
                ])


if __name__ == '__main__':
    unittest.main()
