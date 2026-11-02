#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

docker build \
    --tag hyx-kms-py:latest \
    --file "$repository_root/docker/hyx-kms-py/Dockerfile.amd64" \
    "$repository_root"
