"""Offline release safety tests; no GitHub or PyPI mutations."""
import unittest
from unittest.mock import patch

import release


class ReleaseTests(unittest.TestCase):
    def test_version_bump_and_registry_alignment(self):
        registry = {'version': '1.2.0', 'packages': [{'version': '1.2.0'}]}
        self.assertTrue(release.version_changed('1.2.0', '1.1.0', registry))
        self.assertFalse(release.version_changed('1.2.0', '1.2.0', registry))
        with self.assertRaises(ValueError):
            release.version_changed('1.2.0', '1.3.0', registry)
        with self.assertRaises(ValueError):
            release.version_changed('1.3.0', '1.2.0', registry)
        for version in ['1.2.0rc1', 'v1.2.0', '01.2.0', '1.2']:
            with self.assertRaises(ValueError):
                release.version_number(version)

    def test_ci_must_match_commit_main_and_trusted_event(self):
        run = {'head_sha': 'a' * 40, 'head_branch': 'main', 'event': 'push',
               'status': 'completed', 'conclusion': 'success'}
        self.assertTrue(release.successful_ci([run], 'a' * 40))
        for changes in [{'head_sha': 'b' * 40}, {'head_branch': 'feature'},
                        {'event': 'pull_request'}, {'status': 'in_progress'}, {'conclusion': 'failure'}]:
            self.assertFalse(release.successful_ci([run | changes], 'a' * 40))

    def test_partial_upload_can_resume_but_conflicting_or_yanked_files_cannot(self):
        local = {'package.whl': 'abc', 'package.tar.gz': 'def'}
        wheel = {'filename': 'package.whl', 'digests': {'sha256': 'abc'}}
        sdist = {'filename': 'package.tar.gz', 'digests': {'sha256': 'def'}}
        self.assertTrue(release.compare_files(local, [], False))
        self.assertTrue(release.compare_files(local, [wheel], False))
        self.assertFalse(release.compare_files(local, [wheel], True))
        self.assertTrue(release.compare_files(local, [wheel, sdist], True))
        for remote in [[wheel | {'digests': {'sha256': 'different'}}],
                       [wheel | {'filename': 'unexpected.whl'}], [wheel | {'yanked': True}]]:
            with self.assertRaises(ValueError):
                release.compare_files(local, remote, False)

    @patch.dict('os.environ', {'GITHUB_REPOSITORY': 'owner/repo'})
    @patch('release.subprocess.run')
    @patch('release.verify', side_effect=ValueError('PyPI incomplete'))
    def test_no_github_release_before_pypi_verification(self, verify, run):
        with self.assertRaises(ValueError):
            release.release('1.2.0', 'a' * 40)
        run.assert_not_called()

    @patch('release.github')
    def test_existing_tag_cannot_move(self, github):
        github.return_value = {'object': {'type': 'commit', 'sha': 'b' * 40}}
        with self.assertRaises(ValueError):
            release.check_tag('owner/repo', 'v1.2.0', 'a' * 40)
        github.side_effect = [
            {'object': {'type': 'tag', 'sha': 'c' * 40}},
            {'object': {'type': 'commit', 'sha': 'a' * 40}},
        ]
        release.check_tag('owner/repo', 'v1.2.0', 'a' * 40)

    @patch.dict('os.environ', {'GITHUB_REPOSITORY': 'owner/repo'})
    @patch('release.subprocess.run')
    @patch('release.github', return_value={'draft': False, 'prerelease': False})
    @patch('release.check_tag')
    @patch('release.verify')
    def test_completed_release_rerun_is_noop(self, verify, check_tag, github, run):
        release.release('1.2.0', 'a' * 40)
        verify.assert_called_once_with('1.2.0', complete=True)
        check_tag.assert_called_once_with('owner/repo', 'v1.2.0', 'a' * 40)
        run.assert_not_called()

    @patch.dict('os.environ', {'GITHUB_REPOSITORY': 'owner/repo'})
    @patch('release.subprocess.run')
    @patch('release.github', return_value=None)
    @patch('release.check_tag')
    @patch('release.verify')
    def test_release_targets_verified_commit(self, verify, check_tag, github, run):
        release.release('1.2.0', 'a' * 40)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['gh', 'release', 'create', 'v1.2.0'])
        self.assertEqual(args[args.index('--target') + 1], 'a' * 40)


if __name__ == '__main__':
    unittest.main()
