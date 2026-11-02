"""Shared liveness/readiness probes; never writes an activation record."""
import ipaddress
import os
import socket
import struct
import time
import uuid
from hyx_kms_transport import recv_pdu
from hyx_kms_dcerpc import MSRPCBindAck


def kms_probe_host():
    """Return the local address matching the configured KMS listener family."""
    configured = os.environ.get('KMS_HEALTH_HOST', '').strip()
    if configured:
        if configured.startswith('[') and configured.endswith(']'):
            candidate = configured[1:-1]
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                pass
            else:
                return candidate
        return configured
    bind_address = os.environ.get('IP', '0.0.0.0').strip()
    try:
        version = ipaddress.ip_address(bind_address).version
    except ValueError:
        version = 4
    return '::1' if version == 6 else '127.0.0.1'


def probe_kms(host, port, timeout=1.0):
    call_id = 0x484c5448
    syntax = uuid.UUID('8a885d04-1ceb-11c9-9fe8-08002b104860').bytes_le + struct.pack('<I', 2)
    context = (struct.pack('<HBB', 0, 1, 0) +
               uuid.UUID('51c82175-844e-4750-b0d8-ec255555bc06').bytes_le +
               struct.pack('<I', 1) + syntax)
    body = struct.pack('<HHIBBH', 4280, 4280, 0, 1, 0, 0) + context
    wire = struct.pack('<BBBBIHHI', 5, 0, 11, 3, 16, 16 + len(body), 0, call_id) + body
    deadline = time.monotonic() + timeout
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(wire)
        ack = MSRPCBindAck(recv_pdu(sock, deadline))
    if ack['type'] != 12 or ack['call_id'] != call_id or ack['ctx_num'] != 1:
        raise ValueError('Invalid RPC readiness response')
    result = ack.getCtxItem(1)
    received_syntax = result['TransferSyntax']
    if isinstance(received_syntax, str):
        received_syntax = received_syntax.encode('latin-1')
    if result['Result'] != 0 or received_syntax != syntax:
        raise ValueError('RPC readiness context rejected')


def check():
    """One entry point for Docker HEALTHCHECK: web readiness or bare KMS readiness."""
    if os.environ.get('SQLITE') == 'true':
        from hyx_kms_tls import probe_web
        probe_web()
    else:
        probe_kms(kms_probe_host(), int(os.environ.get('PORT', '1688')))


if __name__ == '__main__':
    check()
