#!/bin/sh
set -eu
umask 077

case "${KMS_IPV6:-false}" in
    1|true|yes)
        ipv6_enabled=true
        ;;
    0|false|no|"")
        ipv6_enabled=false
        ;;
    *)
        echo "KMS_IPV6 must be true or false." >&2
        exit 64
        ;;
esac

cd /opt/HYX-KMS-PY/hyx_kms_py

set -- hyx_kms_server.py \
    "$IP" "$PORT" \
    -l "$LCID" \
    -c "$CLIENT_COUNT" \
    -a "$ACTIVATION_INTERVAL" \
    -r "$RENEWAL_INTERVAL" \
    -w "$HWID" \
    -V "$LOGLEVEL" \
    -F "$LOGFILE" \
    -t1 "${KMS_IO_TIMEOUT:-5}"

if [ -n "${EPID:-}" ]; then
    set -- "$@" -e "$EPID"
fi

if [ -n "${LOGSIZE:-}" ]; then
    set -- "$@" -S "$LOGSIZE"
fi

database="/data/HYX-KMS-PY_database.db"
if [ "${SQLITE:-false}" = "true" ]; then
    if [ "${HYX_WEBUI_AVAILABLE:-1}" != "1" ]; then
        echo "SQLITE=true requires the full WebUI image." >&2
        exit 64
    fi
    set -- "$@" -s "$database"
fi

if [ "$ipv6_enabled" = true ]; then
    case "$IP" in
        0.0.0.0)
            set -- "$@" connect -n "::,$PORT"
            ;;
        ::)
            set -- "$@" connect -n "0.0.0.0,$PORT"
            ;;
        127.*)
            set -- "$@" connect -n "::1,$PORT"
            ;;
        ::1)
            set -- "$@" connect -n "127.0.0.1,$PORT"
            ;;
        *:*)
            set -- "$@" connect -n "0.0.0.0,$PORT"
            ;;
        *)
            set -- "$@" connect -n "::,$PORT"
            ;;
    esac
fi

if [ "${SQLITE:-false}" != "true" ]; then
    exec python3 "$@"
fi

python3 -m hyx_kms_tls

chmod 700 /data
python3 -c "import sys; from hyx_kms_sql import sql_initialize; sql_initialize(sys.argv[1])" "$database"

cleanup() {
    trap - INT TERM EXIT
    kill "$server_pid" 2>/dev/null || true
    if [ -n "${web_pid:-}" ]; then
        kill "$web_pid" 2>/dev/null || true
    fi
}

terminate() {
    exit 0
}

python3 "$@" &
server_pid=$!

export PYKMS_SQLITE_DB_PATH="$database"
gunicorn -c python:hyx_kms_gunicorn hyx_kms_webui:app &
web_pid=$!

trap terminate INT TERM
trap cleanup EXIT

while kill -0 "$server_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
    sleep 1
done

cleanup

set +e
wait "$server_pid"
server_status=$?
wait "$web_pid"
web_status=$?
set -e

if [ "$server_status" -ne 0 ]; then
    exit "$server_status"
fi

if [ "$web_status" -ne 0 ]; then
    exit "$web_status"
fi

echo "HYX-KMS-PY stopped because a managed process exited unexpectedly." >&2
exit 1
