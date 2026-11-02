"""Gunicorn entry configuration; TLS is mandatory even on loopback."""
import os
import ssl
from hyx_kms_budget import env_int, validate_environment
from hyx_kms_tls import tls_files

certfile, keyfile = tls_files()
validate_environment()
bind = '{}:{}'.format(os.environ.get('WEB_HOST', '0.0.0.0'), os.environ.get('WEB_PORT', '8080'))
workers = 1
worker_class = 'gthread'
threads = env_int('WEB_THREADS', 4)
if threads > 16:
    raise ValueError('WEB_THREADS must be between 1 and 16')
keepalive = 5
accesslog = '-'


def ssl_context(config, default_factory):
    context = default_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
