"""Python 3.14 兼容性回归：命令行、时间转换和本机协议收发。"""

import doctest
import importlib
import json
import locale
import os
from contextlib import closing
from pathlib import Path
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hyx_kms_py"
sys.path.insert(0, str(SOURCE))

import hyx_kms_base as base
import hyx_kms_client as client
import hyx_kms_filetimes as filetimes
import hyx_kms_misc as misc
import hyx_kms_rpc_bind as rpc_bind
import hyx_kms_rpc_request as rpc_request
import hyx_kms_server as server
from Etrigan import Etrigan, default_pidfile
from hyx_kms_connect import MultipleListener
from hyx_kms_dcerpc import MSRPCRespHeader
from hyx_kms_format import ShellMessage, enco


def tearDownModule():
        server.serverthread.terminate_thread()
        if server.serverthread.is_alive():
                server.serverthread.join(timeout=2)


class Python314CompatibilityTests(unittest.TestCase):
        def test_sources_compile_without_warnings(self):
                for path in SOURCE.glob("*.py"):
                        with self.subTest(module=path.stem):
                                compile(path.read_bytes(), str(path), "exec")

        def test_all_modules_import(self):
                for path in SOURCE.glob("*.py"):
                        # Gunicorn configuration is tested with real TLS files in test_tls.
                        if path.stem == "hyx_kms_gunicorn":
                                continue
                        if path.stem.startswith("hyx_kms_gui"):
                                try:
                                        importlib.import_module("tkinter")
                                except ImportError:
                                        continue
                        with self.subTest(module=path.stem):
                                importlib.import_module(path.stem)

        def test_cli_help_with_redirected_output(self):
                for name in ("hyx_kms_server.py", "hyx_kms_client.py"):
                        with self.subTest(command=name), tempfile.TemporaryDirectory() as tmp:
                                result = subprocess.run(
                                        [sys.executable, "-B", "-W", "error", str(SOURCE / name), "--help"],
                                        cwd=tmp, capture_output=True, text=True, timeout=10,
                                )
                                self.assertEqual(result.returncode, 0, result.stderr)
                                self.assertIn("usage:", result.stdout)
                                self.assertEqual(result.stderr, "")

        def test_filetime_existing_examples(self):
                result = doctest.testmod(filetimes, verbose=False)
                self.assertEqual(result.failed, 0)
                self.assertEqual(result.attempted, 7)

        def test_filetime_preserves_instant_and_microseconds(self):
                utc_time = datetime(2026, 10, 27, 12, 34, 56, 123456, tzinfo=timezone.utc)
                expected = filetimes.dt_to_filetime(utc_time)
                for offset in (-7, 0, 8):
                        with self.subTest(offset=offset):
                                local_time = utc_time.astimezone(timezone(timedelta(hours=offset)))
                                self.assertEqual(filetimes.dt_to_filetime(local_time), expected)
                naive = utc_time.replace(tzinfo=None)
                self.assertEqual(filetimes.dt_to_filetime(naive), expected)
                self.assertEqual(filetimes.filetime_to_dt(expected), naive)

        def test_lcid_fallback_without_deprecated_locale_api(self):
                with patch.object(sys.implementation, "name", "pypy"), \
                     patch.object(locale, "getlocale", return_value=("zh_CN", "UTF-8")), \
                     patch.object(misc, "pretty_printer"):
                        self.assertEqual(misc.check_lcid(0, lambda message: None), 2052)

        def test_lcid_fallback_for_unrecognised_locale(self):
                with patch.object(sys.implementation, "name", "pypy"), \
                     patch.object(locale, "getlocale", side_effect=ValueError("unknown locale")), \
                     patch.object(misc, "pretty_printer"):
                        self.assertEqual(misc.check_lcid(0, lambda message: None), 1033)


class RequestCompatibilityTests(unittest.TestCase):
        def setUp(self):
                self.enterContext(patch.dict(client.clt_config, clear=True))
                self.enterContext(patch.object(ShellMessage, "viewsrv", False))
                self.enterContext(patch.object(ShellMessage, "viewclt", False))
                client.clt_config.update(mode="Windows8.1", call_id=1, cmid=None, machine="PY314-TEST")
                client.client_update()
                self.config = {
                        "clientcount": None, "lcid": 1033, "epid": None,
                        "activation": 120, "renewal": 10080, "hwid": bytes.fromhex("364F463A8863D35F"),
                        "sqlite": False, "loglevel": "INFO",
                }

        def test_current_time_request_and_epid_generation(self):
                before = datetime.now(timezone.utc).replace(tzinfo=None)
                request = client.createKmsRequestBase()
                after = datetime.now(timezone.utc).replace(tzinfo=None)
                self.assertLessEqual(before, filetimes.filetime_to_dt(request["requestTime"]))
                self.assertLessEqual(filetimes.filetime_to_dt(request["requestTime"]), after)
                response = base.kmsBase(None, self.config).serverLogic(request)
                self.assertTrue(response["kmsEpid"].decode("utf-16le"))
                self.assertEqual(response["responseTime"], request["requestTime"])

        def test_tzlocal_zoneinfo_converts_utc_instant(self):
                request = client.createKmsRequestBase()
                server_time = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
                request["requestTime"] = filetimes.dt_to_filetime(server_time)
                zone = timezone(timedelta(hours=8), "CST")
                tzlocal = types.SimpleNamespace(get_localzone=lambda: zone)
                with patch.dict(sys.modules, {"tzlocal": tzlocal}), \
                     patch.object(base.time, "time", return_value=server_time.timestamp()), \
                     self.assertLogs("logsrv", level="INFO") as logs:
                        base.kmsBase(None, self.config).serverLogic(request)
                self.assertTrue(any("2026-10-27 20:00:00 CST (UTC+0800)" in line for line in logs.output))

        def test_client_clock_is_bounded_to_four_hours(self):
                server_time = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
                request = client.createKmsRequestBase()
                with patch.object(base.time, "time", return_value=server_time.timestamp()):
                        for offset in (-4, 0, 4):
                                with self.subTest(offset=offset):
                                        request["requestTime"] = filetimes.dt_to_filetime(
                                                server_time + timedelta(hours=offset)
                                        )
                                        base.kmsBase(None, self.config).serverLogic(request)
                        for offset in (-4.001, 4.001):
                                with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "four hours"):
                                        request["requestTime"] = filetimes.dt_to_filetime(
                                                server_time + timedelta(hours=offset)
                                        )
                                        base.kmsBase(None, self.config).serverLogic(request)

        def test_missing_timezone_data_falls_back_to_utc(self):
                def missing_zone():
                        raise ZoneInfoNotFoundError("missing")

                tzlocal = types.SimpleNamespace(get_localzone=missing_zone)
                with patch.dict(sys.modules, {"tzlocal": tzlocal}):
                        response = base.kmsBase(None, self.config).serverLogic(client.createKmsRequestBase())
                self.assertEqual(response["versionMajor"], 6)

        def test_client_socket_closes_on_success_and_failure(self):
                for error in (None, RuntimeError("request failed")):
                        with self.subTest(error=error), closing(socket.socket()) as sock, \
                             patch.object(client, "client_options"), patch.object(client, "client_check"), \
                             patch.object(client, "client_update"), \
                             patch.object(client, "client_connect", return_value=sock), \
                             patch.object(client, "client_create", side_effect=error):
                                if error is None:
                                        client.clt_main()
                                else:
                                        with self.assertRaisesRegex(RuntimeError, "request failed"):
                                                client.clt_main()
                                self.assertEqual(sock.fileno(), -1)

        def test_without_optional_tzlocal(self):
                with patch.dict(sys.modules, {"tzlocal": None}):
                        response = base.kmsBase(None, self.config).serverLogic(client.createKmsRequestBase())
                self.assertEqual(response["versionMajor"], 6)

        def test_v4_v5_v6_over_loopback_with_sqlite(self):
                with tempfile.TemporaryDirectory(prefix="kms-py314-") as tmp, patch.dict(server.srv_config, clear=True):
                        db = str(Path(tmp) / "requests.db")
                        server.srv_config.update(self.config, sqlite=db, timeoutsndrcv=3)
                        listener = server.KeyServer([("127.0.0.1", 0, 5, False)], server.kmsServerHandler)
                        port = listener.multisock.getsockname()[1]
                        server.srv_config["port"] = port
                        worker = threading.Thread(target=listener.hyx_kms_serve, daemon=True)
                        worker.start()
                        try:
                                for mode, version in (("Windows7", 4), ("Windows8", 5), ("Windows8.1", 6)):
                                        with self.subTest(version=version):
                                                result = subprocess.run(
                                                        [sys.executable, "-B", "-W", "error", str(SOURCE / "hyx_kms_client.py"),
                                                         "127.0.0.1", str(port), "-m", mode, "-n", "PY314-TEST",
                                                         "-t0", "3", "-t1", "3", "-F", "STDOUT", "-V", "INFO"],
                                                        cwd=tmp, capture_output=True, text=True, timeout=12,
                                                )
                                                self.assertEqual(result.returncode, 0, result.stderr)
                                                self.assertEqual(result.stderr, "")
                                                self.assertIn("KMS Host ePID:", result.stdout)
                                                self.assertIn("KMS Host Current Client Count: 50", result.stdout)
                                                self.assertIn("KMS VL Renewal Interval: 10080", result.stdout)
                                with closing(sqlite3.connect(db)) as con:
                                        rows = con.execute("SELECT machineName, kmsEpid, requestCount FROM clients").fetchall()
                                self.assertEqual(len(rows), 3)
                                self.assertTrue(all(name == "PY314-TEST" and epid and count == 1 for name, epid, count in rows))
                        finally:
                                listener.shutdown()
                                listener.w_service.sendall(b"stop")
                                worker.join(timeout=3)
                                listener.server_close()
                                listener.r_service.close()
                                listener.w_service.close()
                        self.assertFalse(worker.is_alive())


class InfrastructureCompatibilityTests(unittest.TestCase):
        def test_etrigan_signature_introspection_without_getargspec(self):
                daemon = Etrigan(default_pidfile(), logfile=None, mute=True)

                def sample(first, second=None):
                        return first, second

                self.assertEqual(daemon.exclude(sample)[0], ["first", "second"])
                self.assertEqual(daemon.exclude(lambda: None)[0], [])

        def test_multiple_listener_context_manager_closes_sockets(self):
                fake_socket = socket.socket()
                self.addCleanup(fake_socket.close)
                with patch("hyx_kms_connect.create_server_sock", return_value=fake_socket) as create:
                        with MultipleListener([("127.0.0.1", 0, 5, False)]) as listener:
                                sockets = list(listener.socks)
                                self.assertEqual(sockets, [fake_socket])
                                self.assertGreaterEqual(fake_socket.fileno(), 0)
                self.assertEqual(fake_socket.fileno(), -1)
                create.assert_called_once()

        def test_server_bind_failure_does_not_create_service_socketpair(self):
                bind_error = RuntimeError("bind failed")
                with patch.object(server, "MultipleListener", side_effect=bind_error), \
                     patch.object(server, "pretty_printer", side_effect=SystemExit(1)), \
                     patch.object(server.socket, "socketpair") as socketpair, \
                     self.assertRaises(SystemExit):
                        server.KeyServer([("127.0.0.1", 0, 5, False)], server.kmsServerHandler)
                socketpair.assert_not_called()

        def test_sql_initialize_populates_an_existing_empty_database(self):
                import hyx_kms_sql

                with tempfile.TemporaryDirectory(prefix="kms-sql-") as tmp:
                        database = Path(tmp) / "requests.db"
                        database.touch()
                        hyx_kms_sql.sql_initialize(str(database))
                        with closing(sqlite3.connect(database)) as connection:
                                columns = connection.execute("PRAGMA table_info(clients)").fetchall()
                                count = connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
                self.assertEqual(
                        [column[1] for column in columns],
                        [
                                "clientMachineId", "machineName", "applicationId",
                                "skuId", "licenseStatus", "lastRequestTime",
                                "kmsEpid", "requestCount",
                        ],
                )
                self.assertEqual(count, 0)

        def test_daemon_config_json_roundtrip_and_permissions(self):
                config = {
                        "bytes": b"\x00\xffHYX",
                        "tuple": ("nested", (1, 2)),
                        "list": [b"item", None, True],
                        "port": 1688,
                }
                with tempfile.TemporaryDirectory(prefix="kms-daemon-") as tmp:
                        path = Path(tmp) / "daemon.json"
                        with patch.object(server, "_daemon_config_path", return_value=str(path)):
                                server._save_daemon_config(config)
                                loaded = server._load_daemon_config()
                        self.assertEqual(loaded, config)
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["bytes"]["__type__"], "bytes")

        def test_daemon_config_rejects_unknown_typed_value(self):
                with tempfile.TemporaryDirectory(prefix="kms-daemon-") as tmp:
                        path = Path(tmp) / "daemon.json"
                        path.write_text('{"__type__": "object", "value": []}', encoding="utf-8")
                        os.chmod(path, 0o600)
                        with patch.object(server, "_daemon_config_path", return_value=str(path)), \
                             self.assertRaisesRegex(ValueError, "Unknown daemon configuration type"):
                                server._load_daemon_config()

        def test_daemon_pidfile_is_private_and_does_not_follow_symlinks(self):
                self.assertTrue(Path(default_pidfile()).name.startswith("HYX-KMS-PY_etrigan_"))
                daemon = Etrigan(default_pidfile(), logfile=None, mute=True)
                with tempfile.TemporaryDirectory(prefix="kms-pid-") as tmp:
                        path = Path(tmp) / "daemon.pid"
                        daemon.pidfile = str(path)
                        daemon.create_pidfile()
                        if os.name != "nt":
                                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                        self.assertEqual(daemon.get_pidfile(), os.getpid())
                        daemon.delete_pidfile(os.getpid())
                        self.assertFalse(path.exists())

                if os.name != "nt" and hasattr(os, "O_NOFOLLOW"):
                        with tempfile.TemporaryDirectory(prefix="kms-pid-") as tmp:
                                target = Path(tmp) / "target.pid"
                                target.write_text(str(os.getpid()), encoding="ascii")
                                link = Path(tmp) / "link.pid"
                                link.symlink_to(target)
                                daemon.pidfile = str(link)
                                self.assertIsNone(daemon.get_pidfile())
                                self.assertEqual(target.read_text(encoding="ascii"), str(os.getpid()))

        def test_daemon_start_status_stop_real_lifecycle(self):
                with tempfile.TemporaryDirectory(prefix="kms-daemon-life-") as tmp:
                        environment = dict(os.environ, TMPDIR=tmp)
                        environment.pop("KMS_ALLOWED_NETWORKS", None)
                        pidfile = str(Path(tmp) / "daemon.pid")
                        logfile = str(Path(tmp) / "daemon.log")
                        server_logfile = str(Path(tmp) / "server.log")
                        with socket.socket() as reserve:
                                reserve.bind(("127.0.0.1", 0))
                                port = reserve.getsockname()[1]
                        prefix = [
                                sys.executable, "-B", str(SOURCE / "hyx_kms_server.py"),
                                "127.0.0.1", str(port), "-F", server_logfile, "-V", "DEBUG",
                                "etrigan",
                        ]
                        options = [
                                "--etrigan-pid", pidfile,
                                "--etrigan-log", logfile, "--etrigan-mute",
                        ]
                        start = subprocess.run(
                                prefix + ["start"] + options, cwd=tmp, env=environment,
                                capture_output=True, text=True, timeout=15,
                        )
                        self.assertEqual(start.returncode, 0, start.stderr)
                        try:
                                daemon_pid = int(Path(pidfile).read_text(encoding="ascii").strip())
                                deadline = time.monotonic() + 8
                                while True:
                                        try:
                                                from hyx_kms_health import probe_kms
                                                probe_kms("127.0.0.1", port)
                                                probe_kms("127.0.0.1", port)
                                                break
                                        except (OSError, EOFError, ValueError):
                                                if time.monotonic() >= deadline:
                                                        log_tail = Path(logfile).read_text(
                                                                encoding="utf-8", errors="replace"
                                                        )[-4000:] if Path(logfile).exists() else "<missing>"
                                                        server_tail = Path(server_logfile).read_text(
                                                                encoding="utf-8", errors="replace"
                                                        )[-4000:] if Path(server_logfile).exists() else "<missing>"
                                                        self.fail("daemon KMS listener did not become ready:\n" + log_tail + "\n" + server_tail)
                                                time.sleep(0.05)
                                duplicate = subprocess.run(
                                        prefix + ["start"] + options, cwd=tmp, env=environment,
                                        capture_output=True, text=True, timeout=15,
                                )
                                self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
                                os.kill(daemon_pid, 0)
                                status = subprocess.run(
                                        [sys.executable, "-B", str(SOURCE / "hyx_kms_server.py"),
                                         "etrigan", "status"],
                                        cwd=tmp, env=environment,
                                        capture_output=True, text=True, timeout=10,
                                )
                                self.assertEqual(status.returncode, 0, status.stderr)
                                self.assertTrue(Path(pidfile).is_file())
                                probe_kms("127.0.0.1", port)
                        finally:
                                stop = subprocess.run(
                                        [sys.executable, "-B", str(SOURCE / "hyx_kms_server.py"),
                                         "etrigan", "stop"],
                                        cwd=tmp, env=environment,
                                        capture_output=True, text=True, timeout=15,
                                )
                                self.assertEqual(stop.returncode, 0, stop.stderr)
                                deadline = time.monotonic() + 5
                                while Path(pidfile).exists() and time.monotonic() < deadline:
                                        time.sleep(0.05)
                                self.assertFalse(Path(pidfile).exists())
                                with self.assertRaises(ProcessLookupError):
                                        os.kill(daemon_pid, 0)
                                stopped = subprocess.run(
                                        [sys.executable, "-B", str(SOURCE / "hyx_kms_server.py"),
                                         "etrigan", "status"],
                                        cwd=tmp, env=environment,
                                        capture_output=True, text=True, timeout=10,
                                )
                                self.assertEqual(stopped.returncode, 3)


class RpcResponseCompatibilityTests(unittest.TestCase):
        def setUp(self):
                self.config = {"port": 1688, "call_id": 7}
                self.bind_printer = patch.object(rpc_bind, "pretty_printer").start()
                self.request_printer = patch.object(rpc_request, "pretty_printer").start()
                self.addCleanup(self.request_printer.stop)
                self.addCleanup(self.bind_printer.stop)

        def test_bind_response_parses_serialized_ack(self):
                request_wire = enco(str(rpc_bind.handler(None, self.config).generateRequest()), "latin-1")
                request = rpc_bind.handler(request_wire, self.config).parseRequest()
                response = rpc_bind.handler(request_wire, self.config).generateResponse(request)
                response_wire = enco(str(response), "latin-1")
                parsed = rpc_bind.handler(response_wire, self.config).parseResponse()
                self.assertEqual(parsed["type"], rpc_bind.handler.packetType["bindAck"])
                self.assertEqual(parsed["call_id"], self.config["call_id"])
                self.assertEqual(parsed["frag_len"], len(response_wire))
                self.assertEqual(parsed["ctx_num"], 2)

        def test_message_response_parses_serialized_header(self):
                response = MSRPCRespHeader()
                response["representation"] = 0x10
                response["flags"] = 3
                response["call_id"] = 19
                response["ctx_id"] = 1
                response["alloc_hint"] = 5
                response["pduData"] = b"probe"
                response_wire = enco(str(response), "latin-1")
                parsed = rpc_request.handler(response_wire, self.config).parseResponse()
                self.assertEqual(parsed["type"], rpc_request.handler.packetType["response"])
                self.assertEqual(parsed["call_id"], 19)
                self.assertEqual(parsed["ctx_id"], 1)
                self.assertEqual(parsed["pduData"], b"probe")
                self.assertEqual(parsed["frag_len"], len(response_wire))


if __name__ == "__main__":
        unittest.main()
