"""Every displayed edition: official key coverage, protocol roundtrip and script matrix."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hyx_kms_py'))
import hyx_kms_client as client
from hyx_kms_db2dict import kmsDB2Dict
from hyx_kms_format import enco
from hyx_kms_request_v4 import kmsRequestV4
from hyx_kms_request_v5 import kmsRequestV5
from hyx_kms_request_v6 import kmsRequestV6
from hyx_kms_catalog import get_activation_products as _get_activation_products


class ProductMatrixTests(unittest.TestCase):
    def test_displayed_products_match_reviewed_keys_and_identity(self):
        official = json.loads((ROOT / 'tests/fixtures/microsoft_product_gvlks.json').read_text())['keys']
        keysets = {name: set(keys) for name, keys in official.items()}
        data = kmsDB2Dict()[2]
        seen = set()
        for family, groups in _get_activation_products().items():
            for group in groups:
                for item in group['items']:
                    with self.subTest(product=item['name']):
                        self.assertNotIn(item['name'], seen)
                        seen.add(item['name'])
                        uuid.UUID(item['id'])
                        self.assertRegex(item['gvlk'], r'^[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}$')
                        matches = [(app, kms, sku) for app in data for kms in app['KmsItems'] for sku in kms['SkuItems'] if sku['Id'] == item['id']]
                        self.assertEqual(len(matches), 1)
                        self.assertEqual(matches[0][2]['Gvlk'], item['gvlk'])
                        if group['group'] != 'Office 2013':
                            reference = 'windows' if family != 'Office' else 'office2010' if group['group'] == 'Office 2010' else 'office'
                            self.assertIn(item['gvlk'], keysets[reference])
                        self.assertFalse(re.search(r'Mondo|Groove.*2013|ARM64|Azure Core|Cloud Storage', item['name']))
        self.assertTrue(any(group['group'] == 'Windows Server 2022' for group in _get_activation_products()['Windows Server']))

    def test_all_displayed_editions_roundtrip_with_their_actual_ids(self):
        indexed = {sku['Id']: (app, kms) for app in kmsDB2Dict()[2] for kms in app['KmsItems'] for sku in kms['SkuItems']}
        config = dict(clientcount=None, epid=None, lcid=1033, activation=120, renewal=10080,
                      sqlite=False, loglevel='ERROR', hwid=bytes.fromhex('364F463A8863D35F'))
        with patch.dict(client.clt_config, clear=True), patch('hyx_kms_client.pretty_printer'), patch('hyx_kms_base.pretty_printer'), patch('hyx_kms_request_v4.pretty_printer'), patch('hyx_kms_request_v5.pretty_printer'), patch('hyx_kms_request_v4.time.sleep'):
            for groups in _get_activation_products().values():
                for group in groups:
                    for item in group['items']:
                        with self.subTest(product=item['name']):
                            app, kms = indexed[item['id']]
                            major = int(float(kms['DefaultKmsProtocol']))
                            client.clt_config.clear()
                            client.clt_config.update(cmid=str(uuid.uuid4()), machine='PRODUCT-MATRIX', call_id=1,
                                KMSProtocolMajorVersion=major, KMSProtocolMinorVersion=0, KMSClientLicenseStatus=2,
                                RequiredClientCount=int(kms['NCountPolicy']), KMSClientAppID=app['Id'],
                                KMSClientKMSCountedID=kms['Id'], KMSClientSkuID=item['id'])
                            request = client.createKmsRequest()
                            handler = {4: kmsRequestV4, 5: kmsRequestV5, 6: kmsRequestV6}[major](enco(str(request), 'latin-1'), config)
                            wire = handler.executeRequestLogic()
                            response = client.readKmsResponse(enco(wire, 'latin-1'), request, client.clt_config)['response']
                            self.assertEqual(response['versionMajor'], major)
                            self.assertEqual(response['clientMachineId'].get(), uuid.UUID(client.clt_config['cmid']))
                            self.assertGreaterEqual(response['currentClientCount'], int(kms['NCountPolicy']))
                            self.assertEqual(response['vLActivationInterval'], 120)
                            self.assertEqual(response['vLRenewalInterval'], 10080)

    def test_script_for_every_edition_and_office_architecture(self):
        result = subprocess.run(['node', str(ROOT / 'tests/test_product_matrix.cjs')],
                                input=json.dumps(_get_activation_products()), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
