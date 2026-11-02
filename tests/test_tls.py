"""TLS regressions: actual sockets, certificate trust and fail-closed configuration."""
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hyx_kms_py'))
from hyx_kms_tls import tls_files, probe_web
from hyx_kms_webui import app


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/readyz' else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.cert = str(Path(cls.temp.name) / 'cert.pem')
        cls.key = str(Path(cls.temp.name) / 'key.pem')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', cls.key, '-out', cls.cert, '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(cls.key).chmod(0o600)
        Path(cls.cert).chmod(0o600)

    def env(self):
        return patch.dict(
            os.environ,
            WEB_TLS_CERT_FILE=self.cert,
            WEB_TLS_KEY_FILE=self.key,
        )

    def test_config_requires_cert_and_key(self):
        with patch.dict(os.environ, WEB_TLS_CERT_FILE='', WEB_TLS_KEY_FILE=''):
            with self.assertRaises(ValueError):
                tls_files()
        with self.env(), patch.dict(os.environ, WEB_TLS_KEY_FILE='/nonexistent/private.key'):
            with self.assertRaises(ValueError):
                tls_files()

    def test_valid_pair_and_invalid_key(self):
        with self.env():
            self.assertEqual(tls_files(), (self.cert, self.key))
            with patch.dict(os.environ, WEB_TLS_KEY_FILE=self.cert):
                with self.assertRaises((ssl.SSLError, ValueError)):
                    tls_files()

    def test_gunicorn_configuration_requires_valid_tls(self):
        source = str(Path(__file__).resolve().parents[1] / 'hyx_kms_py')
        command = [sys.executable, '-m', 'gunicorn', '--check-config',
                   '-c', 'python:hyx_kms_gunicorn', 'hyx_kms_webui:app']
        with self.env():
            result = subprocess.run(command, cwd=source, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            with patch.dict(os.environ, WEB_TLS_KEY_FILE=''):
                result = subprocess.run(command, cwd=source, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'WEB_TLS_KEY_FILE is required', result.stderr)

    def test_group_or_world_readable_key_rejected(self):
        if os.name == 'nt':
            self.skipTest('Unix file mode check')
        try:
            for mode in (0o604, 0o640):
                Path(self.key).chmod(mode)
                with self.env(), self.assertRaises(ValueError):
                    tls_files()
        finally:
            Path(self.key).chmod(0o600)

    def test_http_rejected_before_routes_including_forwarded_header(self):
        client = app.test_client()
        for path in ('/activate', '/livez', '/readyz', '/static/css/site.css'):
            response = client.get(path, headers={'X-Forwarded-Proto': 'https'})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('WWW-Authenticate', response.headers)
            self.assertNotIn('Strict-Transport-Security', response.headers)
        response = client.get('/livez', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn('max-age=', response.headers['Strict-Transport-Security'])

    def test_verified_probe_uses_local_socket_and_certificate_hostname(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert, self.key)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.env(), patch.dict(os.environ, WEB_PORT=str(server.server_port),
                                        WEB_TLS_SERVER_NAME='localhost', WEB_TLS_CA_FILE=''):
                probe_web()
                with patch.dict(os.environ, WEB_TLS_SERVER_NAME='wrong.example'), self.assertRaises(ssl.SSLCertVerificationError):
                    probe_web()
                with patch.dict(os.environ, WEB_TLS_CA_FILE=ssl.get_default_verify_paths().cafile), self.assertRaises(ssl.SSLCertVerificationError):
                    probe_web()
                with socket.create_connection(server.server_address) as raw:
                    raw.sendall(b'GET /livez HTTP/1.0\r\n\r\n')
                    try:
                        self.assertNotIn(b'200 OK', raw.recv(1024))
                    except ConnectionResetError:
                        pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
