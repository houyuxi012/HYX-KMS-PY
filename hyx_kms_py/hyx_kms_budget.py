"""Thread-safe per-minute token buckets for admission control."""
from collections import OrderedDict
from ipaddress import ip_address, ip_network
import os
import threading
import time


def env_int(name, default):
    raw = os.environ.get(name, '')
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError('%s must be an integer' % name)
    if value < 1:
        raise ValueError('%s must be positive' % name)
    return value


class TokenBuckets:
    def __init__(self, max_entries=4096, idle_seconds=600, clock=time.monotonic):
        if max_entries < 1 or idle_seconds <= 0:
            raise ValueError('Token bucket state limits must be positive')
        self._lock = threading.Lock()
        self._state = OrderedDict()
        self._max_entries = max_entries
        self._idle_seconds = idle_seconds
        self._clock = clock

    def _make_room(self, now):
        cutoff = now - self._idle_seconds
        while self._state and next(iter(self._state.values()))[1] <= cutoff:
            self._state.popitem(last=False)
        while len(self._state) >= self._max_entries:
            self._state.popitem(last=False)

    def try_acquire(self, entries):
        """entries: sequence of (key, capacity_per_minute); all-or-nothing."""
        now = self._clock()
        with self._lock:
            if any(key not in self._state for key, _ in entries):
                self._make_room(now)
            refreshed = []
            for key, capacity in entries:
                tokens, last = self._state.pop(key, (float(capacity), now))
                refreshed.append((key, capacity, min(capacity, tokens + (now - last) * capacity / 60.0)))
            if any(tokens < 1 for _, _, tokens in refreshed):
                for key, _, tokens in refreshed:
                    self._state[key] = (tokens, now)
                return False
            for key, _, tokens in refreshed:
                self._state[key] = (tokens - 1.0, now)
            return True

    def release(self, entries):
        """Return one reservation after the admitted operation succeeds."""
        now = self._clock()
        with self._lock:
            for key, capacity in entries:
                if key not in self._state:
                    self._make_room(now)
                tokens, _ = self._state.pop(key, (float(capacity), now))
                self._state[key] = (min(capacity, tokens + 1.0), now)

    def reset(self):
        with self._lock:
            self._state.clear()


class SourceConnectionLimiter:
    """Bound KMS connections globally and per source without unbounded key state."""
    def __init__(self, global_limit, per_source_limit):
        if global_limit < 1 or per_source_limit < 1:
            raise ValueError('Connection limits must be positive')
        self._global_limit = global_limit
        self._per_source_limit = per_source_limit
        self._global_slots = threading.BoundedSemaphore(global_limit)
        self._lock = threading.Lock()
        self._source_counts = {}

    def try_acquire(self, source):
        if not self._global_slots.acquire(blocking=False):
            return False
        with self._lock:
            count = self._source_counts.get(source, 0)
            if count >= self._per_source_limit:
                self._global_slots.release()
                return False
            self._source_counts[source] = count + 1
        return True

    def release(self, source):
        with self._lock:
            count = self._source_counts.get(source, 0)
            if count <= 0:
                return False
            if count == 1:
                del self._source_counts[source]
            else:
                self._source_counts[source] = count - 1
        self._global_slots.release()
        return True


def _listener_hosts(server_address):
    """Return bind hosts for both BaseServer's address tuple and MultiListener lists."""
    if (isinstance(server_address, tuple) and len(server_address) >= 2 and
            isinstance(server_address[0], str)):
        return (server_address[0],)
    return tuple(address[0] for address in server_address)


class KmsSourcePolicy:
    """Network admission applied before a KMS request can allocate an identity."""

    def __init__(self, networks):
        self.networks = tuple(ip_network(network, strict=False) for network in networks)

    @classmethod
    def from_environment(cls, server_address):
        raw = os.environ.get("KMS_ALLOWED_NETWORKS", "").strip()
        bind_hosts = _listener_hosts(server_address)
        non_loopback_bind = False
        for host in bind_hosts:
            try:
                address = ip_address(host)
            except ValueError as exc:
                raise ValueError("KMS listener addresses must be literal IP addresses") from exc
            if not address.is_loopback:
                non_loopback_bind = True

        if not raw:
            if non_loopback_bind:
                raise ValueError(
                    "KMS_ALLOWED_NETWORKS is required when KMS listens on a non-loopback address"
                )
            networks = ("127.0.0.0/8", "::1/128")
        else:
            values = [value.strip() for value in raw.split(",") if value.strip()]
            if not values or len(values) > 64:
                raise ValueError("KMS_ALLOWED_NETWORKS must contain 1..64 IPv4/IPv6 CIDR networks")
            networks = values
        # Local health probes and same-host clients must remain usable even when
        # the operator supplies a narrower external allowlist.
        networks = tuple(networks) + ("127.0.0.0/8", "::1/128")
        return cls(networks)

    def allows(self, source):
        try:
            address = ip_address(source)
        except (ValueError, TypeError):
            return False
        return any(address in network for network in self.networks if network.version == address.version)

    @staticmethod
    def source_key(source):
        """Collapse IPv6 rotation to /64 while retaining ordinary IPv4 sources."""
        try:
            address = ip_address(source)
        except (ValueError, TypeError):
            return "unknown"
        prefix = 64 if address.version == 6 else 32
        return str(ip_network(f"{address}/{prefix}", strict=False))


RUNTIME_BUDGETS = (
    ('KMS_NEW_IDENTITY_PER_MIN', 60),
    ('KMS_NEW_IDENTITY_PER_SOURCE_PER_MIN', 10),
    ('KMS_MAX_CONNECTIONS_PER_SOURCE', 16),
    ('KMS_MAX_CLIENTS', 10000),
)


def validate_environment():
    """Fail fast at startup when any admission-budget variable is misconfigured."""
    for name, default in RUNTIME_BUDGETS:
        env_int(name, default)
