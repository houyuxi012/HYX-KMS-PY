#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

"$PYTHON" -B -W error -m unittest discover -s tests -v
node tests/test_activation.cjs
"$PYTHON" scripts/build_product_matrix.py --check
"$PYTHON" scripts/generate_sbom.py --check
"$PYTHON" scripts/check_docs_links.py
"$PYTHON" -m pyflakes hyx_kms_py scripts tests
sh -n scripts/build_deployment_bundle.sh
bash -n \
    docker/hyx-kms-py/prepare-tls.sh \
    docker/hyx-kms-py/run.sh

if command -v sphinx-build >/dev/null 2>&1; then
    sphinx-build -b html -n -W --keep-going docs /tmp/hyx-docs-check
fi
