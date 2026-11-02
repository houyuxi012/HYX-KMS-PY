"""Locale negotiation, persistence, escaping and complete UI catalogs."""
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hyx_kms_py'))
from hyx_kms_i18n import CATALOG
from hyx_kms_webui import app


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url='https://localhost', **kwargs)

    def test_all_pages_have_supported_language_options_and_translated_titles(self):
        for language, title, menu_label in (
            ('zh-CN', '密钥管理服务平台', '简体中文'),
            ('zh-TW', '金鑰管理服務平台', '繁體中文'),
            ('en', 'Key Management Platform', 'English'),
            ('ja', 'キー管理プラットフォーム', '日本語'),
            ('fr', 'Plateforme de gestion de clés', 'Français'),
        ):
            for path in ('/activate', '/activate/windows', '/products', '/usage', '/license', '/'):
                with self.subTest(language=language, path=path), self.get(path+'?lang='+language) as response:
                    self.assertIn(response.status_code, (200, 500) if path == '/' else (200,))
                    body = response.get_data(as_text=True)
                    self.assertIn(f'<html lang="{language}">', body)
                    self.assertIn(f'<title>{title}</title>', body)
                    self.assertIn(f'<option value="{language}" selected>{menu_label}</option>', body)
                    self.assertEqual(response.headers['Content-Language'], language)
                    for code in ('zh-CN', 'zh-TW', 'en', 'ja', 'fr'):
                        self.assertIn(f'option value="{code}"', body)

    def test_explicit_choice_persists_and_overrides_browser_preference(self):
        response = self.get('/activate?lang=ja')
        cookie = response.headers['Set-Cookie']
        for attribute in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'):
            self.assertIn(attribute, cookie)
        self.assertEqual(self.get('/usage', headers={'Accept-Language': 'en'}).headers['Content-Language'], 'ja')
        self.assertEqual(self.get('/usage?lang=en').headers['Content-Language'], 'en')
        self.assertEqual(self.get('/usage').headers['Content-Language'], 'en')

    def test_browser_preference_fallback_and_untrusted_locale(self):
        self.assertEqual(self.get('/usage').headers['Content-Language'], 'zh-CN')
        self.assertEqual(self.get('/usage', headers={'Accept-Language': 'ja-JP, en;q=0.5'}).headers['Content-Language'], 'ja')
        self.assertEqual(self.get('/usage', headers={'Accept-Language': 'en-US'}).headers['Content-Language'], 'en')
        self.assertEqual(self.get('/usage', headers={'Accept-Language': 'fr-FR'}).headers['Content-Language'], 'fr')
        for tag in ('zh-TW', 'zh-HK', 'zh-MO', 'zh-Hant', 'zh-Hant-HK'):
            with self.subTest(tag=tag):
                self.assertEqual(
                    self.get('/usage', headers={'Accept-Language': tag}).headers['Content-Language'],
                    'zh-TW',
                )
        for tag in ('zh-CN', 'zh-SG', 'zh-Hans', 'zh-Hans-SG'):
            with self.subTest(tag=tag):
                self.assertEqual(
                    self.get('/usage', headers={'Accept-Language': tag}).headers['Content-Language'],
                    'zh-CN',
                )
        response = self.get('/usage?lang=%3Cscript%3E')
        self.assertEqual(response.headers['Content-Language'], 'zh-CN')
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertNotIn('<script><', response.get_data(as_text=True))

    def test_switch_preserves_query_and_escapes_hidden_fields(self):
        body = self.get('/activate?page=2&extra=%22%3E%3Cimg%20src=x%3E&lang=en').get_data(as_text=True)
        self.assertIn('name="page" value="2"', body)
        self.assertIn('&lt;img src=x&gt;', body)
        self.assertNotIn('<img src=x>', body)

    def test_ui_and_js_keys_are_complete_and_catalog_serialization_is_safe(self):
        expected_keys = set(CATALOG['en'])
        self.assertEqual(set(CATALOG['zh-TW']), expected_keys)
        self.assertEqual(set(CATALOG['ja']), expected_keys)
        self.assertEqual(set(CATALOG['fr']), expected_keys)
        root = Path(__file__).resolve().parents[1] / 'hyx_kms_py'
        sources = list((root / 'templates').glob('*.html')) + [root / 'static/js/activation.js']
        for source in sources:
            for key in re.findall(r"\bt\('([^']+)'", source.read_text()):
                self.assertIn(key, CATALOG['en'], (source.name, key))
                self.assertTrue(CATALOG['en'][key])
                self.assertTrue(CATALOG['zh-TW'][key])
                self.assertTrue(CATALOG['ja'][key])
                self.assertTrue(CATALOG['fr'][key])
        body = self.get('/activate?lang=fr').get_data(as_text=True)
        messages = json.loads(re.search(
            r'<script id="ui-messages" type="application/json"[^>]*>(.*?)</script>',
            body, re.S
        )[1])
        self.assertEqual(messages['脚本已复制。'], 'Script copié.')
        traditional_body = self.get('/activate?lang=zh-TW').get_data(as_text=True)
        traditional_messages = json.loads(re.search(
            r'<script id="ui-messages" type="application/json"[^>]*>(.*?)</script>',
            traditional_body, re.S
        )[1])
        self.assertEqual(traditional_messages['脚本已复制。'], '指令碼已複製。')


if __name__ == '__main__':
    unittest.main()
