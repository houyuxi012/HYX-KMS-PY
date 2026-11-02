#!/usr/bin/env python3
"""Generate or verify the product matrix after real validation suites pass."""
import argparse
import csv
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hyx_kms_py'))
from hyx_kms_catalog import get_activation_products
from hyx_kms_db2dict import kmsDB2Dict


def run_validation():
    """The evidence columns may only say 通过 after these suites actually pass."""
    result = subprocess.run(
        [sys.executable, '-m', 'unittest', 'tests.test_product_matrix'],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            'Product validation failed.\nSTDOUT:\n%s\nSTDERR:\n%s' %
            (result.stdout, result.stderr)
        )


def render():
    indexed = {sku['Id']: kms for app in kmsDB2Dict()[2] for kms in app['KmsItems'] for sku in kms['SkuItems']}
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['产品类型', '发行分组', '产品名称', 'SKU ID', '协议版本', '架构覆盖',
                     '密钥独立官方复核', '本地协议往返', '脚本生成', '真实设备激活'])
    for family, groups in get_activation_products().items():
        for group in groups:
            for item in group['items']:
                writer.writerow([family, group['group'], item['name'], item['id'],
                                 indexed[item['id']]['DefaultKmsProtocol'],
                                 'x64 / x86' if family == 'Office' else '不适用',
                                 '待补历史官方依据' if group['group'] == 'Office 2013' else '通过',
                                 '通过', '通过', '未执行'])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def write_atomic(target, content):
    fd, temporary = tempfile.mkstemp(prefix='.product-matrix-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true',
                        help='run validation and fail if the committed matrix is stale')
    args = parser.parse_args()
    run_validation()
    content = render()
    target = ROOT / 'docs/产品可用性矩阵.csv'
    if args.check:
        if not target.is_file() or target.read_bytes() != content:
            raise SystemExit('docs/产品可用性矩阵.csv is stale; run without --check')
        print('Product matrix and validation evidence are current.')
        return
    write_atomic(target, content)
    print('Wrote', target)


if __name__ == '__main__':
    main()
