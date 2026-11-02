"""Shared configuration for mandatory website TLS and verified local probes."""
import http.client
import os
from pathlib import Path
import socket
import ssl

from hyx_kms_secrets import require_private_file


def tls_files():
    """Validate readable PEM files, private-key permissions and certificate pairing."""
    paths = []
    for name in ('WEB_TLS_CERT_FILE', 'WEB_TLS_KEY_FILE'):
        value = os.environ.get(name)
        if not value:
            raise ValueError(f'{name} is required: the website only supports HTTPS')
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f'{name} must point to an existing absolute file path')
        paths.append(str(path))
    require_private_file(paths[1], 'TLS private key')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Password-protected keys are not supported by this unattended service.
    context.load_cert_chain(*paths, password=lambda: '')
    return tuple(paths)


def probe_web(timeout=2):
    """Connect locally while checking the configured certificate identity and CA."""
    certfile = os.environ['WEB_TLS_CERT_FILE']
    server_name = os.environ.get('WEB_TLS_SERVER_NAME', 'localhost')
    if not server_name or any(c.isspace() or c in '/\\' for c in server_name):
        raise ValueError('WEB_TLS_SERVER_NAME must be a certificate DNS name or IP address')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=os.environ.get('WEB_TLS_CA_FILE') or certfile)
    port = int(os.environ.get('WEB_PORT', '8080'))
    host = os.environ.get('WEB_HEALTH_HOST', '127.0.0.1')
    connection = http.client.HTTPConnection(server_name, port, timeout=timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            connection.sock = context.wrap_socket(raw, server_hostname=server_name)
            connection.request('GET', '/readyz')
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f'Website readiness returned {response.status}')
            response.close()
    finally:
        connection.close()


if __name__ == '__main__':
    tls_files()
