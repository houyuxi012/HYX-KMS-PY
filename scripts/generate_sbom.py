#!/usr/bin/env python3
"""Generate or verify a deterministic CycloneDX inventory from lock files."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = re.compile(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)')


def parse_lock(path):
    packages = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = PACKAGE.match(line)
        if match:
            name, version = match.groups()
            packages[name.lower()] = (name, version)
    return packages


def build_sbom():
    packages = {}
    for name in ('requirements.lock', 'requirements-minimal.lock'):
        packages.update(parse_lock(ROOT / name))
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').splitlines()[0].strip()
    components = [
        {
            'type': 'application',
            'bom-ref': 'pkg:generic/hyx-kms-py@' + version,
            'name': 'HYX-KMS-PY',
            'version': version,
            'licenses': [{'license': {'name': 'Unlicense'}}],
        }
    ]
    for name, package_version in sorted(packages.values(), key=lambda item: item[0].lower()):
        components.append({
            'type': 'library',
            'bom-ref': 'pkg:pypi/%s@%s' % (name.lower(), package_version),
            'name': name,
            'version': package_version,
            'purl': 'pkg:pypi/%s@%s' % (name.lower(), package_version),
        })
    document = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'version': 1,
        'metadata': {
            'component': components[0],
            'properties': [
                {'name': 'hyx:lockfiles', 'value': 'requirements.lock,requirements-minimal.lock'},
            ],
        },
        'components': components[1:],
    }
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'sbom.cdx.json'
    content = build_sbom()
    if args.check:
        if not target.is_file() or target.read_bytes() != content:
            raise SystemExit('sbom.cdx.json is stale; run without --check')
        print('SBOM is current.')
        return
    target.write_bytes(content)
    print('Wrote', target)


if __name__ == '__main__':
    sys.exit(main())
