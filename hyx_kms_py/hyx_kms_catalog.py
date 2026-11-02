"""Activation product catalog: protocol database filtered by the curated display map."""
import json
import re
from pathlib import Path

from hyx_kms_db2dict import kmsDB2Dict

WINDOWS_CLIENT_CATALOG = json.loads(
    Path(__file__).with_name('windows_client_catalog.json').read_text(encoding='utf-8')
)
ACTIVATION_CATALOG = json.loads(
    Path(__file__).with_name('activation_catalog.json').read_text(encoding='utf-8')
)
WINDOWS_SOURCE_URL = WINDOWS_CLIENT_CATALOG['source']
GVLK_PATTERN = re.compile(r'[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}')

_cache = None


def _protocol_products():
    products = {"Windows": [], "Windows Server": [], "Office": []}
    for app_item in kmsDB2Dict()[2]:
        app_name = app_item.get("DisplayName", "")
        if "windows" in app_name.lower():
            bucket = "Windows"
        elif "office" in app_name.lower():
            bucket = "Office"
        else:
            continue
        for kms_item in app_item.get("KmsItems", []):
            if kms_item.get('IsRetail') == 'true' or kms_item.get('IsPreview') == 'true':
                continue
            group_name = kms_item.get("DisplayName", "")
            if any(term in group_name.lower() for term in ('preview', 'pre-release', 'retail')):
                continue
            items = []
            for sku in kms_item.get("SkuItems", []):
                name = sku.get('DisplayName', '')
                if sku.get('Id', '').startswith('00000000-'):
                    continue
                if any(term in name.lower() for term in ('preview', 'pre-release', 'retail')) or sku.get('IsGeneratedGvlk') == 'true':
                    continue
                gvlk = sku.get("Gvlk", "").strip()
                if not gvlk:
                    continue
                items.append({"name": name, "gvlk": gvlk, "id": sku.get("Id", "")})
            if items:
                product_type = "Windows Server" if bucket == "Windows" and "server" in group_name.lower() else bucket
                products[product_type].append({"group": group_name, "items": items})
    return products


def get_activation_products():
    """Displayed editions only; every curated SKU must exist with a well-formed GVLK."""
    global _cache
    if _cache is not None:
        return _cache
    products = _protocol_products()
    catalogs = dict(ACTIVATION_CATALOG['groups'], Windows=WINDOWS_CLIENT_CATALOG['groups'])
    for family, groups in catalogs.items():
        indexed = {item['id']: item for group in products[family] for item in group['items']}
        curated_groups = []
        for group in groups:
            editions = []
            for edition in group['editions']:
                sku = indexed.get(edition['sku_id'])
                if sku is None or not GVLK_PATTERN.fullmatch(sku['gvlk']):
                    raise ValueError('Invalid or missing catalog SKU: ' + edition['name'])
                editions.append(dict(sku, name=edition['name']))
            curated_groups.append({'group': group['group'], 'items': editions})
        products[family] = curated_groups
    _cache = products
    return products
