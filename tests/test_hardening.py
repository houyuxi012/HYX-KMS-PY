"""Regression tests for audited resource and parser boundaries."""
import concurrent.futures
import os
import socket
import sqlite3
import struct
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hyx_kms_py'))
from hyx_kms_aes import AESModeOfOperation, strip_PKCS7_padding
from hyx_kms_transport import recv_pdu
from hyx_kms_sql import sql_initialize, sql_update
from hyx_kms_webui import app


class Chunks:
    def __init__(self, data, chunk=1): self.data, self.chunk = data, chunk
    def recv(self, n):
        out=self.data[:min(n,self.chunk)];self.data=self.data[len(out):];return out


def frame(body=b''):
    return struct.pack('<BBBBIHHI',5,0,11,3,16,16+len(body),0,1)+body


class HardeningTests(unittest.TestCase):
    def test_aes_instances_do_not_share_state(self):
        a,b=AESModeOfOperation(),AESModeOfOperation()
        self.assertIsNot(a.aes,b.aes)
        a.aes.v6=False;b.aes.v6=True
        self.assertFalse(a.aes.v6)

    def test_padding_rejects_zero_inconsistent_and_oversized(self):
        for value in (bytes(16),b'A'*15+b'\x02',b'A'*15+b'\x11'):
            with self.subTest(value=value),self.assertRaises(ValueError): strip_PKCS7_padding(value)
        self.assertEqual(strip_PKCS7_padding(b'A'*14+b'\x02\x02'),b'A'*14)

    def test_transport_handles_split_and_coalesced_frames(self):
        a,b=frame(b'one'),frame(b'two')
        sock=Chunks(a+b)
        self.assertEqual(recv_pdu(sock),a)
        self.assertEqual(recv_pdu(sock),b)
        with self.assertRaises(EOFError): recv_pdu(sock)

    def test_transport_rejects_truncated_oversized_fragmented(self):
        for value in (frame(b'x')[:-1],frame()[:8]+struct.pack('<H',65535)+frame()[10:],frame()[:3]+b'\x01'+frame()[4:]):
            with self.subTest(value=value),self.assertRaises((ValueError,EOFError)):recv_pdu(Chunks(value))

    def test_protocol_catalog_is_parsed_once_per_process(self):
        import hyx_kms_db2dict as database
        database.kmsDB2Dict.cache_clear()
        with patch.object(database.ET,'parse',wraps=database.ET.parse) as parse:
            self.assertIs(database.kmsDB2Dict(),database.kmsDB2Dict())
            self.assertEqual(parse.call_count,1)

    def test_sql_atomic_updates_and_capacity(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,KMS_MAX_CLIENTS='1'):
            path=str(Path(d)/'db');sql_initialize(path)
            if os.name != 'nt':
                self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
            info=dict(clientMachineId='one',machineName='host',appId='Windows',skuId='SKU',licenseStatus='Activated',requestTime=1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _:sql_update(path,info),range(16)))
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT count(*),sum(requestCount) FROM clients').fetchone(),(1,16))
            with self.assertRaises(ValueError):sql_update(path,dict(info,clientMachineId='two'))
            sql_update(path,info)
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT requestCount FROM clients').fetchone()[0],17)

    def test_legacy_duplicate_migration_preserves_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'db')
            with closing(sqlite3.connect(path)) as con, con:
                con.execute('CREATE TABLE clients(clientMachineId TEXT,machineName TEXT,applicationId TEXT,skuId TEXT,licenseStatus TEXT,lastRequestTime INTEGER,kmsEpid TEXT,requestCount INTEGER)')
                con.executemany('INSERT INTO clients VALUES(?,?,?,?,?,?,?,?)',[('one','old','Windows','s','a',1,'e',2),('one','new','Windows','s','a',2,'e',3)])
            sql_initialize(path);sql_initialize(path)
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT machineName,requestCount FROM clients').fetchall(),[('new',5)])
                self.assertEqual(con.execute('SELECT count(*) FROM clients_before_identity_migration').fetchone()[0],2)

    def test_missing_db_not_ready_but_alive(self):
        with patch.dict(os.environ, PYKMS_SQLITE_DB_PATH='/nonexistent/hyx.db'):
            c=app.test_client()
            self.assertEqual(c.get('/readyz', base_url='https://localhost').status_code,503)
            self.assertEqual(c.get('/livez', base_url='https://localhost').status_code,200)

    def test_pages_are_open_without_credentials(self):
        client = app.test_client()
        for address in ('127.0.0.1', '192.0.2.1'):
            with self.subTest(address=address):
                response = client.get(
                    '/activate',
                    base_url='https://localhost',
                    environ_base={'REMOTE_ADDR': address},
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('WWW-Authenticate', response.headers)

    def test_new_identity_budgets_bound_each_source(self):
        from hyx_kms_sql import sql_update
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, KMS_NEW_IDENTITY_PER_MIN='100', KMS_NEW_IDENTITY_PER_SOURCE_PER_MIN='2'):
            path=str(Path(d)/'db'); sql_initialize(path)
            base=dict(machineName='h', appId='Windows', skuId='S', licenseStatus='Activated', requestTime=1)
            sql_update(path, dict(base, clientMachineId='a1'), source='10.0.0.1')
            sql_update(path, dict(base, clientMachineId='a2'), source='10.0.0.1')
            with self.assertRaises(ValueError): sql_update(path, dict(base, clientMachineId='a3'), source='10.0.0.1')
            sql_update(path, dict(base, clientMachineId='b1'), source='10.0.0.2')
            sql_update(path, dict(base, clientMachineId='a1'), source='10.0.0.1')
            with closing(sqlite3.connect(path)) as con: self.assertEqual(con.execute('SELECT count(*) FROM clients').fetchone()[0], 3)

    def test_identity_budget_is_persistent_and_ipv6_is_grouped_by_64(self):
        from hyx_kms_sql import sql_update
        with tempfile.TemporaryDirectory() as d, patch.dict(
                os.environ, KMS_NEW_IDENTITY_PER_MIN='100',
                KMS_NEW_IDENTITY_PER_SOURCE_PER_MIN='2'):
            path = str(Path(d) / 'db')
            sql_initialize(path)
            base = dict(machineName='h', appId='Windows', skuId='S',
                        licenseStatus='Activated', requestTime=1)
            sql_update(path, dict(base, clientMachineId='a1'), source='2001:db8:1::1')
            sql_update(path, dict(base, clientMachineId='a2'), source='2001:db8:1::2')
            sql_initialize(path)
            with self.assertRaises(ValueError):
                sql_update(path, dict(base, clientMachineId='a3'), source='2001:db8:1::3')
            with closing(sqlite3.connect(path)) as con:
                self.assertGreater(con.execute(
                    'SELECT count(*) FROM identity_admission_budget').fetchone()[0], 0)

    def test_capacity_warning_logged_once(self):
        from hyx_kms_sql import sql_update, _CAPACITY_WARNED
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, KMS_MAX_CLIENTS='2', KMS_NEW_IDENTITY_PER_MIN='60'):
            _CAPACITY_WARNED.clear(); path=str(Path(d)/'db'); sql_initialize(path)
            with self.assertLogs('logsrv', 'WARNING') as logs:
                for i in (1, 2): sql_update(path, dict(machineName='h', clientMachineId=str(i), appId='W', skuId='S', licenseStatus='A', requestTime=1))
            self.assertEqual([line for line in logs.output if 'capacity at' in line], logs.output[:1])
            _CAPACITY_WARNED.clear()

    def test_secret_file_group_readable_fails_closed(self):
        if os.name == 'nt': self.skipTest('Unix file mode check')
        from hyx_kms_secrets import require_private_file
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'secret.pem'
            path.write_text('secret', encoding='utf-8')
            path.chmod(0o640)
            with self.assertRaisesRegex(ValueError, 'group or other'):
                require_private_file(path, 'TLS private key')
            path.chmod(0o600)
            self.assertEqual(require_private_file(path, 'TLS private key'), path)

    def test_windows_secret_acl_is_mandatory_and_fails_closed(self):
        import hyx_kms_secrets
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'private-key.pem'
            path.write_text('secret', encoding='utf-8')
            path.chmod(0o600)
            with patch.object(hyx_kms_secrets, 'IS_WINDOWS', True), \
                 patch.object(hyx_kms_secrets, '_windows_acl_is_private') as checker:
                self.assertEqual(
                    str(hyx_kms_secrets.require_private_file(path, 'TLS private key')),
                    str(path),
                )
                checker.assert_called_once()
                checker.reset_mock()
                checker.side_effect = ValueError('unsafe ACL')
                with self.assertRaisesRegex(ValueError, 'unsafe ACL'):
                    hyx_kms_secrets.require_private_file(path, 'TLS private key')

    def test_token_bucket_state_is_bounded_and_can_release_success(self):
        from hyx_kms_budget import TokenBuckets
        now=[0.0]
        buckets=TokenBuckets(max_entries=2,idle_seconds=30,clock=lambda: now[0])
        limits=[('source',2)]
        self.assertTrue(buckets.try_acquire(limits))
        buckets.release(limits)
        self.assertTrue(buckets.try_acquire(limits))
        self.assertTrue(buckets.try_acquire([('other',2)]))
        self.assertTrue(buckets.try_acquire([('third',2)]))
        self.assertLessEqual(len(buckets._state),2)
        now[0]=100.0
        self.assertTrue(buckets.try_acquire([('fresh',2)]))
        self.assertEqual(list(buckets._state),['fresh'])

    def test_source_connection_limiter_bounds_each_source(self):
        from hyx_kms_budget import SourceConnectionLimiter
        limiter=SourceConnectionLimiter(global_limit=3,per_source_limit=2)
        self.assertTrue(limiter.try_acquire('10.0.0.1'))
        self.assertTrue(limiter.try_acquire('10.0.0.1'))
        self.assertFalse(limiter.try_acquire('10.0.0.1'))
        self.assertTrue(limiter.try_acquire('10.0.0.2'))
        self.assertFalse(limiter.try_acquire('10.0.0.3'))
        self.assertTrue(limiter.release('10.0.0.1'))
        self.assertTrue(limiter.try_acquire('10.0.0.3'))
        self.assertTrue(limiter.release('10.0.0.1'))
        self.assertTrue(limiter.release('10.0.0.2'))
        self.assertTrue(limiter.release('10.0.0.3'))

    def test_non_loopback_kms_bind_requires_explicit_source_networks(self):
        import hyx_kms_server as server
        with patch.dict(os.environ, KMS_ALLOWED_NETWORKS=''):
            with self.assertRaisesRegex(ValueError, 'KMS_ALLOWED_NETWORKS'):
                server.KeyServer([('0.0.0.0', 0, 5, False)], server.kmsServerHandler,
                                 bind_and_activate=False)
        with patch.dict(os.environ, KMS_ALLOWED_NETWORKS='192.0.2.0/24'):
            instance = server.KeyServer([('127.0.0.1', 0, 5, False)],
                                        server.kmsServerHandler, bind_and_activate=False)
            try:
                self.assertTrue(instance._source_policy.allows('192.0.2.10'))
                self.assertFalse(instance._source_policy.allows('198.51.100.10'))
                self.assertTrue(instance._source_policy.allows('127.0.0.1'))
            finally:
                instance.r_service.close()
                instance.w_service.close()

    def test_https_guard_messages_follow_language(self):
        client = app.test_client()
        r=client.get('/activate?lang=ja', base_url='http://localhost')
        self.assertIn('HTTPS 接続のみ許可されています', r.get_data(as_text=True))
        r=client.get('/activate?lang=en', base_url='http://localhost')
        self.assertIn('HTTPS access is required', r.get_data(as_text=True))

    def test_home_paginates_without_losing_totals(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'db');sql_initialize(path)
            info=dict(machineName='<script>',appId='Windows',skuId='SKU',licenseStatus='Activated',requestTime=1)
            for i in range(51):sql_update(path,dict(info,clientMachineId='client-%03d'%i))
            with patch.dict(os.environ,PYKMS_SQLITE_DB_PATH=path):
                c=app.test_client();body=c.get('/', base_url='https://localhost').get_data(as_text=True)
                self.assertEqual(body.count('class="clientMachineId"'),50)
                self.assertIn('&lt;script&gt;',body);self.assertIn('下一页',body)
                self.assertEqual(c.get('/?page=2', base_url='https://localhost').get_data(as_text=True).count('class="clientMachineId"'),1)
                self.assertEqual(c.get('/?page=-1', base_url='https://localhost').status_code,400)

    def test_readiness_is_open_and_cached(self):
        from hyx_kms_webui import _reset_ready_cache
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / 'db')
            sql_initialize(path)
            with patch.dict(os.environ, PYKMS_SQLITE_DB_PATH=path), \
                 patch('hyx_kms_webui.probe_kms') as probe:
                _reset_ready_cache()
                client = app.test_client()
                self.assertEqual(client.get('/readyz', base_url='https://localhost').status_code, 200)
                self.assertEqual(client.get('/readyz', base_url='https://localhost').status_code, 200)
                self.assertEqual(probe.call_count, 1)

    def test_connection_budget_and_split_bind_over_socket(self):
        import threading
        import time
        import hyx_kms_server as server
        import hyx_kms_rpc_bind as bind
        from hyx_kms_format import enco
        with patch.dict(os.environ,KMS_MAX_CONNECTIONS='1',KMS_MAX_CONNECTIONS_PER_SOURCE='1',KMS_CONNECTION_LIFETIME='2'), patch.dict(server.srv_config,{'timeoutsndrcv':1,'port':1688},clear=True), patch.object(bind,'pretty_printer'):
            listener=server.KeyServer([('127.0.0.1',0,5,False)],server.kmsServerHandler)
            address=listener.multisock.getsockname()
            worker=threading.Thread(target=listener.hyx_kms_serve,daemon=True);worker.start()
            first=socket.create_connection(address,timeout=2)
            try:
                # Wait for the first accepted thread to own the one slot.
                until=time.monotonic()+1
                while listener._connection_limiter._source_counts.get('127.0.0.1',0) != 1:
                    if time.monotonic()>until:self.fail('First connection was not accepted')
                    time.sleep(.01)
                from hyx_kms_health import probe_kms
                with self.assertRaises((OSError, EOFError, ValueError)):
                    probe_kms(*address)
                with socket.create_connection(address,timeout=2) as second:
                    self.assertEqual(second.recv(1),b'')
                first.close()
                until=time.monotonic()+2
                while listener._connection_limiter._source_counts.get('127.0.0.1',0):
                    if time.monotonic()>until:self.fail('Connection slot was not released')
                    time.sleep(.01)
                probe_kms(*address)
                until=time.monotonic()+2
                while listener._connection_limiter._source_counts.get('127.0.0.1',0):
                    if time.monotonic()>until:self.fail('Probe slot was not released')
                    time.sleep(.01)
                with socket.create_connection(address,timeout=2) as third:
                    wire=enco(str(bind.handler(None,{'call_id':1,'port':1688}).generateRequest()),'latin-1')
                    third.sendall(wire[:8]);time.sleep(.02);third.sendall(wire[8:])
                    self.assertEqual(recv_pdu(third)[2],12)
            finally:
                first.close();listener.shutdown();listener.w_service.sendall(b'stop');worker.join(3);listener.server_close()
            self.assertFalse(worker.is_alive())

    def test_response_integrity_and_mixed_protocol_concurrency(self):
        import hyx_kms_client as client
        from hyx_kms_request_v4 import kmsRequestV4
        from hyx_kms_request_v5 import kmsRequestV5
        from hyx_kms_request_v6 import kmsRequestV6
        from hyx_kms_format import enco
        config={'clientcount':None,'epid':None,'lcid':1033,'activation':120,'renewal':10080,'sqlite':False,'loglevel':'ERROR','hwid':bytes.fromhex('364F463A8863D35F')}
        prepared=[]
        with patch.dict(client.clt_config,clear=True):
            for mode in ('Windows7','Windows8','Windows11'):
                client.clt_config.clear();client.clt_config.update(mode=mode,cmid=None,machine='REGRESSION',call_id=1)
                client.client_update()
                request=client.createKmsRequest()
                prepared.append((enco(str(request),'latin-1'),dict(client.clt_config)))
            def roundtrip(item, corrupt=False):
                wire, settings=item;major=settings['KMSProtocolMajorVersion']
                cls={4:kmsRequestV4,5:kmsRequestV5,6:kmsRequestV6}[major]
                req=(cls.RequestV4(wire) if major==4 else cls.RequestV5(wire))
                response=enco(cls(wire,config).executeRequestLogic(),'latin-1')
                client.readKmsResponse(response,req,settings)
                if not corrupt:
                    return
                if major==4:
                    parsed=cls.ResponseV4(response)
                    parsed['hash']=bytes(16)
                    with self.assertRaises(ValueError):client.readKmsResponse(enco(str(parsed),'latin-1'),req,settings)
                else:
                    decoded=cls(None,settings).decryptResponse(cls.ResponseV5(response))
                    message=decoded['message'] if major==6 else decoded
                    message['hash']=bytes(32)
                    with patch.object(cls,'decryptResponse',return_value=decoded),self.assertRaises(ValueError):
                        client.readKmsResponse(response,req,settings)
            with patch('hyx_kms_request_v4.pretty_printer'),patch('hyx_kms_request_v5.pretty_printer'),patch('hyx_kms_base.pretty_printer'),patch('hyx_kms_request_v4.time.sleep'):
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(roundtrip,prepared*4))
                for item in prepared:
                    roundtrip(item, corrupt=True)

    def test_gui_output_is_queued_without_worker_tk_calls(self):
        from unittest.mock import Mock
        try:
            from hyx_kms_gui_misc import TextRedirect
        except ImportError:
            self.skipTest('Tkinter unavailable')
        widget=Mock()
        redirect=TextRedirect.Pretty(widget,widget,{})
        widget.reset_mock()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(redirect.write,'worker text').result()
        self.assertEqual(list(redirect._pending),['worker text'])
        self.assertFalse(widget.mock_calls)
        for _ in range(2000):redirect.write('bounded')
        self.assertEqual(len(redirect._pending),1000)

    def test_invalid_budgets_fail_before_listener_creation(self):
        import hyx_kms_server as server
        for name, values in [('KMS_MAX_CONNECTIONS', ['0','-1','4097','nan']), ('KMS_MAX_CONNECTIONS_PER_SOURCE', ['0','-1','nan']), ('KMS_CONNECTION_LIFETIME',['0','-1','nan','inf','301']), ('KMS_MAX_CLIENTS',['0','-1','nan'])]:
            for value in values:
                with self.subTest(name=name,value=value),patch.dict(os.environ,{name:value}),self.assertRaises(ValueError):
                    server.KeyServer([('127.0.0.1',0,5,False)],server.kmsServerHandler,bind_and_activate=False)

    def test_standard_aes_known_answer(self):
        from hyx_kms_aes import AES
        key=list(bytes.fromhex('000102030405060708090a0b0c0d0e0f'))
        plain=list(bytes.fromhex('00112233445566778899aabbccddeeff'))
        self.assertEqual(bytes(AES().encrypt(plain,key,16)).hex(),'69c4e0d86a7b0430d8cdb78070b4c55a')

    def test_unknown_protocol_has_a_binary_rpc_error_response(self):
        import hyx_kms_rpc_request as rpc
        from hyx_kms_dcerpc import MSRPCRequestHeader, MSRPCRespHeader
        from hyx_kms_format import enco
        request=MSRPCRequestHeader()
        request['representation']=16;request['flags']=3;request['call_id']=1
        request['pduData']=struct.pack('<IIHH',4,4,0,99)
        with patch.object(rpc,'pretty_printer'):
            response=rpc.handler(enco(str(request),'latin-1'),{}).populate()
        body=MSRPCRespHeader(enco(str(response),'latin-1'))['pduData']
        if isinstance(body,str):body=body.encode('latin-1')
        self.assertEqual(len(body),12)
        self.assertEqual(struct.unpack('<III',body),(0,0,0xC004F042))
