import copy
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hyx_kms_py'))

import hyx_kms_client as client
from hyx_kms_db2dict import kmsDB2Dict
from hyx_kms_format import enco
from hyx_kms_pid_generator import epidGenerator
from hyx_kms_request_v4 import kmsRequestV4
from hyx_kms_request_v5 import kmsRequestV5
from hyx_kms_request_v6 import kmsRequestV6


class WindowsSupportTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch.dict(client.clt_config, clear=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        for module in ('hyx_kms_client', 'hyx_kms_base', 'hyx_kms_request_v4', 'hyx_kms_request_v5'):
            printer = patch(module + '.pretty_printer')
            printer.start()
            self.addCleanup(printer.stop)
        self.server_config = {
            'clientcount': None, 'epid': None, 'lcid': 1033,
            'activation': 120, 'renewal': 10080, 'sqlite': False,
            'loglevel': 'ERROR', 'hwid': bytes.fromhex('364F463A8863D35F'),
        }

    def configure(self, mode):
        client.clt_config.clear()
        client.clt_config.update(mode=mode, cmid='f4c99868-f91f-4e99-94f1-3fe1a49f4ced', machine='KMS-TEST', call_id=1)
        client.client_update()

    def roundtrip(self):
        major = client.clt_config['KMSProtocolMajorVersion']
        handler_class = {4: kmsRequestV4, 5: kmsRequestV5, 6: kmsRequestV6}[major]
        request = client.createKmsRequest()
        handler = handler_class(enco(str(request), 'latin-1'), self.server_config)
        with patch('hyx_kms_request_v4.time.sleep'), patch('hyx_kms_base.loggersrv.info') as log:
            wire_response = handler.executeRequestLogic()
        decoded = client.readKmsResponse(enco(wire_response, 'latin-1'), request, client.clt_config)
        response = decoded['response']
        self.assertEqual(response['versionMajor'], major)
        self.assertEqual(response['currentClientCount'], client.clt_config['RequiredClientCount'] * 2)
        self.assertEqual(response['vLActivationInterval'], 120)
        self.assertEqual(response['vLRenewalInterval'], 10080)
        self.assertEqual(response['clientMachineId'].get(), uuid.UUID(client.clt_config['cmid']))
        return response, log

    def test_all_client_modes_roundtrip(self):
        for mode in client.clt_options['mode']['choi']:
            with self.subTest(mode=mode):
                self.configure(mode)
                self.roundtrip()

    def test_windows11_reuses_windows10_identifiers(self):
        self.configure('Windows10')
        expected = dict(client.clt_config)
        self.configure('Windows11')
        for field in ('KMSClientSkuID', 'KMSClientAppID', 'KMSClientKMSCountedID'):
            self.assertEqual(client.clt_config[field], expected[field])
        self.assertEqual(client.clt_config['RequiredClientCount'], 25)
        self.assertEqual(client.clt_config['KMSProtocolMajorVersion'], 6)

    def test_documented_windows11_editions_roundtrip(self):
        keys_section = (ROOT / 'docs/Keys.md').read_text().split('### Windows 11\n')[1].split('### Windows Server 2025')[0]
        keys = re.findall(r'`([A-Z0-9-]{29})`', keys_section)
        self.assertEqual(len(keys), 14)
        windows = next(app for app in kmsDB2Dict()[2] if app['DisplayName'] == 'Windows')
        for key in keys:
            with self.subTest(gvlk=key):
                matches = [(kms, sku) for kms in windows['KmsItems'] for sku in kms['SkuItems'] if sku.get('Gvlk') == key]
                self.assertEqual(len(matches), 1)
                kms, sku = matches[0]
                self.configure('Windows11')
                client.clt_config.update(KMSClientSkuID=sku['Id'], KMSClientKMSCountedID=kms['Id'])
                self.roundtrip()

    def test_server2025_skus_and_epid(self):
        expected = {
            '7dc26449-db21-4e09-ba37-28f2958506a6': 'TVRH6-WHNXV-R9WG3-9XRFY-MY832',
            'c052f164-cdf6-409a-a0cb-853ba0f0f55a': 'D764K-2NDRG-47T6Q-P8T8W-YP6DF',
            'c2e946d1-cfa2-4523-8c87-30bc696ee584': 'XGN3F-F394H-FD2MY-PP6FD-8MCRC',
        }
        kms = next(kms for app in kmsDB2Dict()[2] for kms in app['KmsItems'] if kms['DisplayName'] == 'Windows Server 2025')
        self.assertEqual(kms['Id'], '907f1f65-adcd-4a2e-95bc-4bf500bc6e58')
        self.assertEqual({sku['Id']: sku['Gvlk'] for sku in kms['SkuItems']}, expected)
        for sku in kms['SkuItems']:
            with self.subTest(sku=sku['DisplayName']):
                self.configure('WindowsServer2025')
                self.assertEqual(client.clt_config['KMSClientSkuID'], '7dc26449-db21-4e09-ba37-28f2958506a6')
                self.assertEqual(client.clt_config['RequiredClientCount'], 5)
                client.clt_config['KMSClientSkuID'] = sku['Id']
                response, log = self.roundtrip()
                log.assert_any_call('SKU ID: ' + sku['DisplayName'])
                self.assert_server2025_epid(response['kmsEpid'].encode('latin-1').decode('utf-16le'))

    def test_office_modes_select_professional_plus(self):
        expected = {
            'Office2021': (
                '86d50b16-4808-41af-b83b-b338274318b2',
                'fbdb3e18-a8ef-4fb3-9183-dffd60bd0984',
                'Office LTSC Professional Plus 2021',
            ),
            'Office2024': (
                'a8973cb5-bf03-0a4c-9cef-703099645ab3',
                '8d368fc1-9470-4be2-8d66-90e836cbb051',
                'Office LTSC Professional Plus 2024',
            ),
        }
        for mode, (counted_id, sku_id, sku_name) in expected.items():
            with self.subTest(mode=mode):
                self.configure(mode)
                self.assertEqual(client.clt_config['KMSClientKMSCountedID'], counted_id)
                self.assertEqual(client.clt_config['KMSClientSkuID'], sku_id)
                self.assertEqual(client.clt_config['RequiredClientCount'], 5)
                self.assertEqual(client.clt_config['KMSProtocolMajorVersion'], 6)
                _, log = self.roundtrip()
                log.assert_any_call('Application ID: Office 2013 and later')
                log.assert_any_call('SKU ID: ' + sku_name)

    def test_documented_office_gvlks_resolve_uniquely(self):
        keys_document = (ROOT / 'docs/Keys.md').read_text()
        expected_gvlks = {
            'Office 2024': {
                '4NKHF-9HBQF-Q3B6C-7YV34-F64P3',
                '82FTR-NCHR7-W3944-MGRHM-JMCWD',
                'B7TN8-FJ8V3-7QYCP-HQPMV-YY89G',
                'CW94N-K6GJH-9CTXY-MG2VC-FYCWP',
                'D2F8D-N3Q3B-J28PV-X27HD-RJWB9',
                'F4DYN-89BP2-WQTWJ-GR8YC-CKGJG',
                'FQQ23-N4YCY-73HQ3-FM9WC-76HF4',
                'JMMVY-XFNQC-KK4HK-9H7R3-WQQTV',
                'MQ84N-7VYDM-FXV7C-6K7CC-VFW9J',
                'PD3TT-NTHQQ-VC7CY-MFXK3-G87F8',
                'V28N4-JG22K-W66P8-VTMGK-H6HGR',
                'XJ2XN-FW8RK-P4HMP-DKDBV-GCVGB',
            },
            'Office 2021': {
                '2MW9D-N4BXM-9VBPG-Q7W6M-KFBGQ',
                'C9FM6-3N72F-HFJXB-TM3V9-T86R9',
                'FTNWT-C6WBT-8HMGF-K9PRX-QV9H8',
                'FXYTK-NJJ8C-GB6DW-3DYQT-6F7TH',
                'HWCXN-K3WBT-WJBKY-R8BD9-XK29P',
                'J2JDC-NJCYY-9RGQ4-YXWMH-T3D4T',
                'KDX7X-BNVR8-TXXGX-4Q7Y8-78VT3',
                'KNH8D-FGHT4-T8RK3-CTDYJ-K2HT4',
                'MJVNY-BYWPY-CWV6J-2RKRT-4M8QG',
                'NWG3X-87C9K-TC7YY-BC2G7-G6RVC',
                'TN8H9-M34D3-Y64V9-TR72V-X79KV',
                'TY7XF-NFRBR-KJ44C-G83KF-GX27K',
                'WM8YG-YNGDD-4JHDC-PG3F4-FC4T4',
            },
        }
        sections = {
            'Office 2024': (
                keys_document.split('### Office 2024\n')[1].split('### Office 2021')[0],
                12,
            ),
            'Office 2021': (
                keys_document.split('### Office 2021\n')[1].split('### Office 2019')[0],
                13,
            ),
        }
        database = kmsDB2Dict()
        for display_name, (section, expected_count) in sections.items():
            keys = re.findall(r'`([A-Z0-9-]{29})`', section)
            self.assertEqual(len(keys), expected_count)
            self.assertEqual(set(keys), expected_gvlks[display_name])
            kms = next(
                item
                for app in database[2]
                for item in app['KmsItems']
                if item['DisplayName'] == display_name
            )
            for key in keys:
                with self.subTest(product=display_name, gvlk=key):
                    matches = [
                        (item, sku)
                        for app in database[2]
                        for item in app['KmsItems']
                        for sku in item['SkuItems']
                        if sku.get('Gvlk') == key
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertIs(matches[0][0], kms)

    def test_office_csvlk_metadata(self):
        expected = {
            'f3d89bbf-c0ec-47ce-a8fa-e5a5f97e447f': (
                'Office 2024',
                'a8973cb5-bf03-0a4c-9cef-703099645ab3',
                (591000000, 610999999),
                '[0,1,2,3,4]',
            ),
            '47f3b983-7c53-4d45-abc6-bcd91e2dd90a': (
                'Office 2021',
                '86d50b16-4808-41af-b83b-b338274318b2',
                (571000000, 590999999),
                '[0,1,2,3]',
            ),
        }
        csvlks = {item['Id'].lower(): item for item in kmsDB2Dict()[1]}
        for activation_id, (display_name, counted_id, key_range, invalid_builds) in expected.items():
            with self.subTest(product=display_name):
                item = csvlks[activation_id]
                self.assertEqual(item['DisplayName'], display_name)
                self.assertEqual(item['Activate'], [counted_id])
                self.assertEqual((int(item['MinKeyId']), int(item['MaxKeyId'])), key_range)
                self.assertEqual(item['InvalidWinBuild'], invalid_builds)

    def test_office_epid_uses_product_specific_range_and_compatible_host(self):
        expected = {
            '86d50b16-4808-41af-b83b-b338274318b2': (571000000, 590999999),
            'a8973cb5-bf03-0a4c-9cef-703099645ab3': (591000000, 610999999),
        }
        with patch('hyx_kms_pid_generator.random.choice', side_effect=lambda values: values[-1]):
            for kms_id, (minimum, maximum) in expected.items():
                with self.subTest(kms_id=kms_id):
                    epid = epidGenerator(uuid.UUID(kms_id), 6, 1033)
                    parts = epid.split('-')
                    self.assertEqual(parts[0:2], ['03612', '00206'])
                    self.assertTrue(minimum <= int(parts[2] + parts[3]) <= maximum)
                    self.assertEqual(parts[6], '26100.0000')

    def assert_server2025_epid(self, epid):
        parts = epid.split('-')
        self.assertEqual(parts[0:2], ['03612', '04919'])
        self.assertTrue(20000 <= int(parts[2] + parts[3]) <= 20019999)
        self.assertEqual(parts[6], '26100.0000')

    def test_epid_never_mixes_unrelated_product_or_host(self):
        # Choosing the last candidate exposes the old per-item fallback bug.
        with patch('hyx_kms_pid_generator.random.choice', side_effect=lambda values: values[-1]):
            self.assert_server2025_epid(epidGenerator(uuid.UUID('907f1f65-adcd-4a2e-95bc-4bf500bc6e58'), 6, 1033))

    def test_unknown_product_epid_keeps_fallback(self):
        epid = epidGenerator(uuid.UUID(int=1), 6, 1033)
        parts = epid.split('-')
        self.assertEqual(parts[1], '00206')
        self.assertTrue(551000000 <= int(parts[2] + parts[3]) <= 570999999)

    def test_no_compatible_host_fails_explicitly(self):
        database = copy.deepcopy(kmsDB2Dict())
        database[0] = [build for build in database[0] if build.get('BuildNumber') != '26100']
        with patch('hyx_kms_pid_generator.kmsDB2Dict', return_value=database):
            with self.assertRaisesRegex(ValueError, 'No compatible KMS host build'):
                epidGenerator(uuid.UUID('907f1f65-adcd-4a2e-95bc-4bf500bc6e58'), 6, 1033)

    def test_unknown_sku_and_application_do_not_crash(self):
        for unknown_app in (False, True):
            with self.subTest(unknown_app=unknown_app):
                self.configure('Windows11')
                client.clt_config['KMSClientSkuID'] = str(uuid.UUID(int=1))
                if unknown_app:
                    client.clt_config['KMSClientAppID'] = str(uuid.UUID(int=2))
                _, log = self.roundtrip()
                log.assert_any_call('SKU ID: ' + str(uuid.UUID(int=1)))
                log.assert_any_call('Application ID: ' + (str(uuid.UUID(int=2)) if unknown_app else 'Windows'))

    def test_missing_mode_fails_before_connection(self):
        with self.assertRaisesRegex(ValueError, 'No default SKU found'):
            self.configure('UnsupportedProduct')

    def test_machine_name_control_characters_escaped_in_logs(self):
        self.configure('Windows11')
        client.clt_config['machine'] = 'A\nB\x1bC'
        major = client.clt_config['KMSProtocolMajorVersion']
        handler_class = {4: kmsRequestV4, 5: kmsRequestV5, 6: kmsRequestV6}[major]
        request = client.createKmsRequest()
        handler = handler_class(enco(str(request), 'latin-1'), self.server_config)
        # Drive the server path without the usual log mock so assertLogs sees real records.
        with patch('hyx_kms_request_v4.time.sleep'), self.assertLogs('logsrv', level='INFO') as logs:
            handler.executeRequestLogic()
        records = [line for line in logs.output if 'Machine Name' in line]
        self.assertEqual(len(records), 1)
        self.assertNotIn('\n', records[0])
        self.assertIn('\\n', records[0])
        self.assertIn('\\u001b', records[0])

    def test_new_modes_over_loopback_with_sqlite(self):
        import hyx_kms_server as server

        with tempfile.TemporaryDirectory(prefix='kms-windows-') as tmp, patch.dict(server.srv_config, clear=True):
            database = str(Path(tmp) / 'requests.db')
            server.srv_config.update(self.server_config, sqlite=database, timeoutsndrcv=3)
            listener = server.KeyServer([('127.0.0.1', 0, 5, False)], server.kmsServerHandler)
            port = listener.multisock.getsockname()[1]
            server.srv_config['port'] = port
            worker = threading.Thread(target=listener.hyx_kms_serve, daemon=True)
            worker.start()
            try:
                modes = (
                    ('Windows11', 50),
                    ('WindowsServer2025', 10),
                    ('Office2021', 10),
                    ('Office2024', 10),
                )
                for mode, count in modes:
                    with self.subTest(mode=mode):
                        result = subprocess.run(
                            [sys.executable, '-B', str(ROOT / 'hyx_kms_py/hyx_kms_client.py'),
                             '127.0.0.1', str(port), '-m', mode, '-n', mode,
                             '-t0', '3', '-t1', '3', '-F', 'STDOUT', '-V', 'INFO'],
                            cwd=tmp, capture_output=True, text=True, timeout=12,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, '')
                        self.assertIn('KMS Host ePID:', result.stdout)
                        self.assertIn('KMS Host Current Client Count: %d' % count, result.stdout)
                with closing(sqlite3.connect(database)) as connection:
                    rows = connection.execute('SELECT machineName, skuId, kmsEpid, requestCount FROM clients ORDER BY machineName').fetchall()
                self.assertEqual(len(rows), 4)
                self.assertEqual(
                    {row[0]: row[1] for row in rows},
                    {
                        'Office2021': 'Office LTSC Professional Plus 2021',
                        'Office2024': 'Office LTSC Professional Plus 2024',
                        'Windows11': 'Windows 10 Enterprise',
                        'WindowsServer2025': 'Windows Server 2025 Standard',
                    },
                )
                self.assertTrue(all(row[2] and row[3] == 1 for row in rows))
                rows_by_name = {row[0]: row for row in rows}
                self.assert_server2025_epid(rows_by_name['WindowsServer2025'][2])
                office_2021_epid = rows_by_name['Office2021'][2].split('-')
                self.assertTrue(571000000 <= int(office_2021_epid[2] + office_2021_epid[3]) <= 590999999)
                self.assertIn(office_2021_epid[6], {'14393.0000', '17763.0000', '26100.0000'})
                office_2024_epid = rows_by_name['Office2024'][2].split('-')
                self.assertTrue(591000000 <= int(office_2024_epid[2] + office_2024_epid[3]) <= 610999999)
                self.assertIn(office_2024_epid[6], {'17763.0000', '26100.0000'})
            finally:
                listener.shutdown()
                listener.w_service.sendall(b'stop')
                worker.join(timeout=3)
                listener.server_close()
                listener.r_service.close()
                listener.w_service.close()
            self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
