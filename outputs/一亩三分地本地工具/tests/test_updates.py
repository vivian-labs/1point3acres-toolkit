import json
import os
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from updates import Manager, Release


class UpdateTests(unittest.TestCase):
    def make(self, directory):
        return Manager(Path(directory) / 'base', Path(directory) / 'cache')

    def test_approved_new_version_is_prepared_before_atomic_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            candidate = Release(manager.cache / 'versions' / ('b' * 40) / 'outputs' / '一亩三分地本地工具',
                                Path(os.sys.executable), 'b' * 40)
            with patch.object(manager, '_fetch', return_value=candidate.revision), \
                    patch.object(manager, '_approved', return_value=True), \
                    patch.object(manager, '_prepare', return_value=candidate) as prepare:
                self.assertEqual(manager.resolve(), candidate)
                prepare.assert_called_once_with(candidate.revision)
            self.assertEqual(json.loads((manager.cache / 'active.json').read_text())['revision'], candidate.revision)

    def test_pending_ci_or_failed_preparation_keeps_last_good_release(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            before = manager.cached()
            with patch.object(manager, '_fetch', return_value='b' * 40), \
                    patch.object(manager, '_approved', return_value=False), \
                    patch.object(manager, '_prepare') as prepare:
                self.assertEqual(manager.resolve(), before)
                prepare.assert_not_called()
                self.assertFalse((manager.cache / 'active.json').exists())
            with patch.object(manager, '_fetch', return_value='b' * 40), \
                    patch.object(manager, '_approved', return_value=True), \
                    patch.object(manager, '_prepare', side_effect=RuntimeError('private-sentinel')):
                self.assertEqual(manager.resolve(), before)
                self.assertNotIn('private-sentinel', (manager.cache / 'status.json').read_text())
                self.assertFalse((manager.cache / 'active.json').exists())

    def test_offline_never_fetches_and_concurrent_preparation_returns_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            with patch.object(manager, '_fetch') as fetch:
                self.assertEqual(manager.resolve(offline=True), manager.cached())
                with manager.lock():
                    self.assertEqual(manager.resolve(), manager.cached())
                fetch.assert_not_called()

    def test_ci_evidence_requires_exact_main_commit_and_successful_push_workflow(self):
        manager = Manager()
        revision = 'b' * 40
        valid = {'head_sha': revision, 'head_branch': 'main', 'event': 'push',
                 'path': '.github/workflows/consistency.yml', 'status': 'completed', 'conclusion': 'success'}
        with patch.object(manager, '_runs', return_value=[valid]):
            self.assertTrue(manager._approved(revision))
        for change in ({'head_sha': 'c' * 40}, {'head_branch': 'other'}, {'event': 'pull_request'},
                       {'conclusion': 'failure'}, {'status': 'in_progress'}, {'path': 'untrusted.yml'}):
            with patch.object(manager, '_runs', return_value=[{**valid, **change}]):
                self.assertFalse(manager._approved(revision))

    def test_worker_environment_preserves_mutable_workspace_and_blocks_recursive_updates(self):
        manager = Manager()
        env = manager.worker_env()
        self.assertEqual(env['ONEPOINT3ACRES_UPDATE_WORKER'], '1')
        from settings import RUNTIME_WORKSPACE
        self.assertEqual(Path(env['ONEPOINT3ACRES_WORKSPACE']), RUNTIME_WORKSPACE)

    def test_changed_base_dependencies_are_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'requirements.txt').write_text('example==1.0\n')
            with patch('updates.importlib.metadata.version', return_value='2.0'):
                self.assertFalse(self.make(directory)._requirements_match(path))

    def test_new_code_workspace_preserves_existing_state_profile_and_exports(self):
        import settings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / 'versions' / 'v2' / 'outputs' / 'tool'
            code.mkdir(parents=True)
            (code / 'settings.py').write_text((settings.ROOT / 'settings.py').read_text(encoding='utf-8'), encoding='utf-8')
            canonical = root / 'canonical'
            env = {**os.environ, 'ONEPOINT3ACRES_WORKSPACE': str(canonical)}
            env.pop('ONEPOINT3ACRES_HOME', None)
            result = subprocess.run([os.sys.executable, '-X', 'utf8', '-c',
                'import settings,json; print(json.dumps({k:str(getattr(settings,k)) for k in ("STATE","PROFILE","WORKSPACE","EXPORT_DIRECTORY")}))'],
                cwd=code, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            value = json.loads(result.stdout)
            self.assertEqual(Path(value['STATE']), canonical / 'work' / 'local-toolkit-state')
            self.assertEqual(Path(value['PROFILE']), canonical / 'work' / 'account-browser' / 'chrome-profile')
            self.assertEqual(Path(value['EXPORT_DIRECTORY']), canonical / 'outputs' / 'Stripe面经资料')
            self.assertEqual(Path(value['WORKSPACE']), code.parent.parent)

    def test_failed_candidate_validation_cannot_rewrite_live_client_config(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            revision = 'b' * 40
            package = manager.cache / 'versions' / revision / 'outputs' / '一亩三分地本地工具'
            package.mkdir(parents=True)
            (package / 'requirements.txt').write_text('')
            live = Path(directory) / 'live'
            live.mkdir()
            config = live / 'mcp.config.json'
            config.write_text('original-bootstrap')
            def child(argv, **kwargs):
                if any(str(item).endswith('check.py') for item in argv):
                    home = Path(kwargs['env']['ONEPOINT3ACRES_HOME'])
                    self.assertNotEqual(home, live)
                    home.mkdir(parents=True, exist_ok=True)
                    (home / 'mcp.config.json').write_text('candidate')
                failed = any(str(item).endswith('cli.py') for item in argv)
                return CompletedProcess(argv, 1 if failed else 0, '', '')
            with patch.dict(os.environ, {'ONEPOINT3ACRES_HOME': str(live)}), patch('updates.command', side_effect=child):
                with self.assertRaisesRegex(RuntimeError, 'validation_failed'):
                    manager._prepare(revision)
            self.assertEqual(config.read_text(), 'original-bootstrap')
            self.assertFalse((manager.cache / 'active.json').exists())

    def test_cli_launch_preserves_argument_boundaries_and_exit_code(self):
        import launcher
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            release = manager.base()
            arguments = ['daily', '--question', 'literal ; & spaces', '--answer', 'another literal']
            with patch('launcher.Manager', return_value=manager), \
                    patch.object(manager, 'resolve', return_value=release) as resolve, \
                    patch('launcher.command', return_value=CompletedProcess([], 7, '', '')) as execute, \
                    patch.dict(os.environ, {'ONEPOINT3ACRES_AUTO_UPDATE': '1'}):
                self.assertEqual(launcher.main(['cli', *arguments]), 7)
                resolve.assert_called_once_with(offline=False)
                self.assertEqual(execute.call_args.args[0][-len(arguments):], arguments)
                self.assertFalse(execute.call_args.kwargs['capture'])
                self.assertEqual(execute.call_args.kwargs['env']['ONEPOINT3ACRES_UPDATE_WORKER'], '1')

    def test_installed_bootstrap_initializes_registration_without_rewriting_existing_config(self):
        import launcher
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make(directory)
            config = Path(directory) / 'data' / 'mcp.config.json'
            with patch('launcher.Manager', return_value=manager), \
                    patch.object(manager, 'resolve', return_value=manager.base()), \
                    patch('launcher.command', return_value=CompletedProcess([], 0)), \
                    patch('launcher.INSTALLED', True), patch('launcher.CONFIG_FILE', config), \
                    patch('launcher.mcp_config', return_value={'bootstrap': True}):
                self.assertEqual(launcher.main(['cli', 'info']), 0)
                self.assertEqual(json.loads(config.read_text()), {'bootstrap': True})
                config.write_text('existing-user-config')
                self.assertEqual(launcher.main(['cli', 'info']), 0)
                self.assertEqual(config.read_text(), 'existing-user-config')


if __name__ == '__main__':
    unittest.main()
