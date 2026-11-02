import os
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hyx_kms_py'))
from hyx_kms_catalog import get_activation_products as _get_activation_products
from hyx_kms_webui import app


class WebUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / 'clients.db')
        with closing(sqlite3.connect(self.database)) as con:
            con.execute('CREATE TABLE clients (clientMachineId TEXT, machineName TEXT, applicationId TEXT, skuId TEXT, licenseStatus TEXT, lastRequestTime INTEGER, kmsEpid TEXT, requestCount INTEGER)')
            con.execute('INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        ('test-id', '<script>alert(1)</script>', 'Windows', 'test-sku', 'Licensed', 1700000000, None, 2))
            con.commit()
        env = patch.dict(os.environ, PYKMS_SQLITE_DB_PATH=self.database)
        env.start()
        self.addCleanup(env.stop)
        self.client = app.test_client()

    def test_home_keeps_client_records_and_escapes_names(self):
        response = self.client.get('/', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('test-id', body)
        self.assertIn('2023-11-14T22:13:20+00:00', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('href="/activate"', body)

    def test_machine_name_is_not_truncated(self):
        machine_name = 'DESKTOP-HouYuxi-Workstation-01'
        with closing(sqlite3.connect(self.database)) as con:
            con.execute(
                'INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                ('long-name-id', machine_name, 'Windows', 'test-sku',
                 'Licensed', 1700000001, None, 1),
            )
            con.commit()

        body = self.client.get('/', base_url='https://localhost').get_data(as_text=True)
        machine_cell = body.split('class="machineName machine-name-cell">', 1)[1].split('</td>', 1)[0]
        self.assertIn(machine_name, machine_cell)
        self.assertNotIn('...', machine_cell)
        self.assertNotIn('<abbr', machine_cell)

    def test_routes_and_static_assets(self):
        for path in ('/activate', '/activate/windows', '/products', '/license', '/static/js/site.js', '/static/js/activation.js', '/static/css/bulma.min.css'):
            with self.subTest(path=path):
                with self.client.get(path, base_url='https://localhost') as response:
                    self.assertEqual(response.status_code, 200)

    def test_brand_logo_is_used_in_navigation_and_favicon(self):
        body = self.client.get('/activate', base_url='https://localhost').get_data(as_text=True)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/static/logo.svg">', body)
        self.assertIn('class="kms-logo" src="/static/logo.svg"', body)
        with self.client.get('/static/logo.svg', base_url='https://localhost') as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content_type.startswith('image/svg+xml'))
            self.assertIn(b'viewBox="0 0 1024 1024"', response.data)
            self.assertIn(b'fill="#2636dd"', response.data)

    def test_footer_separates_copyright_from_support_and_license(self):
        body = self.client.get('/activate', base_url='https://localhost').get_data(as_text=True)
        copyright_text = body.split('class="footer-copyright">', 1)[1].split('</p>', 1)[0]
        support_text = body.split('class="footer-support">', 1)[1].split('</p>', 1)[0]
        self.assertIn('密钥管理服务器平台', copyright_text)
        self.assertIn('版权所有', copyright_text)
        self.assertNotIn('软件许可', copyright_text)
        self.assertIn('技术支持', support_text)
        self.assertIn('https://www.houyuxi.com', support_text)
        self.assertIn('href="/license"', support_text)

    def test_activation_connection_fields_are_grouped_as_advanced_settings(self):
        body = self.client.get('/activate', base_url='https://localhost').get_data(as_text=True)
        details = body.split('<details class="connection-options"', 1)[1].split('</details>', 1)[0]
        self.assertIn('id="server-input"', details)
        self.assertIn('id="port-input"', details)
        self.assertLess(details.index('id="server-input"'), details.index('id="port-input"'))

    def test_security_headers_and_static_cache_policy(self):
        page = self.client.get('/activate', base_url='https://localhost')
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("default-src 'self'", page.headers['Content-Security-Policy'])
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertIn('camera=()', page.headers['Permissions-Policy'])
        self.assertNotIn('<style>', body)
        self.assertIn('nonce="', body)
        with self.client.get('/static/css/bulma.min.css', base_url='https://localhost') as static:
            self.assertIn('public, max-age=86400', static.headers['Cache-Control'])

    def test_pages_and_static_assets_are_open_without_authentication(self):
        for path in ('/', '/activate', '/static/js/site.js'):
            with self.subTest(path=path), \
                 self.client.get(path, base_url='https://localhost') as response:
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('WWW-Authenticate', response.headers)

    def test_database_failure_does_not_create_or_overwrite_file(self):
        missing = str(Path(self.directory.name) / 'missing.db')
        with patch.dict(os.environ, PYKMS_SQLITE_DB_PATH=missing):
            response = self.client.get('/', base_url='https://localhost')
            self.assertEqual(response.status_code, 500)
            body = response.get_data(as_text=True)
            self.assertNotIn(missing, body)
            self.assertNotIn('sqlite', body.lower())
            self.assertIn('error-reference', body)
            self.assertFalse(Path(missing).exists())
        before = Path(self.database).read_bytes()
        self.client.get('/', base_url='https://localhost')
        self.assertEqual(before, Path(self.database).read_bytes())

    def test_catalog_excludes_retail_preview_and_includes_current_office(self):
        catalog = _get_activation_products()
        names = [item['name'] for groups in catalog.values() for group in groups for item in group['items']]
        self.assertFalse(any('Retail' in name or 'Preview' in name or 'Pre-Release' in name for name in names))
        self.assertTrue(any('Office' in name and '2024' in name for name in names))
        self.assertTrue(any('Windows Server 2025' in name for name in names))

    def test_product_types_separate_windows_and_server_without_losing_products(self):
        catalog = _get_activation_products()
        self.assertEqual(list(catalog), ['Windows', 'Windows Server', 'Office'])
        self.assertTrue(all(catalog.values()))
        self.assertTrue(all('server' not in group['group'].lower() for group in catalog['Windows']))
        self.assertTrue(all('server' in group['group'].lower() for group in catalog['Windows Server']))
        self.assertTrue(any(item['name'] == 'Windows Server 2025 Standard'
                            for group in catalog['Windows Server'] for item in group['items']))
        self.assertTrue(any(item['name'] == 'Windows 10 Pro'
                            for group in catalog['Windows'] for item in group['items']))
        total = sum(len(group['items']) for groups in catalog.values() for group in groups)
        self.assertIn(str(total), self.client.get('/products', base_url='https://localhost').get_data(as_text=True))

    def test_every_windows_edition_matches_independent_microsoft_snapshot(self):
        path = Path(__file__).with_name('fixtures') / 'microsoft_windows_gvlks.json'
        official = json.loads(path.read_text())['editions']
        items = [item for group in _get_activation_products()['Windows'] for item in group['items']]
        names = [item['name'] for item in items]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {name for name in official if not name.startswith('Windows IoT')})
        for item in items:
            with self.subTest(name=item['name']):
                self.assertEqual(item['gvlk'], official[item['name']])

    def test_shared_skus_have_explicit_windows_and_ltsc_versions(self):
        editions = {item['name']: item for group in _get_activation_products()['Windows'] for item in group['items']}
        for suffix in ('Pro', 'Pro N', 'Pro for Workstations', 'Pro Education', 'Enterprise G'):
            self.assertEqual(editions['Windows 11 ' + suffix]['gvlk'], editions['Windows 10 ' + suffix]['gvlk'])
        for suffix in ('Enterprise', 'Enterprise N'):
            self.assertEqual(editions['Windows 11 ' + suffix + ' LTSC 2024']['gvlk'],
                             editions['Windows 10 ' + suffix + ' LTSC 2021']['gvlk'])

    def test_edition_groups_are_ordered_newest_first(self):
        catalog = _get_activation_products()
        self.assertEqual([group['group'] for group in catalog['Windows']], [
            'Windows 11', 'Windows 11 Enterprise LTSC 2024', 'Windows 10',
            'Windows 10 Enterprise LTSC 2021', 'Windows 10 Enterprise LTSC 2019',
            'Windows 10 Enterprise LTSB 2016', 'Windows 10 Enterprise LTSB 2015',
            'Windows 8.1', 'Windows 8', 'Windows 7', 'Windows Vista',
        ])
        self.assertEqual(catalog['Windows Server'][0]['group'], 'Windows Server 2025')
        self.assertEqual(catalog['Office'][0]['group'], 'Office 2024')
        self.assertEqual(catalog['Office'][-1]['group'], 'Office 2010')


if __name__ == '__main__':
    unittest.main()
