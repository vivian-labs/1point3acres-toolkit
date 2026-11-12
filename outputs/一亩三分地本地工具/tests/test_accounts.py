import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import accounts
import daily
from contracts import daily_history_record, day_complete, summarize_daily_history
from rules import daily_retry_due
from settings import DATA_HOME_ENV, ROOT
from tests.test_access_recovery import SubmissionBrowser


class AccountTests(unittest.TestCase):
    def setUp(self):
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = home / 'state'
        self.state.mkdir()
        self.primary = self.state / 'account.json'
        self.enterContext(patch.multiple(accounts, ACCOUNT_FILE=self.primary, STATE=self.state))
        self.enterContext(patch.dict(os.environ, {DATA_HOME_ENV: str(home)}))

    def test_registration_and_primary_reuse(self):
        self.assertEqual(accounts.checkin_all()['error'], 'account_not_configured')
        self.primary.write_text(json.dumps({'uid': 51, 'username': 'original'}))
        accounts.add_account(51, 'original')
        accounts.add_account(52, 'additional')
        home = self.state / 'accounts' / '52'
        self.assertEqual(accounts.account_homes(), {51: None, 52: home})
        config = home / 'state' / 'account.json'
        data = json.loads(config.read_text())
        config.write_text(json.dumps({**data, 'checkin_mood_random': True}))
        accounts.add_account(52, 'additional')
        with self.assertRaisesRegex(ValueError, 'account_profile_mismatch'):
            accounts.add_account(52, 'other')
        self.assertTrue(json.loads(config.read_text())['checkin_mood_random'])
        self.assertEqual(accounts.login_account(53, 'wechat')['error'], 'account_not_configured')

    def test_parallel_workers_and_partial_results(self):
        self.primary.write_text(json.dumps({'uid': 51, 'username': 'original'}))
        accounts.add_account(52, 'additional')
        together = threading.Barrier(2)
        def worker(uid, home, operation, day):
            together.wait(timeout=5)
            return {'uid': uid, 'status': 'failed' if uid == 51 else 'complete'}
        with patch.object(accounts, '_run_account', side_effect=worker):
            result = accounts.checkin_all()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['accounts'], [{'uid': 51, 'status': 'failed'}, {'uid': 52, 'status': 'complete'}])

    def test_real_cli_workers_use_isolated_profiles_and_validate_uid(self):
        def cli(*arguments, expected=0):
            env = {**os.environ, 'ONEPOINT3ACRES_UPDATE_WORKER': '1'}
            result = subprocess.run([sys.executable, str(ROOT / 'cli.py'), *arguments],
                                    env=env, capture_output=True, timeout=40)
            self.assertEqual(result.returncode, expected, result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)
        cli('account-add', '52', 'additional')
        self.primary.write_text(json.dumps({'uid': 51, 'username': 'original'}))
        extra = self.state / 'accounts' / '52'
        # Hold each account's real browser lock. No Chrome can start, on either platform.
        from browser import _lock
        for state in (self.state, extra / 'state'):
            handle = self.enterContext((state / 'browser.lock').open('w+b'))
            handle.write(b'0')
            handle.flush()
            _lock(handle, True)
            self.addCleanup(_lock, handle, False)
        result = cli('checkin-all', expected=2)
        self.assertEqual([(r['uid'], r['error']) for r in result['accounts']],
                         [(51, 'another_task_is_using_the_browser'), (52, 'another_task_is_using_the_browser')])
        for home in (self.state.parent, extra):
            self.assertTrue((home / 'chrome-profile').is_dir())
            latest = json.loads((home / 'state' / 'latest-daily.json').read_text())
            self.assertTrue(latest['checkin_only'])
            self.assertTrue(latest['history_saved'])
        self.assertEqual(cli('account-login', '52', expected=2)['error'], 'another_task_is_using_the_browser')
        (extra / 'state' / 'account.json').write_text(json.dumps({'uid': 51, 'username': 'other'}))
        self.assertEqual(cli('checkin-all', expected=2)['accounts'][1]['error'], 'account_profile_mismatch')

    def test_checkin_only_submits_once_without_quiz_and_verifies_reward(self):
        class CheckinBrowser(SubmissionBrowser):
            def account(self):
                return {'uid': 52, 'app_status': {'checkin': self.submissions > 0, 'question': False}, 'rice': 1}
            def rpc(self, method):
                raise AssertionError('unexpected quiz request')
            def evaluate(self, expression):
                return True
            def click_text(self, label):
                if label != '提交签到':
                    raise AssertionError(label)
                self.submissions += 1
            def credit_logs(self):
                return [dict(row, uid=52) for row in super().credit_logs()] if self.rewarded else []
        browser = CheckinBrowser(completed=False, rewarded=False)
        browser.ids['/trpc/reward.checkin'] = 'fixture'
        with patch.multiple(daily, STATE=self.state, ACCOUNT_UID=52, CHECKIN_MOOD_RANDOM=False), \
                patch.object(daily, 'Browser', return_value=browser):
            unpaid = daily.run_daily(checkin_only=True)
            self.assertEqual(unpaid['status'], 'needs_attention')
            browser.rewarded = True
            paid = daily.run_daily(checkin_only=True)
        self.assertEqual(browser.submissions, 1)
        self.assertEqual(paid['status'], 'complete')
        self.assertEqual(paid['reward_verified'], {'checkin': True})
        self.assertEqual(paid['actions'], [{'action': 'checkin', 'completed': True, 'status': 'already_done'}])
        record = daily_history_record(paid)
        self.assertFalse(day_complete(summarize_daily_history([record])[0]))
        self.assertIsNone(daily_retry_due([daily_history_record(unpaid)]))
