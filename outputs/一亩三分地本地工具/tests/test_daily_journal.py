import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import daily
from library import Library
from rules import site_day
from tests.test_access_recovery import SubmissionBrowser


class JournalTests(unittest.TestCase):
    def invoke(self, root, session):
        with patch('daily.STATE', root), patch('daily.ACCOUNT_UID', 123456), \
                patch('daily.Browser', return_value=session), patch('daily.time.monotonic', side_effect=[0, 100]):
            return daily.run_daily(supplied_answer='Answer', expected_question='Synthetic question')

    def test_killed_after_click_leaves_intent_and_restart_does_not_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(False, False)
            click = session.click_text

            def killed(label):
                if label == '提交答案':
                    db = Library(root / daily.DATABASE_NAME)
                    try:
                        days = db.daily_history(123456, site_day(), 10)['days']
                        self.assertTrue(days)
                        self.assertIsNotNone(days[0]['actions'][1]['unconfirmed_submission_run_id'])
                    finally:
                        db.close()
                    click(label)
                    raise KeyboardInterrupt('synthetic process interruption')
                click(label)

            with patch.object(session, 'click_text', side_effect=killed), self.assertRaises(KeyboardInterrupt):
                self.invoke(root, session)
            later = self.invoke(root, session)
            self.assertEqual(session.submissions, 1)
            self.assertEqual(later['error'], 'quiz_submission_unconfirmed')
            session.completed = session.rewarded = True
            self.assertEqual(self.invoke(root, session)['status'], 'complete')
            self.assertEqual(session.submissions, 1)

    def test_quiz_wait_interruption_reuses_remaining_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(True, True)
            now = datetime.now(timezone.utc)
            with patch('daily.datetime', wraps=datetime) as clock, \
                    patch('rules.SystemRandom') as random:
                clock.now.return_value = now
                random.return_value.uniform.return_value = 50
                session.sb.sleep.side_effect = KeyboardInterrupt('synthetic interruption')
                with self.assertRaises(KeyboardInterrupt):
                    self.invoke(root, session)
                self.assertEqual(session.submissions, 0)
                clock.now.return_value = now + timedelta(seconds=20)
                session.sb.sleep.side_effect = None
                self.assertEqual(self.invoke(root, session)['status'], 'complete')
                self.assertEqual(session.submissions, 1)
                self.assertEqual(session.sb.sleep.call_args_list[-1].args, (30.0,))
                random.return_value.uniform.assert_called_once_with(30, 70)

    def test_expired_quiz_gap_needs_no_wait_and_clock_rollback_stops(self):
        from unittest.mock import Mock
        now = datetime.now(timezone.utc)
        session = SubmissionBrowser(True, True)
        with patch('daily.datetime', wraps=datetime) as clock:
            clock.now.return_value = now
            daily._wait_quiz_gap(session, {'ready_at': (now - timedelta(seconds=1)).isoformat()})
            session.sb.sleep.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, '^daily_clock_changed$'):
                daily._wait_quiz_gap(session, {'ready_at': (now + timedelta(minutes=5)).isoformat()})
        rng = Mock()
        for seconds in (30, 70):
            rng.uniform.return_value = seconds
            plan = daily.make_quiz_gap(now, rng)
            self.assertEqual(datetime.fromisoformat(plan['ready_at']) - now, timedelta(seconds=seconds))

    def test_storage_failure_prevents_the_click(self):
        with tempfile.TemporaryDirectory() as directory:
            session = SubmissionBrowser(False, False)
            with patch.object(Library, 'save_daily', side_effect=OSError('synthetic failure')):
                result = self.invoke(Path(directory), session)
            self.assertEqual(session.submissions, 0)
            self.assertEqual(result['error'], 'daily_history_write_failed')

    def test_midnight_during_gap_stops_before_quiz_click(self):
        with tempfile.TemporaryDirectory() as directory:
            session = SubmissionBrowser(True, True)
            current_day = site_day()
            def midnight(seconds):
                nonlocal current_day
                current_day = '2099-01-01'
            session.sb.sleep.side_effect = midnight
            with patch('daily.site_day', side_effect=lambda now=None: site_day(now) if now else current_day):
                result = self.invoke(Path(directory), session)
            self.assertEqual(result['error'], 'site_day_changed')
            self.assertEqual(session.submissions, 0)

    def test_expiration_during_gap_does_not_leave_pending_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(True, True)
            def expire(seconds):
                session.expired = True
            session.sb.sleep.side_effect = expire
            first = self.invoke(root, session)
            self.assertEqual(first['error'], 'daily_run_timeout')
            self.assertEqual(session.submissions, 0)
            session.expired = False
            session.sb.sleep.side_effect = None
            self.assertEqual(self.invoke(root, session)['status'], 'complete')
            self.assertEqual(session.submissions, 1)

    def test_proven_no_click_removes_intent_and_allows_later_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(True, True)
            original = session.click_text
            def not_ready(label):
                if label == '提交答案':
                    raise RuntimeError('button_not_ready')
                original(label)
            with patch.object(session, 'click_text', side_effect=not_ready):
                self.assertEqual(self.invoke(root, session)['error'], 'button_not_ready')
            self.assertEqual(self.invoke(root, session)['status'], 'complete')
            self.assertEqual(session.submissions, 1)

    def test_temporary_storage_failure_does_not_block_later_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(True, True)
            original = Library.save_daily
            failed = False

            def fail_once(db, *args, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError('synthetic lock')
                return original(db, *args, **kwargs)

            with patch.object(Library, 'save_daily', fail_once):
                result = self.invoke(root, session)
            self.assertEqual(result['error'], 'daily_history_write_failed')
            self.assertEqual(session.submissions, 0)
            self.assertEqual(self.invoke(root, session)['status'], 'complete')
            self.assertEqual(session.submissions, 1)

    def test_midnight_during_checkpoint_prevents_click_and_clears_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SubmissionBrowser(True, True)
            original = Library.save_daily
            current_day = site_day()

            def cross_midnight(db, *args, **kwargs):
                nonlocal current_day
                saved = original(db, *args, **kwargs)
                current_day = '2099-01-01'
                return saved

            with patch.object(Library, 'save_daily', cross_midnight), \
                    patch('daily.site_day', side_effect=lambda now=None: site_day(now) if now else current_day):
                result = self.invoke(root, session)
            self.assertEqual(result['error'], 'site_day_changed')
            self.assertEqual(session.submissions, 0)
            self.assertEqual(self.invoke(root, session)['status'], 'complete')
            self.assertEqual(session.submissions, 1)


class QuizRecoveryTests(unittest.TestCase):
    def setUp(self):
        import itertools
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.session = SubmissionBrowser(False, False)
        for name, value in [('STATE', self.root), ('ACCOUNT_UID', 123456)]:
            self.stack.enter_context(patch.object(daily, name, value))
        self.factory = self.stack.enter_context(patch('daily.Browser', return_value=self.session))
        self.stack.enter_context(patch('daily.time.monotonic', side_effect=itertools.cycle([0, 100])))
        self.stack.enter_context(patch('daily.draw_daily_due_at', return_value=datetime.now(timezone.utc) - timedelta(hours=1)))

    def run_quiz(self, **kwargs):
        return daily.run_daily(supplied_answer='Answer', expected_question='Synthetic question', **kwargs)

    def authorize(self, first):
        return dict(retry_quiz=first['run_id'], retry_day=first['site_day'], retry_uid=123456)

    def history(self):
        db = Library(self.root / daily.DATABASE_NAME)
        try:
            return db.daily_history(123456, site_day(), 1)['days'][0]['actions'][1]
        finally:
            db.close()

    def test_manual_retry_is_consumed_even_when_second_response_is_lost(self):
        first = self.run_quiz()
        self.assertEqual(first['attention']['run_id'], first['run_id'])
        second = self.run_quiz(**self.authorize(first))
        self.assertEqual(self.session.submissions, 2)
        self.assertEqual(self.history()['submission_attempts'], 2)
        self.assertEqual(self.history()['unconfirmed_submission_run_id'], second['run_id'])
        replay = self.run_quiz(**self.authorize(first))
        self.assertEqual(replay['error'], 'quiz_recovery_stale')
        self.assertEqual(self.session.submissions, 2)

    def test_manual_retry_success_verifies_reward_and_learns(self):
        first = self.run_quiz()
        original = self.session.click_text
        def accept(text):
            original(text)
            if text == '提交答案':
                self.session.completed = self.session.rewarded = True
        with patch.object(self.session, 'click_text', side_effect=accept) as click:
            recovered = self.run_quiz(**self.authorize(first))
        self.assertEqual(recovered['status'], 'complete')
        self.assertTrue(recovered['reward_verified']['quiz'])
        self.assertEqual(self.session.submissions, 2)
        self.assertNotIn(('提交签到',), [call.args for call in click.call_args_list])
        self.assertIsNone(self.history()['unconfirmed_submission_run_id'])

    def test_bound_account_day_question_and_token_reject_stale_recovery(self):
        first = self.run_quiz()
        auth = self.authorize(first)
        for changed in [dict(retry_uid=654321), dict(retry_day='2000-01-01'), dict(retry_quiz='wrong')]:
            result = self.run_quiz(**(auth | changed))
            self.assertIn(result['error'], ('invalid_quiz_recovery', 'quiz_recovery_stale'))
        wrong_question = daily.run_daily(supplied_answer='Answer', expected_question='Different question', **auth)
        self.assertEqual(wrong_question['error'], 'question_changed_or_not_confirmed')
        self.assertEqual(self.session.submissions, 1)
        self.assertEqual(self.history()['unconfirmed_submission_run_id'], first['run_id'])

    def test_reward_or_completed_evidence_prevents_manual_resubmission(self):
        first = self.run_quiz()
        self.session.rewarded = True  # Reward exists even if completion flag has not caught up.
        self.run_quiz(**self.authorize(first))
        self.assertEqual(self.session.submissions, 1)
        self.assertTrue(self.history()['reward_verified'])

    def test_unknown_click_failure_is_counted_and_does_not_auto_replay(self):
        from contracts import BrowserConnectionError
        original = self.session.click_text
        def disconnected(text):
            if text == '提交答案':
                raise BrowserConnectionError('browser_connection_lost')
            original(text)
        with patch.object(self.session, 'click_text', side_effect=disconnected):
            first = self.run_quiz()
        self.assertEqual(first['error'], 'browser_connection_lost')
        self.assertEqual(self.history()['submission_attempts'], 1)
        self.assertEqual(first['actions'][-1]['submission_phase'], 'click_started')
        self.run_quiz()
        self.assertEqual(self.session.submissions, 0)
        with patch('daily.Browser') as unopened:
            waiting = daily.resume_daily()
            self.assertEqual(waiting['decision'], 'manual_recovery_required')
            self.assertEqual(waiting['attention']['run_id'], first['run_id'])
            unopened.assert_not_called()

    def test_disconnect_before_submit_is_retried_automatically(self):
        from contracts import BrowserConnectionError
        self.session.completed = self.session.rewarded = True
        with patch.object(self.session, 'wait_for', side_effect=[BrowserConnectionError('browser_connection_lost'), True, True]):
            result = daily.resume_daily(supplied_answer='Answer', expected_question='Synthetic question')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual(self.session.submissions, 1)

    def test_explicit_no_click_keeps_original_authorization_available(self):
        first = self.run_quiz()
        original = self.session.click_text
        def not_ready(text):
            if text == '提交答案':
                raise RuntimeError('button_not_ready')
            original(text)
        with patch.object(self.session, 'click_text', side_effect=not_ready):
            failed = self.run_quiz(**self.authorize(first))
        self.assertEqual(failed['error'], 'button_not_ready')
        self.assertEqual(self.history()['unconfirmed_submission_run_id'], first['run_id'])
        self.run_quiz(**self.authorize(first))
        self.assertEqual(self.session.submissions, 2)

    def test_cross_day_during_recovery_stops_before_click(self):
        first = self.run_quiz()
        day = first['site_day']
        original = self.session.rpc
        def rollover(method):
            nonlocal day
            day = '2099-01-01'
            return original(method)
        with patch.object(self.session, 'rpc', side_effect=rollover), \
                patch('daily.site_day', side_effect=lambda now=None: site_day(now) if now else day):
            failed = self.run_quiz(**self.authorize(first))
        self.assertEqual(failed['error'], 'site_day_changed')
        self.assertEqual(self.session.submissions, 1)

    def test_recovery_checks_live_account_identity(self):
        first = self.run_quiz()
        original = self.session.account
        with patch.object(self.session, 'account', side_effect=lambda: original() | {'uid': 654321}):
            failed = self.run_quiz(**self.authorize(first))
        self.assertEqual(failed['error'], 'invalid_quiz_recovery')
        self.assertEqual(self.session.submissions, 1)

    def test_failed_verification_does_not_suspend_scheduler(self):
        self.run_quiz()
        with patch.object(self.session, 'credit_logs', side_effect=RuntimeError('network_timeout')):
            failed = self.run_quiz()
        self.assertEqual(failed['error'], 'network_timeout')
        self.assertEqual(self.history()['unconfirmed_checks'], 0)
        self.run_quiz()
        self.assertEqual(self.history()['unconfirmed_checks'], 1)

    def test_recovery_intent_survives_process_interruption(self):
        first = self.run_quiz()
        original = self.session.click_text
        def killed(text):
            original(text)
            if text == '提交答案':
                raise KeyboardInterrupt('synthetic interruption')
        with patch.object(self.session, 'click_text', side_effect=killed), self.assertRaises(KeyboardInterrupt):
            self.run_quiz(**self.authorize(first))
        self.assertNotEqual(self.history()['unconfirmed_submission_run_id'], first['run_id'])
        replay = self.run_quiz(**self.authorize(first))
        self.assertEqual(replay['error'], 'quiz_recovery_stale')
        self.assertEqual(self.session.submissions, 2)

    def test_invalid_recovery_is_rejected_without_browser(self):
        with patch('daily.Browser') as unopened:
            result = daily.run_daily(retry_quiz='run', retry_day=site_day(), retry_uid=123456)
            self.assertEqual(result['error'], 'invalid_quiz_recovery')
            unopened.assert_not_called()

    def test_cli_recovery_routes_binding_and_rejects_scheduler_combination(self):
        import cli
        import io
        import sys
        argv = ['cli.py', 'daily', '--retry-quiz', 'run', '--site-day', site_day(),
                '--account-uid', '123456', '--question', 'Synthetic question', '--answer', 'Answer']
        with patch.object(sys, 'argv', argv), patch('sys.stdout', new_callable=io.StringIO), \
                patch('cli.run_daily', return_value={'status': 'complete'}) as run:
            cli.main()
            run.assert_called_once_with(False, 'Answer', 'Synthetic question', retry_quiz='run',
                                        retry_day=site_day(), retry_uid=123456)
        with patch.object(sys, 'argv', argv + ['--resume']), patch('sys.stderr', new_callable=io.StringIO), \
                patch('cli.run_daily') as run, self.assertRaises(SystemExit) as failure:
            cli.main()
        self.assertEqual(failure.exception.code, 2)
        run.assert_not_called()
