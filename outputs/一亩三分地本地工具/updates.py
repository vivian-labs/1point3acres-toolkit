"""Prepare CI-approved immutable releases. This module never calls the forum or imports business code."""
import contextlib
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from settings import (ROOT, RUNTIME_WORKSPACE, STATE, DATA_HOME, DATA_HOME_ENV, WINDOWS,
                      UPDATE_REPOSITORY, UPDATE_GIT_URLS, UPDATE_CACHE, UPDATE_FETCH_TIMEOUT,
                      UPDATE_PREPARE_TIMEOUT, SOURCE_PACKAGE_DIRECTORY)


@dataclass(frozen=True)
class Release:
    package: Path
    python: Path
    revision: str | None


def command(argv, capture=True, **kwargs):
    if capture:
        # Update commands never need input and must not consume the client's MCP stream.
        kwargs.setdefault('stdin', subprocess.DEVNULL)
    if not capture:
        # Explicit handles preserve Windows pipelines with CREATE_NO_WINDOW, including stdin for credentials.
        # pythonw has no console streams, so its scheduled child uses null handles instead of opening a window.
        for name in ('stdin', 'stdout', 'stderr'):
            stream = getattr(sys, name)
            kwargs.setdefault(name, stream if stream is not None else subprocess.DEVNULL)
    return subprocess.run([str(a) for a in argv], capture_output=capture, text=True, encoding='utf-8',
                          errors='replace', creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0,
                          **kwargs)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def update_info():
    """Sanitized cache diagnostics only. Reading them never performs an update."""
    try:
        data = json.loads((UPDATE_CACHE / 'status.json').read_text(encoding='utf-8'))
        return {key: data.get(key) for key in ('state', 'checked_at', 'active_revision', 'available_revision', 'error')}
    except (OSError, ValueError, AttributeError):
        return {'state': 'not_checked', 'error': None}


class Manager:
    def __init__(self, root=ROOT, cache=UPDATE_CACHE):
        self.root, self.cache = Path(root), Path(cache)
        executable = Path(sys.executable)
        self.python = executable.with_name('python.exe') if executable.name.lower() == 'pythonw.exe' else executable
        self.mirror = self.cache / 'repository.git'

    def worker_env(self):
        env = {**os.environ, 'PYTHONUTF8': '1', 'ONEPOINT3ACRES_UPDATE_WORKER': '1',
               'ONEPOINT3ACRES_WORKSPACE': str(RUNTIME_WORKSPACE), 'ONEPOINT3ACRES_UPDATE_CACHE': str(self.cache)}
        if DATA_HOME:
            env[DATA_HOME_ENV] = str(DATA_HOME)
        return env

    def base(self):
        try:
            result = command(['git', '-C', self.root, 'rev-parse', 'HEAD'], timeout=3)
            revision = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            revision = None
        return Release(self.root, self.python, revision)

    def cached(self):
        try:
            data = json.loads((self.cache / 'active.json').read_text(encoding='utf-8'))
            revision, environment = data['revision'], data['environment']
            if not re.fullmatch('[a-f0-9]{40}', revision) or not re.fullmatch('base|[a-f0-9]{64}', environment):
                raise ValueError()
            package = self.cache / 'versions' / revision / 'outputs' / SOURCE_PACKAGE_DIRECTORY
            python = self.python if environment == 'base' else self.cache / 'environments' / environment / (
                'Scripts/python.exe' if WINDOWS else 'bin/python')
            if not (package / '.update-ready.json').is_file() or not python.is_file():
                raise ValueError()
            ready = json.loads((package / '.update-ready.json').read_text(encoding='utf-8'))
            if ready != data:
                raise ValueError()
            if environment == 'base' and not self._requirements_match(package):
                raise ValueError()
            actual = command(['git', '-C', package, 'rev-parse', 'HEAD'], timeout=3)
            dirty = command(['git', '-C', package, 'status', '--porcelain', '--untracked-files=no'], timeout=3)
            if actual.returncode or actual.stdout.strip() != revision or dirty.returncode or dirty.stdout.strip():
                raise ValueError()
            return Release(package, python, revision)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return self.base()

    @contextlib.contextmanager
    def lock(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        with (self.cache / 'update.lock').open('a+b') as stream:
            stream.seek(0)
            if WINDOWS:
                import msvcrt
                if not stream.read(1):
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if WINDOWS:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _record(self, state, active, available=None, error=None):
        atomic_json(self.cache / 'status.json', {'state': state, 'checked_at': datetime.now(timezone.utc).isoformat(),
                    'active_revision': active.revision, 'available_revision': available, 'error': error})

    def resolve(self, offline=False):
        active = self.cached()
        if offline:
            return active
        try:
            with self.lock():
                active = self.cached()
                revision = self._fetch()
                if revision == active.revision:
                    self._record('current', active, revision)
                    return active
                if not self._approved(revision):
                    self._record('waiting_for_ci', active, revision)
                    return active
                ready = self._prepare(revision)
                environment = 'base' if ready.python == self.python else ready.python.parent.parent.name
                pointer = {'revision': ready.revision, 'environment': environment}
                atomic_json(ready.package / '.update-ready.json', pointer)
                atomic_json(self.cache / 'active.json', pointer)
                self._record('updated', ready, revision)
                return ready
        except BlockingIOError:
            return self.cached()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
            # Never expose subprocess output, URLs with credentials, usernames, or source exception text.
            try:
                self._record('fallback', active, error='update_unavailable')
            except OSError:
                pass
            return active

    def _fetch(self):
        if not self.mirror.exists():
            result = command(['git', 'init', '--bare', self.mirror], timeout=10)
            if result.returncode:
                raise RuntimeError('update_repository_unavailable')
        env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0',
               'GIT_SSH_COMMAND': 'ssh -p 443 -o HostKeyAlias=github.com -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes'}
        for url in UPDATE_GIT_URLS:
            try:
                result = command(['git', '--git-dir', self.mirror, 'fetch', '--no-tags', '--depth=1', url,
                                  '+refs/heads/main:refs/remotes/upstream/main'], env=env, timeout=UPDATE_FETCH_TIMEOUT)
                if result.returncode == 0:
                    break
            except subprocess.TimeoutExpired:
                continue
        else:
            raise RuntimeError('update_fetch_failed')
        result = command(['git', '--git-dir', self.mirror, 'rev-parse', 'refs/remotes/upstream/main'], timeout=3)
        revision = result.stdout.strip()
        if result.returncode or not re.fullmatch('[a-f0-9]{40}', revision):
            raise RuntimeError('update_revision_invalid')
        return revision

    def _runs(self, revision):
        request = Request('https://api.github.com/repos/' + UPDATE_REPOSITORY + '/actions/runs?head_sha=' + revision +
                          '&event=push&branch=main&per_page=30', headers={'Accept': 'application/vnd.github+json',
                          'User-Agent': '1point3acres-toolkit-updater'})
        with urlopen(request, timeout=UPDATE_FETCH_TIMEOUT) as response:
            return json.loads(response.read(2_000_000))['workflow_runs']

    def _approved(self, revision):
        for run in self._runs(revision):
            # This is the GitHub workflow lifecycle, separate from toolkit business statuses.
            lifecycle = run.get('status')
            if (run.get('head_sha') == revision and run.get('head_branch') == 'main'
                    and run.get('event') == 'push' and run.get('path') == '.github/workflows/consistency.yml'
                    and lifecycle == 'completed' and run.get('conclusion') == 'success'):
                return True
        return False

    def _requirements_match(self, package):
        requirements = (package / 'requirements.txt').read_text(encoding='utf-8')
        expected = dict(line.split('==', 1) for line in requirements.splitlines() if line.strip() and not line.startswith('#'))
        try:
            return all(importlib.metadata.version(name) == version for name, version in expected.items())
        except importlib.metadata.PackageNotFoundError:
            return False

    def _prepare(self, revision):
        workspace = self.cache / 'versions' / revision
        package = workspace / 'outputs' / SOURCE_PACKAGE_DIRECTORY
        if not workspace.exists():
            workspace.parent.mkdir(parents=True, exist_ok=True)
            result = command(['git', '--git-dir', self.mirror, 'worktree', 'add', '--detach', workspace, revision], timeout=30)
            if result.returncode:
                raise RuntimeError('update_checkout_failed')
        requirements = (package / 'requirements.txt').read_text(encoding='utf-8')
        reusable = self._requirements_match(package)
        python = self.python
        if not reusable:
            key = hashlib.sha256((requirements + sys.version.split()[0]).encode()).hexdigest()
            environment = self.cache / 'environments' / key
            python = environment / ('Scripts/python.exe' if WINDOWS else 'bin/python')
            if not python.exists():
                result = command([self.python, '-m', 'venv', environment], timeout=60)
                if result.returncode:
                    raise RuntimeError('update_environment_failed')
            result = command([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', package / 'requirements.txt'],
                             timeout=UPDATE_PREPARE_TIMEOUT)
            if result.returncode:
                raise RuntimeError('update_dependencies_failed')
        # Validation has no account/profile/export data and cannot rewrite live client registration.
        validation_env = self.worker_env()
        validation_env[DATA_HOME_ENV] = str(self.cache / 'validation' / revision)
        validation_env['ONEPOINT3ACRES_WORKSPACE'] = str(workspace)
        for argv in ([python, '-m', 'pip', 'check'],
                     [python, '-X', 'utf8', package / 'check.py', '--sync', '--stage', 'static'],
                     [python, '-X', 'utf8', package / 'cli.py', 'info']):
            result = command(argv, cwd=package, env=validation_env, timeout=60)
            if result.returncode:
                raise RuntimeError('update_validation_failed')
        return Release(package, python, revision)
