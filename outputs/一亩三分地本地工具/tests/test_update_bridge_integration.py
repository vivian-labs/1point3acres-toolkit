"""Exercise the real stable stdio connection with synthetic versioned workers, never the forum."""
import json
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from settings import ROOT


WORKER = '''import json,sys,threading,time,os
from pathlib import Path
version = Path(__file__).parent.name
lock = threading.Lock()
def emit(data):
    with lock:
        print(json.dumps(data), flush=True)
def handle(m):
    if m.get('method') == 'initialize':
        emit({'jsonrpc':'2.0','id':m['id'],'result':{'protocolVersion':'incompatible' if version=='bad' else 'test', 'capabilities':{'tools':{}}}})
    elif m.get('method') == 'tools/list':
        emit({'jsonrpc':'2.0','id':m['id'],'result':{'tools':[{'name':version}]}})
    elif m.get('method') == 'tools/call':
        p=m['params']
        if p['name']=='crash':
            os._exit(7)
        if p['name']=='slow':
            Path(__file__).parent.parent.joinpath('started').write_text('yes')
            time.sleep(.5)
        with lock:
            with Path(__file__).parent.parent.joinpath('calls').open('a') as f:
                f.write(str(m['id'])+'\\n')
        emit({'jsonrpc':'2.0','id':m['id'],'result':{'version':version}})
for line in sys.stdin:
    threading.Thread(target=handle,args=(json.loads(line),),daemon=True).start()
'''

HOST = '''import asyncio, json, sys
from pathlib import Path
from updates import Release
from mcp_bridge import Bridge
class Manager:
    def __init__(self): self.root=Path(sys.argv[1])
    def cached(self): return Release(self.root/'v1',Path(sys.executable),'v1')
    def resolve(self):
        v=self.root.joinpath('selected').read_text()
        return Release(self.root/v,Path(sys.executable),v)
    def worker_env(self): return {'PYTHONUTF8':'1'}
    def _record(self,*args): pass
asyncio.run(Bridge(Manager()).run())
'''


class BridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        for version in ('v1', 'v2', 'bad'):
            (self.root / version).mkdir()
            (self.root / version / 'mcp_server.py').write_text(WORKER, encoding='utf-8')
        (self.root / 'selected').write_text('v1')
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', HOST, str(self.root)],
                                        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding='utf-8')
        self.output = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.output.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.send(1, 'initialize', {'protocolVersion': 'test', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
        self.receive(1)
        self.send(None, 'notifications/initialized')
        self.send(2, 'tools/call', {'name': 'runtime_info'})
        self.assertEqual(self.receive(2)['result']['version'], 'v1')

    def tearDown(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()
        self.directory.cleanup()

    def send(self, identifier, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if identifier is not None:
            message['id'] = identifier
        if params is not None:
            message['params'] = params
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def receive(self, identifier):
        while True:
            message = self.output.get(timeout=10)
            if message.get('id') == identifier:
                return message

    def test_same_connection_switches_worker_and_delivers_new_schema_without_replay(self):
        original = self.process.pid
        (self.root / 'selected').write_text('v2')
        self.send(3, 'tools/call', {'name': 'echo'})
        self.assertEqual(self.receive(3)['result']['version'], 'v2')
        self.send(4, 'tools/list')
        self.assertEqual(self.receive(4)['result']['tools'][0]['name'], 'v2')
        self.assertEqual(self.process.pid, original)
        self.assertEqual((self.root / 'calls').read_text().splitlines().count('3'), 1)

    def test_active_call_finishes_and_held_cancelled_call_is_never_executed(self):
        self.send(3, 'tools/call', {'name': 'slow'})
        import time
        deadline = time.monotonic() + 5
        while not (self.root / 'started').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((self.root / 'started').exists())
        (self.root / 'selected').write_text('v2')
        self.send(4, 'tools/call', {'name': 'echo'})
        self.send(None, 'notifications/cancelled', {'requestId': 4})
        self.assertIn('error', self.receive(4))
        self.assertEqual(self.receive(3)['result']['version'], 'v1')
        self.send(5, 'tools/call', {'name': 'echo'})
        self.assertEqual(self.receive(5)['result']['version'], 'v2')
        calls = (self.root / 'calls').read_text().splitlines()
        self.assertNotIn('4', calls)
        self.assertEqual(calls.count('3'), 1)

    def test_failed_initialization_keeps_original_worker_and_connection(self):
        (self.root / 'selected').write_text('bad')
        self.send(3, 'tools/call', {'name': 'echo'})
        self.assertEqual(self.receive(3)['result']['version'], 'v1')
        self.assertEqual((self.root / 'calls').read_text().splitlines().count('3'), 1)

    def test_cancelled_sent_call_settles_before_switch_and_does_not_block_future_calls(self):
        self.send(3, 'tools/call', {'name': 'slow'})
        import time
        deadline = time.monotonic() + 5
        while not (self.root / 'started').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((self.root / 'started').exists())
        self.send(None, 'notifications/cancelled', {'requestId': 3})
        (self.root / 'selected').write_text('v2')
        self.send(4, 'tools/call', {'name': 'echo'})
        self.assertEqual(self.receive(4)['result']['version'], 'v2')
        calls = (self.root / 'calls').read_text().splitlines()
        self.assertEqual(calls.count('3'), 1)
        self.assertEqual(calls.count('4'), 1)

    def test_worker_crash_reports_failure_and_never_replays_request(self):
        self.send(3, 'tools/call', {'name': 'crash'})
        result = self.receive(3)
        self.assertIn('not replayed', result['error']['message'])
        self.process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
