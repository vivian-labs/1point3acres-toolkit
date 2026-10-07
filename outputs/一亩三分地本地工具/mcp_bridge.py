"""Keep the client stdio session alive while replacing idle, immutable MCP workers."""
import asyncio
import json
import os
import sys
import threading
from contextlib import suppress

from settings import WINDOWS, UPDATE_POLL_SECONDS, UPDATE_HANDSHAKE_TIMEOUT, UPDATE_CONTROL_TOOLS

META_PREFIX = 'io.modelcontextprotocol/'
META_PROTOCOL = META_PREFIX + 'protocolVersion'


class Bridge:
    def __init__(self, manager, offline=False):
        self.manager, self.offline = manager, offline
        self.queue = asyncio.Queue()
        self.worker = None
        self.reader = None
        self.release = manager.cached()
        self.pending, self.server_pending, self.held = set(), set(), {}
        self.sent_tools, self.cancelled = set(), set()
        self.initialize = None
        self.protocol = None
        self.capabilities = None
        self.discover = None
        self.modern_protocol = None
        self.modern_capabilities = None
        self.catalog = set()
        self.update = None
        self.target = None

    async def start(self, release):
        import subprocess
        return await asyncio.create_subprocess_exec(str(release.python), '-X', 'utf8',
                    str(release.package / 'mcp_server.py'), cwd=release.package, env=self.manager.worker_env(),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=32 * 1024 * 1024,
                    creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0)

    async def send(self, message, worker=None):
        worker = worker or self.worker
        worker.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        await worker.stdin.drain()

    async def emit(self, message):
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    async def read_worker(self, worker):
        try:
            while line := await worker.stdout.readline():
                await self.queue.put(('worker', worker, json.loads(line)))
        except (ValueError, OSError):
            pass
        finally:
            await self.queue.put(('dead', worker, None))

    def read_client(self, loop):
        try:
            # A blocked BufferedReader daemon can abort Python during worker-crash shutdown.
            buffer = b''
            while chunk := os.read(sys.stdin.fileno(), 65536):
                lines = (buffer + chunk).split(b'\n')
                buffer = lines.pop()
                for line in lines:
                    loop.call_soon_threadsafe(self.queue.put_nowait, ('client', None, json.loads(line)))
                if len(buffer) > 32 * 1024 * 1024:
                    raise ValueError('frame_too_large')
        except (ValueError, OSError, RuntimeError):
            pass
        finally:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self.queue.put_nowait, ('eof', None, None))

    def begin_update(self):
        if not self.offline and self.update is None:
            self.update = asyncio.create_task(asyncio.to_thread(self.manager.resolve))

    async def close(self, worker):
        if worker is None:
            return
        worker.stdin.close()
        try:
            await asyncio.wait_for(worker.wait(), 5)
        except asyncio.TimeoutError:
            worker.kill()
            await worker.wait()

    async def switch(self, target):
        candidate = None
        try:
            candidate = await self.start(target)
            async def probe(request, identifier):
                message = {**request, 'id': identifier}
                await self.send(message, candidate)
                line = await asyncio.wait_for(candidate.stdout.readline(), UPDATE_HANDSHAKE_TIMEOUT)
                answer = json.loads(line)
                if answer.get('id') != identifier or 'error' in answer or not isinstance(answer.get('result'), dict):
                    raise ValueError('worker_initialization_failed')
                return answer['result']
            if self.initialize:
                result = await probe(self.initialize, '__toolkit_initialize__')
                if result.get('protocolVersion') != self.protocol or result.get('capabilities', {}) != self.capabilities:
                    raise ValueError('worker_initialization_failed')
                await self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, candidate)
            if self.discover:
                result = await probe(self.discover, '__toolkit_discover__')
                capabilities = result.get('capabilities', {})
                if (self.modern_protocol not in result.get('supportedVersions', [])
                        or (self.modern_capabilities is not None and capabilities != self.modern_capabilities)
                        or 'tools' not in capabilities):
                    raise ValueError('worker_initialization_failed')
                self.modern_capabilities = json.loads(json.dumps(capabilities))
        except (OSError, ValueError, asyncio.TimeoutError, BrokenPipeError):
            await self.close(candidate)
            with suppress(OSError):
                self.manager._record('mcp_fallback', self.release, target.revision, 'worker_initialization_failed')
            return False
        previous, previous_reader = self.worker, self.reader
        self.worker, self.release = candidate, target
        self.reader = asyncio.create_task(self.read_worker(candidate))
        await self.close(previous)
        previous_reader.cancel()
        if self.initialize:
            await self.emit({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})
        return True

    async def client(self, message):
        if not isinstance(message, dict) or type(message.get('id')) not in (str, int, type(None)):
            await self.emit({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}})
            return
        method, identifier = message.get('method'), message.get('id')
        params = message.get('params', {})
        meta = params.get('_meta', {}) if isinstance(params, dict) else {}
        modern = meta.get(META_PROTOCOL) if isinstance(meta, dict) else None
        if isinstance(modern, str):
            if method == 'server/discover' or self.discover is None or modern != self.modern_protocol:
                self.discover = message if method == 'server/discover' else {
                    'jsonrpc': '2.0', 'method': 'server/discover', 'params': {'_meta': {
                        key: value for key, value in meta.items() if key in
                        (META_PROTOCOL, META_PREFIX + 'clientInfo', META_PREFIX + 'clientCapabilities')}}}
                self.modern_capabilities = None
            self.modern_protocol = modern
            if method == 'tools/list' and identifier is not None:
                self.catalog.add(identifier)
        if method == 'initialize':
            self.initialize = message
        if method == 'notifications/cancelled':
            cancelled = message.get('params', {}).get('requestId')
            if cancelled in self.held:
                self.held.pop(cancelled)
                await self.emit({'jsonrpc': '2.0', 'id': cancelled, 'error': {'code': -32800, 'message': 'Request cancelled'}})
                return
            if cancelled in self.sent_tools:
                # The SDK suppresses responses for cancelled requests. Keep the internal request alive
                # until actual settlement; an active submission must not be killed or mistaken for idle.
                self.cancelled.add(cancelled)
                return
            self.pending.discard(cancelled)
        if method == 'tools/call' and identifier is not None:
            name = message.get('params', {}).get('name')
            if name not in UPDATE_CONTROL_TOOLS:
                self.begin_update()
                if self.update is not None or self.target is not None:
                    self.held[identifier] = message
                    return
        if identifier is not None:
            if method:
                self.pending.add(identifier)
            else:
                self.server_pending.discard(identifier)
        if method == 'tools/call' and identifier is not None:
            self.sent_tools.add(identifier)
        await self.send(message)

    async def tick(self):
        if self.update is not None and self.update.done():
            self.target = self.update.result()
            self.update = None
        if self.target is not None and not self.pending and not self.server_pending:
            if self.target != self.release and ((self.initialize and self.protocol) or (self.discover and self.modern_protocol)):
                await self.switch(self.target)
            self.target = None
        if self.update is None and self.target is None and self.queue.empty():
            # Drain queued cancellations before delivering held business calls. Never replay a sent call.
            held, self.held = self.held, {}
            for identifier, message in held.items():
                self.pending.add(identifier)
                self.sent_tools.add(identifier)
                await self.send(message)

    async def run(self):
        # MCP stdio is UTF-8 regardless of the Windows console's legacy encoding.
        sys.stdout.reconfigure(encoding='utf-8')
        self.worker = await self.start(self.release)
        self.reader = asyncio.create_task(self.read_worker(self.worker))
        threading.Thread(target=self.read_client, args=(asyncio.get_running_loop(),), daemon=True).start()
        self.begin_update()
        last_poll = asyncio.get_running_loop().time()
        try:
            while True:
                try:
                    kind, worker, message = await asyncio.wait_for(self.queue.get(), .1)
                except asyncio.TimeoutError:
                    kind, worker, message = None, None, None
                if kind == 'eof':
                    return 0
                if kind == 'dead' and worker is self.worker:
                    for identifier in (self.pending | self.held.keys()) - self.cancelled:
                        await self.emit({'jsonrpc': '2.0', 'id': identifier, 'error': {
                            'code': -32000, 'message': 'MCP worker disconnected; request not replayed'}})
                    return 1
                if kind == 'client':
                    await self.client(message)
                if kind == 'worker' and worker is self.worker:
                    identifier = message.get('id')
                    if 'method' in message and identifier is not None:
                        self.server_pending.add(identifier)
                    elif identifier is not None:
                        self.pending.discard(identifier)
                        self.sent_tools.discard(identifier)
                    if self.initialize and identifier == self.initialize.get('id') and 'result' in message:
                        self.protocol = message['result'].get('protocolVersion')
                        self.capabilities = json.loads(json.dumps(message['result'].get('capabilities', {})))
                        message['result'].setdefault('capabilities', {}).setdefault('tools', {})['listChanged'] = True
                    if self.discover and identifier is not None and identifier == self.discover.get('id') and 'result' in message:
                        self.modern_capabilities = json.loads(json.dumps(message['result'].get('capabilities', {})))
                        message['result']['ttlMs'] = 0
                    if identifier in self.catalog:
                        self.catalog.discard(identifier)
                        if 'result' in message:
                            message['result']['ttlMs'] = 0
                    if identifier in self.cancelled and 'method' not in message:
                        self.cancelled.discard(identifier)
                    else:
                        await self.emit(message)
                await self.tick()
                now = asyncio.get_running_loop().time()
                if now - last_poll >= UPDATE_POLL_SECONDS and not self.pending and not self.server_pending:
                    self.begin_update()
                    last_poll = now
        finally:
            self.reader.cancel()
            await self.close(self.worker)
            if self.update:
                with suppress(Exception):
                    await self.update
