#!/usr/bin/env bash
set -euo pipefail

: "${WEB_TLS_VOLUME:?Set WEB_TLS_VOLUME to an explicitly provisioned certificate volume}"
: "${WEB_TLS_SERVER_NAME:?Set WEB_TLS_SERVER_NAME to a certificate SAN name}"
: "${KMS_ALLOWED_NETWORKS:?Set KMS_ALLOWED_NETWORKS to the client IPv4/IPv6 CIDR allowlist}"
kms_public_port="${KMS_PUBLISH_PORT:-${KMS_PUBLIC_PORT:-1688}}"
image="${HYX_KMS_IMAGE:-hyx-kms-py:latest}"
kms_ipv6=false
web_ipv6=false

case "${KMS_IPV6:-false}" in
    1|true|yes) kms_ipv6=true ;;
    0|false|no|"") ;;
    *)
        echo "KMS_IPV6 must be true or false." >&2
        exit 64
        ;;
esac

case "${WEB_IPV6:-false}" in
    1|true|yes) web_ipv6=true ;;
    0|false|no|"") ;;
    *)
        echo "WEB_IPV6 must be true or false." >&2
        exit 64
        ;;
esac

ipv6_host() {
    case "$1" in
        \[*\]) printf '%s' "$1" ;;
        *) printf '[%s]' "$1" ;;
    esac
}

docker run --rm --network none \
    -e WEB_TLS_CERT_FILE=/run/tls/current/fullchain.pem \
    -e WEB_TLS_KEY_FILE=/run/tls/current/privkey.pem \
    -e WEB_TLS_SERVER_NAME="$WEB_TLS_SERVER_NAME" \
    -v "$WEB_TLS_VOLUME:/run/tls:ro" \
    --entrypoint python3 \
    "$image" -c \
    'from hyx_kms_tls import tls_files; tls_files(); print("Runtime TLS is valid.")'

docker_args=(
    run -d --name HYX-KMS-PY
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --cap-drop=ALL \
    --security-opt=no-new-privileges:true \
    --pids-limit="${KMS_PIDS_LIMIT:-256}" \
    --memory="${KMS_MEMORY_LIMIT:-512m}" \
    --cpus="${KMS_CPU_LIMIT:-1.0}" \
    --ulimit "nofile=${KMS_NOFILE_LIMIT:-1024}:${KMS_NOFILE_LIMIT:-1024}" \
    --stop-timeout 20 \
    -p "${WEB_PUBLISH_ADDRESS:-127.0.0.1}:${WEB_PUBLISH_PORT:-443}:8080" \
    -p "${KMS_PUBLISH_ADDRESS:-127.0.0.1}:${kms_public_port}:1688" \
)

if [ "$web_ipv6" = true ]; then
    docker_args+=(
        -p "$(ipv6_host "${WEB_IPV6_PUBLISH_ADDRESS:-::1}"):${WEB_PUBLISH_PORT:-443}:8080"
    )
fi

if [ "$kms_ipv6" = true ]; then
    docker_args+=(
        -p "$(ipv6_host "${KMS_IPV6_PUBLISH_ADDRESS:-::1}"):${kms_public_port}:1688"
    )
fi

docker_args+=(
    -e IP="${KMS_BIND_ADDRESS:-0.0.0.0}" \
    -e PORT=1688 \
    -e KMS_HEALTH_HOST="${KMS_HEALTH_HOST:-}" \
    -e KMS_IPV6="$kms_ipv6" \
    -e KMS_ALLOWED_NETWORKS="$KMS_ALLOWED_NETWORKS" \
    -e SQLITE=true \
    -e WEB_TLS_CERT_FILE=/run/tls/current/fullchain.pem \
    -e WEB_TLS_KEY_FILE=/run/tls/current/privkey.pem \
    -e WEB_TLS_SERVER_NAME="$WEB_TLS_SERVER_NAME" \
    -e WEB_TLS_CA_FILE="${WEB_TLS_CA_FILE:-}" \
    -v "$WEB_TLS_VOLUME:/run/tls:ro" \
    -e HWID="${HWID:-364F463A8863D35F}" \
    -e LOGLEVEL=INFO \
    -e LOGFILE=STDOUT \
    -e LOGSIZE=2 \
    -e KMS_PUBLIC_HOST="${KMS_PUBLIC_HOST:-}" \
    -e KMS_PUBLIC_PORT="$kms_public_port" \
    -v /etc/localtime:/etc/localtime:ro \
    -v HYX-KMS-PY-data:/data \
    --restart unless-stopped \
    "$image"
)

docker "${docker_args[@]}"
