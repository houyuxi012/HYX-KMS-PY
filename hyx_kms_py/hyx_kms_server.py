#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import sqlite3
import struct
from hyx_kms_budget import KmsSourcePolicy, SourceConnectionLimiter, env_int, validate_environment
from hyx_kms_transport import recv_pdu, DEFAULT_IO_TIMEOUT, DEFAULT_CONNECTION_LIFETIME

import binascii
import json
import re
import sys
import socket
import uuid
import logging
import os
import threading
import socketserver
import queue as Queue
import selectors
from importlib.util import find_spec
from getpass import getuser
from tempfile import gettempdir, mkstemp
from time import monotonic as time

import hyx_kms_rpc_bind, hyx_kms_rpc_request
from hyx_kms_rpc_base import rpcBase
from hyx_kms_dcerpc import MSRPCHeader
from hyx_kms_misc import check_setup, check_lcid, check_dir, check_other
from hyx_kms_misc import KmsParser, KmsParserException, KmsParserHelp
from hyx_kms_misc import kms_parser_get, kms_parser_check_optionals, kms_parser_check_positionals, kms_parser_check_connect
from hyx_kms_format import enco, deco, pretty_printer, justify
from Etrigan import Etrigan, Etrigan_parser, Etrigan_check, Etrigan_job
from hyx_kms_connect import MultipleListener

srv_version             = "HYX-KMS-PY_2026.11.02-rc.2"
__license__             = "The Unlicense"
__author__              = u"Matteo ℱan <SystemRage@protonmail.com>"
__url__                 = "docs/index.rst"
srv_description         = "HYX-KMS-PY: KMS Server Emulator written in Python"
srv_config = {}


def _daemon_config_path():
        identity = str(os.getuid()) if hasattr(os, 'getuid') else re.sub(r'[^A-Za-z0-9_.-]', '_', getuser())
        return os.path.join(gettempdir(), 'HYX-KMS-PY_config_%s.json' % identity)


def _encode_daemon_config(value):
        if isinstance(value, bytes):
                return {'__type__': 'bytes', 'value': value.hex()}
        if isinstance(value, tuple):
                return {'__type__': 'tuple', 'value': [_encode_daemon_config(item) for item in value]}
        if isinstance(value, list):
                return [_encode_daemon_config(item) for item in value]
        if isinstance(value, dict):
                return {key: _encode_daemon_config(item) for key, item in value.items()}
        if value is None or isinstance(value, (str, int, float, bool)):
                return value
        raise TypeError("Unsupported daemon configuration value: %s" % type(value).__name__)


def _decode_daemon_config(value):
        if isinstance(value, list):
                return [_decode_daemon_config(item) for item in value]
        if isinstance(value, dict):
                if set(value) == {'__type__', 'value'}:
                        value_type = value['__type__']
                        if value_type == 'bytes':
                                return bytes.fromhex(value['value'])
                        if value_type == 'tuple':
                                decoded = [_decode_daemon_config(item) for item in value['value']]
                                return tuple(decoded)
                        raise ValueError("Unknown daemon configuration type: %s" % value_type)
                return {key: _decode_daemon_config(item) for key, item in value.items()}
        return value


def _save_daemon_config(config):
        target = _daemon_config_path()
        fd, temporary = mkstemp(prefix = 'HYX-KMS-PY_config-', suffix = '.tmp', dir = gettempdir())
        try:
                with os.fdopen(fd, 'w', encoding = 'utf-8') as file:
                        json.dump(_encode_daemon_config(config), file, ensure_ascii = False, sort_keys = True)
                        file.write('\n')
                os.replace(temporary, target)
        except BaseException:
                try:
                        os.close(fd)
                except OSError:
                        pass
                try:
                        os.remove(temporary)
                except OSError:
                        pass
                raise


def _load_daemon_config():
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(_daemon_config_path(), flags)
        try:
                stat_result = os.fstat(fd)
                if stat_result.st_size > 65536:
                        raise ValueError("Daemon configuration file is too large.")
                if hasattr(os, 'getuid') and stat_result.st_uid != os.getuid():
                        raise PermissionError("Daemon configuration file is owned by another user.")
                with os.fdopen(fd, 'r', encoding = 'utf-8') as file:
                        fd = None
                        config = json.load(file)
        finally:
                if fd is not None:
                        os.close(fd)
        if not isinstance(config, dict):
                raise ValueError("Daemon configuration must be a JSON object.")
        return _decode_daemon_config(config)


##---------------------------------------------------------------------------------------------------------------------------------------------------------
class KeyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True

        def __init__(self, server_address, RequestHandlerClass, bind_and_activate = True, want_dual = False):
                socketserver.BaseServer.__init__(self, server_address, RequestHandlerClass)
                self.__shutdown_request = False
                self._source_policy = KmsSourcePolicy.from_environment(server_address)
                limit = int(os.environ.get('KMS_MAX_CONNECTIONS', '64'))
                if not 1 <= limit <= 4096:
                        raise ValueError('KMS_MAX_CONNECTIONS must be 1..4096')
                lifetime = float(os.environ.get('KMS_CONNECTION_LIFETIME', DEFAULT_CONNECTION_LIFETIME))
                if not math.isfinite(lifetime) or not 0 < lifetime <= 300:
                        raise ValueError('KMS_CONNECTION_LIFETIME must be in (0,300]')
                self.connection_lifetime = lifetime
                validate_environment()
                if srv_config.get('sqlite'):
                        from hyx_kms_sql import sql_initialize
                        sql_initialize(srv_config['sqlite'])
                self._connection_limiter = SourceConnectionLimiter(
                    limit, env_int('KMS_MAX_CONNECTIONS_PER_SOURCE', 16)
                )
                self._connection_lock = threading.Lock()
                self._active_connections = {}
                self._closing = False

                if hasattr(selectors, 'PollSelector'):
                        self._ServerSelector = selectors.PollSelector
                else:
                        self._ServerSelector = selectors.SelectSelector

                if bind_and_activate:
                        try:
                                self.multisock = MultipleListener(server_address, want_dual = want_dual)
                        except Exception as e:
                                if want_dual and str(e) == "dualstack_ipv6 not supported on this platform":
                                        try:
                                                pretty_printer(log_obj = loggersrv.warning,
                                                               put_text = "{reverse}{yellow}{bold}%s. Creating not dualstack sockets...{end}" %str(e))
                                                self.multisock = MultipleListener(server_address, want_dual = False)
                                        except Exception as e:
                                                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                                               put_text = "{reverse}{red}{bold}%s. Exiting...{end}" %str(e))
                                else:
                                        pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                                       put_text = "{reverse}{red}{bold}%s. Exiting...{end}" %str(e))

                        if self.multisock.cant_dual:
                                delim = ('' if len(self.multisock.cant_dual) == 1 else ', ')
                                pretty_printer(log_obj = loggersrv.warning,
                                               put_text = "{reverse}{yellow}{bold}IPv4 [%s] can't be dualstack{end}" %delim.join(self.multisock.cant_dual))

                try:
                        self.r_service, self.w_service = socket.socketpair()
                except BaseException:
                        if bind_and_activate:
                                self.multisock.close()
                        raise


        def process_request(self, request, client_address):
                source = client_address[0]
                if not self._source_policy.allows(source):
                        self.shutdown_request(request)
                        return
                if not self._connection_limiter.try_acquire(source):
                        self.shutdown_request(request)
                        return
                with self._connection_lock:
                        if self._closing:
                                self._connection_limiter.release(source)
                                self.shutdown_request(request)
                                return
                        self._active_connections[request] = source
                try:
                        super().process_request(request, client_address)
                except BaseException:
                        self._release_connection(request)
                        raise

        def process_request_thread(self, request, client_address):
                try:
                        super().process_request_thread(request, client_address)
                finally:
                        self._release_connection(request)

        def _release_connection(self, request):
                with self._connection_lock:
                        source = self._active_connections.pop(request, None)
                if source is not None:
                        self._connection_limiter.release(source)

        def hyx_kms_serve(self):
                """ Mixing of socketserver serve_forever() and handle_request() functions,
                    without elements blocking tkinter.
                    Handle one request at a time, possibly blocking.
                    Respects self.timeout.
                """
                # Support people who used socket.settimeout() to escape
                # hyx_kms_serve() before self.timeout was available.
                timeout = self.multisock.gettimeout()
                if timeout is None:
                        timeout = self.timeout
                elif self.timeout is not None:
                        timeout = min(timeout, self.timeout)
                if timeout is not None:
                        deadline = time() + timeout

                try:
                        # Wait until a request arrives or the timeout expires.
                        with self._ServerSelector() as selector:
                                self.multisock.register(selector)
                                # self-pipe trick.
                                selector.register(fileobj = self.r_service.fileno(), events = selectors.EVENT_READ)

                                while not self.__shutdown_request:
                                        ready = selector.select(timeout)
                                        if self.__shutdown_request:
                                                break

                                        if ready == []:
                                                if timeout is not None:
                                                        timeout = deadline - time()
                                                        if timeout < 0:
                                                                return self.handle_timeout()
                                        else:
                                                for key, mask in ready:
                                                        if key.fileobj in self.multisock.filenos():
                                                                self.socket = self.multisock.sockmap[key.fileobj]
                                                                self.server_address = self.socket.getsockname()
                                                                self._handle_request_noblock()
                                                        elif key.fileobj is self.r_service.fileno():
                                                                # Drain the shutdown wake-up byte. A manual
                                                                # GUI stop does not request process exit.
                                                                os.read(self.r_service.fileno(), 8)
                finally:
                        self.__shutdown_request = False

        def shutdown(self):
                self.__shutdown_request = True
                try:
                        os.write(self.w_service.fileno(), b'\x00')
                except OSError:
                        pass

        def server_close(self):
                with self._connection_lock:
                        self._closing = True
                        active = list(self._active_connections)
                for request in active:
                        try:
                                request.shutdown(socket.SHUT_RDWR)
                        except OSError:
                                pass
                        request.close()
                try:
                        self.r_service.close()
                        self.w_service.close()
                finally:
                        self.multisock.close()

        def handle_timeout(self):
                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                               put_text = "{reverse}{red}{bold}Server connection timed out. Exiting...{end}")

        def handle_error(self, request, client_address):
                loggersrv.exception("Unhandled error while serving %s:%s", *client_address[:2])


class server_thread(threading.Thread):
        def __init__(self, queue, name):
                threading.Thread.__init__(self)
                self.name = name
                self.queue = queue
                self.server = None
                self.error = None
                self.is_running_server, self.with_gui, self.checked = [False for _ in range(3)]
                self.is_running_thread = threading.Event()

        def terminate_serve(self):
                if self.server is not None:
                        self.server.shutdown()

        def terminate_thread(self):
                self.is_running_thread.set()
                self.terminate_serve()
                self.terminate_eject()

        def terminate_eject(self):
                if self.server is not None:
                        try:
                                os.write(self.server.w_service.fileno(), b'\x00')
                        except OSError:
                                pass

        def run(self):
                while not self.is_running_thread.is_set():
                        try:
                                item = self.queue.get(block = True, timeout = 0.1)
                                self.queue.task_done()
                        except Queue.Empty:
                                continue
                        else:
                                try:
                                        if item == 'start':
                                                self.eject = False
                                                self.is_running_server = True
                                                # Check options.
                                                if not self.checked:
                                                        server_check()
                                                # Create and run server.
                                                self.server = server_create()
                                                self.server.hyx_kms_serve()
                                except (SystemExit, Exception) as e:
                                        self.eject = True
                                        self.error = e
                                        loggersrv.exception("KMS server thread stopped unexpectedly")
                                        if not self.with_gui:
                                                raise
                                        else:
                                                if isinstance(e, SystemExit):
                                                        continue
                                                else:
                                                        raise
                                finally:
                                        if self.server is not None:
                                                self.server.server_close()
                                                self.server = None
                                        self.is_running_server = False

##---------------------------------------------------------------------------------------------------------------------------------------------------------

loggersrv = logging.getLogger('logsrv')

# 'help' string - 'default' value - 'dest' string.
srv_options = {
        'ip'         : {'help' : 'The IP address (IPv4 or IPv6) to listen on. The default is \"0.0.0.0\" (all interfaces).', 'def' : "0.0.0.0", 'des' : "ip"},
        'port'       : {'help' : 'The network port to listen on. The default is \"1688\".', 'def' : 1688, 'des' : "port"},
        'epid'       : {'help' : 'Use this option to manually specify an ePID to use. If no ePID is specified, a random ePID will be auto generated.',
                        'def' : None, 'des' : "epid"},
        'lcid'       : {'help' : 'Use this option to manually specify an LCID for use with randomly generated ePIDs. Default is \"1033\" (en-us)',
                        'def' : 1033, 'des' : "lcid"},
        'count'      : {'help' : 'Use this option to specify the current client count. A number >=25 is required to enable activation of client OSes; \
for server OSes and Office >=5', 'def' : None, 'des' : "clientcount"},
        'activation' : {'help' : 'Use this option to specify the activation interval (in minutes). Default is \"120\" minutes (2 hours).',
                        'def' : 120, 'des': "activation"},
        'renewal'    : {'help' : 'Use this option to specify the renewal interval (in minutes). Default is \"10080\" minutes (7 days).',
                        'def' : 1440 * 7, 'des' : "renewal"},
        'sql'        : {'help' : 'Use this option to store request information from unique clients in an SQLite database. Deactivated by default. \
If enabled the default .db file is \"HYX-KMS-PY_database.db\". You can also provide a specific location.', 'def' : False,
                        'file': os.path.join('.', 'HYX-KMS-PY_database.db'), 'des' : "sqlite"},
        'hwid'       : {'help' : 'Use this option to specify a HWID. The HWID must be an 16-character string of hex characters. \
The default is \"364F463A8863D35F\" or type \"RANDOM\" to auto generate the HWID.',
                        'def' : "364F463A8863D35F", 'des' : "hwid"},
        'time0'      : {'help' : 'Maximum inactivity time (in seconds) after which the connection with the client is closed. If \"None\" (default) serve forever.',
                        'def' : None, 'des' : "timeoutidle"},
        'time1'      : {'help' : 'Set the maximum time to wait for sending / receiving a request / response. Default (unset) is an effective 5-second timeout.',
                        'def' : None, 'des' : "timeoutsndrcv"},
        'asyncmsg'   : {'help' : 'Prints pretty / logging messages asynchronously. Deactivated by default.',
                        'def' : False, 'des' : "asyncmsg"},
        'llevel'     : {'help' : 'Use this option to set a log level. The default is \"ERROR\".', 'def' : "ERROR", 'des' : "loglevel",
                        'choi' : ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "MININFO"]},
        'lfile'      : {'help' : 'Use this option to set an output log file. The default is \"HYX-KMS-PY_server.log\". \
Type \"STDOUT\" to view log info on stdout. Type \"FILESTDOUT\" to combine previous actions. \
Use \"STDOUTOFF\" to disable stdout messages. Use \"FILEOFF\" if you not want to create logfile.',
                        'def' : os.path.join('.', 'HYX-KMS-PY_server.log'), 'des' : "logfile"},
        'lsize'      : {'help' : 'Use this flag to set a maximum size (in MB) to the output log file. Deactivated by default.', 'def' : 0, 'des': "logsize"},
        'listen'     : {'help' : 'Adds multiple listening ip address - port couples.', 'des': "listen"},
        'backlog'    : {'help' : 'Specifies the maximum length of the queue of pending connections. Default is \"5\".', 'def' : 5, 'des': "backlog"},
        'reuse'      : {'help' : 'Do not allows binding / listening to the same address and port. Reusing port is activated by default.', 'def' : True,
                        'des': "reuse"},
        'dual'       : {'help' : 'Allows listening to an IPv6 address also accepting connections via IPv4. Deactivated by default.',
                        'def' : False, 'des': "dual"}
        }

def server_options():
        server_parser = KmsParser(description = srv_description, epilog = 'version: ' + srv_version, add_help = False)
        server_parser.add_argument("ip", nargs = "?", action = "store", default = srv_options['ip']['def'], help = srv_options['ip']['help'], type = str)
        server_parser.add_argument("port", nargs = "?", action = "store", default = srv_options['port']['def'], help = srv_options['port']['help'], type = int)
        server_parser.add_argument("-e", "--epid", action = "store", dest = srv_options['epid']['des'], default = srv_options['epid']['def'],
                                   help = srv_options['epid']['help'], type = str)
        server_parser.add_argument("-l", "--lcid", action = "store", dest = srv_options['lcid']['des'], default = srv_options['lcid']['def'],
                                   help = srv_options['lcid']['help'], type = int)
        server_parser.add_argument("-c", "--client-count", action = "store", dest = srv_options['count']['des'] , default = srv_options['count']['def'],
                                   help = srv_options['count']['help'], type = str)
        server_parser.add_argument("-a", "--activation-interval", action = "store", dest = srv_options['activation']['des'],
                                   default = srv_options['activation']['def'], help = srv_options['activation']['help'], type = int)
        server_parser.add_argument("-r", "--renewal-interval", action = "store", dest = srv_options['renewal']['des'],
                                   default = srv_options['renewal']['def'], help = srv_options['renewal']['help'], type = int)
        server_parser.add_argument("-s", "--sqlite", nargs = "?", dest = srv_options['sql']['des'], const = True,
                                   default = srv_options['sql']['def'], help = srv_options['sql']['help'], type = str)
        server_parser.add_argument("-w", "--hwid", action = "store", dest = srv_options['hwid']['des'], default = srv_options['hwid']['def'],
                                   help = srv_options['hwid']['help'], type = str)
        server_parser.add_argument("-t0", "--timeout-idle", action = "store", dest = srv_options['time0']['des'], default = srv_options['time0']['def'],
                                   help = srv_options['time0']['help'], type = str)
        server_parser.add_argument("-t1", "--timeout-sndrcv", action = "store", dest = srv_options['time1']['des'], default = srv_options['time1']['def'],
                                   help = srv_options['time1']['help'], type = str)
        server_parser.add_argument("-y", "--async-msg", action = "store_true", dest = srv_options['asyncmsg']['des'],
                                   default = srv_options['asyncmsg']['def'], help = srv_options['asyncmsg']['help'])
        server_parser.add_argument("-V", "--loglevel", action = "store", dest = srv_options['llevel']['des'], choices = srv_options['llevel']['choi'],
                                   default = srv_options['llevel']['def'], help = srv_options['llevel']['help'], type = str)
        server_parser.add_argument("-F", "--logfile", nargs = "+", action = "store", dest = srv_options['lfile']['des'],
                                   default = srv_options['lfile']['def'], help = srv_options['lfile']['help'], type = str)
        server_parser.add_argument("-S", "--logsize", action = "store", dest = srv_options['lsize']['des'], default = srv_options['lsize']['def'],
                                   help = srv_options['lsize']['help'], type = float)

        server_parser.add_argument("-h", "--help", action = "help", help = "show this help message and exit")

        ## Daemon (Etrigan) parsing.
        daemon_parser = KmsParser(description = "daemon options inherited from Etrigan", add_help = False)
        daemon_subparser = daemon_parser.add_subparsers(dest = "mode")

        etrigan_parser = daemon_subparser.add_parser("etrigan", add_help = False)
        etrigan_parser.add_argument("-g", "--gui", action = "store_const", dest = 'gui', const = True, default = False,
                                    help = "Enable HYX-KMS-PY GUI usage.")
        etrigan_parser = Etrigan_parser(parser = etrigan_parser)

        ## Connection parsing.
        connection_parser = KmsParser(description = "connect options", add_help = False)
        connection_subparser = connection_parser.add_subparsers(dest = "mode")

        connect_parser = connection_subparser.add_parser("connect", add_help = False)
        connect_parser.add_argument("-n", "--listen", action = "append", dest = srv_options['listen']['des'], default = [],
                                    help = srv_options['listen']['help'], type = str)
        connect_parser.add_argument("-b", "--backlog", action = "append", dest = srv_options['backlog']['des'], default = [],
                                    help = srv_options['backlog']['help'], type = int)
        connect_parser.add_argument("-u", "--no-reuse", action = "append_const", dest = srv_options['reuse']['des'], const = False, default = [],
                                    help = srv_options['reuse']['help'])
        connect_parser.add_argument("-d", "--dual", action = "store_true", dest = srv_options['dual']['des'], default = srv_options['dual']['def'],
                                    help = srv_options['dual']['help'])

        try:
                userarg = sys.argv[1:]

                # Run help.
                if any(arg in ["-h", "--help"] for arg in userarg):
                        KmsParserHelp().printer(parsers = [server_parser, (daemon_parser, etrigan_parser),
                                                           (connection_parser, connect_parser)])

                # Get stored arguments.
                hyx_kms_srv_zeroarg, hyx_kms_srv_onearg = kms_parser_get(server_parser)
                etrigan_zeroarg, etrigan_onearg = kms_parser_get(etrigan_parser)
                connect_zeroarg, connect_onearg = kms_parser_get(connect_parser)
                subdict = {'etrigan' : (etrigan_zeroarg, etrigan_onearg, daemon_parser.parse_args),
                           'connect' : (connect_zeroarg, connect_onearg, connection_parser.parse_args)
                           }
                subpars = list(subdict.keys())
                hyx_kms_srv_zeroarg += subpars # add subparsers

                exclude_kms = ['-F', '--logfile']
                exclude_dup = ['-n', '--listen', '-b', '--backlog', '-u', '--no-reuse']

                # Set defaults for server dict config.
                # example case:
                #       python3 hyx_kms_server.py
                srv_config.update(vars(server_parser.parse_args([])))

                subindx = sorted([(userarg.index(pars), pars) for pars in subpars if pars in userarg], key = lambda x: x[0])
                if subindx:
                        # Set `daemon options` and/or `connect options` for server dict config.
                        # example cases:
                        # 1     python3 hyx_kms_server.py [1.2.3.4] [1234] [--hyx_kms_optionals] etrigan daemon_positional [--daemon_optionals] \
                        #       connect [--connect_optionals]
                        #
                        # 2     python3 hyx_kms_server.py [1.2.3.4] [1234] [--hyx_kms_optionals] connect [--connect_optionals] etrigan \
                        #       daemon_positional [--daemon_optionals]
                        #
                        # 3     python3 hyx_kms_server.py [1.2.3.4] [1234] [--hyx_kms_optionals] etrigan daemon_positional [--daemon_optionals]
                        # 4     python3 hyx_kms_server.py [1.2.3.4] [1234] [--hyx_kms_optionals] connect [--connect_optionals]
                        first = subindx[0][0]
                        # initial.
                        kms_parser_check_optionals(userarg[0 : first], hyx_kms_srv_zeroarg, hyx_kms_srv_onearg, exclude_opt_len = exclude_kms)
                        kms_parser_check_positionals(srv_config, server_parser.parse_args, arguments = userarg[0 : first], force_parse = True)
                        # middle.
                        for i in range(len(subindx) - 1):
                                posi, posf, typ = subindx[i][0], subindx[i + 1][0], subindx[i][1]
                                kms_parser_check_optionals(userarg[posi : posf], subdict[typ][0], subdict[typ][1], msg = 'optional %s' %typ,
                                                           exclude_opt_dup = (exclude_dup if typ == 'connect' else []))
                                kms_parser_check_positionals(srv_config, subdict[typ][2], arguments = userarg[posi : posf], msg = 'positional %s' %typ)
                        # final.
                        pos, typ = subindx[-1]
                        kms_parser_check_optionals(userarg[pos:], subdict[typ][0], subdict[typ][1], msg = 'optional %s' %typ,
                                                   exclude_opt_dup = (exclude_dup if typ == 'connect' else []))
                        kms_parser_check_positionals(srv_config, subdict[typ][2], arguments = userarg[pos:], msg = 'positional %s' %typ)

                        if len(subindx) > 1:
                                srv_config['mode'] = '+'.join(elem[1] for elem in subindx)
                else:
                        # Update `HYX-KMS-PY options` for server dict config.
                        # example case:
                        # 5     python3 hyx_kms_server.py [1.2.3.4] [1234] [--hyx_kms_optionals]
                        kms_parser_check_optionals(userarg, hyx_kms_srv_zeroarg, hyx_kms_srv_onearg, exclude_opt_len = exclude_kms)
                        kms_parser_check_positionals(srv_config, server_parser.parse_args)

                kms_parser_check_connect(srv_config, srv_options, userarg, connect_zeroarg, connect_onearg)

        except KmsParserException as e:
                pretty_printer(put_text = "{reverse}{red}{bold}%s. Exiting...{end}" %str(e), to_exit = True)

class Etrigan_Check(Etrigan_check):
        def emit_opt_err(self, msg):
                pretty_printer(put_text = "{reverse}{red}{bold}%s{end}" %msg, to_exit = True)

class Etrigan(Etrigan):
        def emit_message(self, message, to_exit = False):
                if not self.mute:
                        pretty_printer(put_text = "{reverse}{green}{bold}%s{end}" %message)
                if to_exit:
                        sys.exit(0)

        def emit_error(self, message, to_exit = True):
                if not self.mute:
                        pretty_printer(put_text = "{reverse}{red}{bold}%s{end}" %message, to_exit = to_exit)
                elif to_exit:
                        sys.exit(1)

def server_daemon():
        if 'etrigan' in srv_config.values():
                if srv_config['operation'] in ['stop', 'restart', 'status'] and len(sys.argv[1:]) > 2:
                        pretty_printer(put_text = "{reverse}{red}{bold}too much arguments with etrigan '%s'. Exiting...{end}" %srv_config['operation'],
                                       to_exit = True)

                # Check file arguments.
                Etrigan_Check().checkfile(srv_config['etriganpid'], '--etrigan-pid', '.pid')
                Etrigan_Check().checkfile(srv_config['etriganlog'], '--etrigan-log', '.log')

                if srv_config['gui']:
                        pass
                else:
                        if srv_config['operation'] == 'start':
                                _save_daemon_config(srv_config)
                        elif srv_config['operation'] in ['stop', 'status', 'restart']:
                                old_srv_config = _load_daemon_config()
                                old_srv_config = {x: old_srv_config[x] for x in old_srv_config if x not in ['operation']}
                                srv_config.update(old_srv_config)

                serverdaemon = Etrigan(srv_config['etriganpid'],
                                       logfile = srv_config['etriganlog'], loglevel = srv_config['etriganlev'],
                                       mute = srv_config['etriganmute'], pause_loop = None)

                if srv_config['operation'] in ['start', 'restart']:
                        serverdaemon.want_quit = True
                        if srv_config['gui']:
                                serverdaemon.funcs_to_daemonize = [server_with_gui]
                        else:
                                server_without_gui = ServerWithoutGui()
                                serverdaemon.funcs_to_daemonize = [server_without_gui.start, server_without_gui.join]
                                indx_for_clean = lambda: (0, )
                                serverdaemon.quit_on_stop = [indx_for_clean, server_without_gui.clean]
                Etrigan_job(srv_config['operation'], serverdaemon)

def server_check():
        # Setup and some checks.
        check_setup(srv_config, srv_options, loggersrv, where = "srv")

        # Random HWID.
        if srv_config['hwid'] == "RANDOM":
                randomhwid = uuid.uuid4().hex
                srv_config['hwid'] = randomhwid[:16]
           
        # Sanitize HWID.
        hexstr = srv_config['hwid']
        # Strip 0x from the start of hexstr
        if hexstr.startswith("0x"):
            hexstr = hexstr[2:]

        hexsub = re.sub(r'[^0-9a-fA-F]', '', hexstr)
        diff = set(hexstr).symmetric_difference(set(hexsub))

        if len(diff) != 0:
                diff = str(diff).replace('{', '').replace('}', '')
                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                               put_text = "{reverse}{red}{bold}HWID '%s' is invalid. Digit %s non hexadecimal. Exiting...{end}" %(hexstr.upper(), diff))
        else:
                lh = len(hexsub)
                if lh % 2 != 0:
                        pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                       put_text = "{reverse}{red}{bold}HWID '%s' is invalid. Hex string is odd length. Exiting...{end}" %hexsub.upper())
                elif lh < 16:
                        pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                       put_text = "{reverse}{red}{bold}HWID '%s' is invalid. Hex string is too short. Exiting...{end}" %hexsub.upper())
                elif lh > 16:
                        pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                       put_text = "{reverse}{red}{bold}HWID '%s' is invalid. Hex string is too long. Exiting...{end}" %hexsub.upper())
                else:
                        srv_config['hwid'] = binascii.a2b_hex(hexsub)

        # Check LCID.
        srv_config['lcid'] = check_lcid(srv_config['lcid'], loggersrv.warning)
                                
        # Check sqlite.
        if srv_config['sqlite']:
                if isinstance(srv_config['sqlite'], str):
                        check_dir(srv_config['sqlite'], 'srv', log_obj = loggersrv.error, argument = '-s/--sqlite', typefile = '.db')
                elif srv_config['sqlite'] is True:
                        srv_config['sqlite'] = srv_options['sql']['file']

                if find_spec('sqlite3') is None:
                        pretty_printer(log_obj = loggersrv.warning,
                                       put_text = "{reverse}{yellow}{bold}Module 'sqlite3' not installed, database support disabled.{end}")
                        srv_config['sqlite'] = False

        # Check other specific server options.
        opts = [('clientcount', '-c/--client-count'),
                ('timeoutidle', '-t0/--timeout-idle'),
                ('timeoutsndrcv', '-t1/--timeout-sndrcv')]
        if serverthread.with_gui:
                opts += [('activation', '-a/--activation-interval'),
                         ('renewal', '-r/--renewal-interval')]
        check_other(srv_config, opts, loggersrv, where = 'srv')

        # Check further addresses / ports.
        if 'listen' in srv_config:
                addresses = []
                for elem in srv_config['listen']:
                        try:
                                addr, port = elem.split(',')
                        except ValueError:
                                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                               put_text = "{reverse}{red}{bold}argument `-n/--listen`: %s not well defined. Exiting...{end}" %elem)
                        try:
                                port = int(port)
                        except ValueError:
                                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                               put_text = "{reverse}{red}{bold}argument `-n/--listen`: port number '%s' is invalid. Exiting...{end}" %port)

                        if not (1 <= port <= 65535):
                                pretty_printer(log_obj = loggersrv.error, to_exit = True,
                                               put_text = "{reverse}{red}{bold}argument `-n/--listen`: port number '%s' is invalid. Enter between 1 - 65535. Exiting...{end}" %port)

                        addresses.append((addr, port))
                srv_config['listen'] = addresses

def server_create():
        # Create address list (when the current user indicates execution inside the Windows Sandbox,
        # then we wont allow port reuse - it is not supported).
        all_address = [(
                        srv_config['ip'], srv_config['port'],
                        (srv_config['backlog_main'] if 'backlog_main' in srv_config else srv_options['backlog']['def']),
                        (srv_config['reuse_main'] if 'reuse_main' in srv_config else False if getuser() == 'WDAGUtilityAccount' \
                         else srv_options['reuse']['def'])
                        )]
        log_address = "TCP server listening at %s on port %d" %(srv_config['ip'], srv_config['port'])

        if 'listen' in srv_config:
                for l, b, r in zip(srv_config['listen'], srv_config['backlog'], srv_config['reuse']):
                        r = (False if getuser() == 'WDAGUtilityAccount' else r)
                        all_address.append(l + (b,) + (r,))
                        log_address += justify("at %s on port %d" %(l[0], l[1]), indent = 56)

        server = KeyServer(all_address, kmsServerHandler, want_dual = (srv_config['dual'] if 'dual' in srv_config else srv_options['dual']['def']))
        server.timeout = srv_config['timeoutidle']

        loggersrv.info(log_address)
        loggersrv.info("HWID: %s" % deco(binascii.b2a_hex(srv_config['hwid']), 'utf-8').upper())

        return server

def server_terminate(generic_srv, exit_server = False, exit_thread = False):
        if exit_server:
                generic_srv.terminate_serve()
        if exit_thread:
                generic_srv.terminate_thread()

class ServerWithoutGui(object):
        def start(self):
                import queue as Queue
                daemon_queue = Queue.Queue(maxsize = 0)
                daemon_serverthread = server_thread(daemon_queue, name = "Thread-Srv-Daemon")
                daemon_serverthread.daemon = True
                # options already checked in `server_main_terminal`.
                daemon_serverthread.checked = True
                daemon_serverthread.start()
                daemon_queue.put('start')
                return 0, daemon_serverthread

        def join(self, daemon_serverthread):
                daemon_serverthread.join()
                if daemon_serverthread.error is not None:
                        raise RuntimeError("KMS server worker stopped unexpectedly") from daemon_serverthread.error

        def clean(self, daemon_serverthread):
                server_terminate(daemon_serverthread, exit_server = True, exit_thread = True)

def server_main_terminal():
        # Parse options.
        server_options()
        # Check options.
        server_check()
        serverthread.checked = True

        if 'etrigan' not in srv_config.values():
                # (without GUI) and (without daemon).
                # Run threaded server.
                ensure_server_thread_started(serverthread)
                serverqueue.put('start')
                # Wait to finish.
                try:
                        while serverthread.is_alive():
                                serverthread.join(timeout = 0.5)
                except (KeyboardInterrupt, SystemExit):
                        server_terminate(serverthread, exit_server = True, exit_thread = True)
        else:
                # (with or without GUI) and (with daemon)
                # Setup daemon (eventually).
                server_daemon()

def server_with_gui():
        import hyx_kms_gui_base

        ensure_server_thread_started(serverthread)
        root = hyx_kms_gui_base.KmsGui()
        root.title(hyx_kms_gui_base.gui_description + ' (' + hyx_kms_gui_base.gui_version + ')')
        root.mainloop()

def server_main_no_terminal():
        # Run tkinter GUI.
        # (with GUI) and (without daemon).
        server_with_gui()

class kmsServerHandler(socketserver.BaseRequestHandler):
        def setup(self):
                loggersrv.info("Connection accepted: %s:%d" %(self.client_address[0], self.client_address[1]))

        def handle(self):
                request_config = dict(srv_config)
                request_config['raddr'] = self.client_address
                timeout = request_config.get('timeoutsndrcv')
                timeout = DEFAULT_IO_TIMEOUT if timeout is None else timeout
                if not math.isfinite(timeout) or timeout <= 0:
                        raise ValueError('KMS IO timeout must be finite and positive')
                self.request.settimeout(timeout)
                deadline = time() + self.server.connection_lifetime
                try:
                        # One bind and one activation per connection; reject repeated binds.
                        self.data = recv_pdu(self.request, deadline)
                        if MSRPCHeader(self.data)['type'] != rpcBase.packetType['bindReq']:
                                raise ValueError('RPC bind required')
                        handler = hyx_kms_rpc_bind.handler(self.data, request_config)
                        ack = handler.populate()
                        self.request.sendall(enco(str(ack), 'latin-1'))
                        self.data = recv_pdu(self.request, deadline)
                        from hyx_kms_dcerpc import MSRPCRequestHeader
                        request = MSRPCRequestHeader(self.data)
                        if request['type'] != rpcBase.packetType['request'] or request['op_num'] != 0:
                                raise ValueError('Unsupported RPC operation')
                        if request['ctx_id'] not in handler.accepted_contexts:
                                raise ValueError('RPC context was not negotiated')
                        handler = hyx_kms_rpc_request.handler(self.data, request_config)
                        self.request.sendall(enco(str(handler.populate()), 'latin-1'))
                except (EOFError, ValueError, KeyError, OverflowError, struct.error, OSError, sqlite3.Error):
                        loggersrv.warning('Rejected invalid or incomplete RPC request from %s', self.client_address[0])

        def finish(self):
                self.request.close()
                loggersrv.info("Connection closed: %s:%d" %(self.client_address[0], self.client_address[1]))


serverqueue = Queue.Queue(maxsize = 0)
serverthread = server_thread(serverqueue, name = "Thread-Srv")
serverthread.daemon = True


def ensure_server_thread_started(worker):
        """Start a worker only after all process forking has completed."""
        if worker.ident is None:
                worker.start()

if __name__ == "__main__":
        if sys.stdout.isatty() or len(sys.argv) > 1:
                server_main_terminal()
        else:
                try:
                        server_main_no_terminal()
                except Exception:
                        server_main_terminal()
