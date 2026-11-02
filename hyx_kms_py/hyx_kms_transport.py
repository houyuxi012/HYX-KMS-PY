"""Bounded connection-oriented RPC transport shared by client and server."""
import struct
import time

MAX_PDU_SIZE = 16384
DEFAULT_IO_TIMEOUT = 5.0
DEFAULT_CONNECTION_LIFETIME = 30.0


def recv_exact(sock, size, deadline=None):
    data = bytearray()
    while len(data) < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RPC connection deadline exceeded')
            configured = sock.gettimeout()
            sock.settimeout(min(configured or DEFAULT_IO_TIMEOUT, remaining))
        block = sock.recv(size - len(data))
        if not block:
            if not data:
                raise EOFError('RPC peer closed connection')
            raise ValueError('Truncated RPC frame')
        data.extend(block)
    return bytes(data)


def recv_pdu(sock, deadline=None):
    header = recv_exact(sock, 16, deadline)
    if header[:2] != b'\x05\x00' or header[4:8] != b'\x10\x00\x00\x00':
        raise ValueError('Unsupported RPC version or representation')
    length, auth_length = struct.unpack_from('<HH', header, 8)
    if not 16 <= length <= MAX_PDU_SIZE or auth_length:
        raise ValueError('Invalid RPC length or unsupported authentication trailer')
    if header[3] & 3 != 3 or header[3] & 0x80:
        raise ValueError('Fragmented/object RPC PDUs are not supported')
    return header + recv_exact(sock, length - 16, deadline)
