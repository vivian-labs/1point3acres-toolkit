"""Run each configured forum account with its own data home and browser lock."""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from contracts import RunStatus, format_error
from rules import site_day
from settings import ACCOUNT_FILE, ACCOUNT_UID, DATA_HOME_ENV, ROOT, STATE, load_identity


def account_homes():
    """None denotes the original account, including its checkout-specific Chrome path."""
    _, primary, _ = load_identity(ACCOUNT_FILE)
    homes = {primary: None} if primary else {}
    directory = STATE / 'accounts'
    if directory.exists():
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if re.fullmatch(r'[1-9][0-9]*', path.name) and path.is_dir():
                homes.setdefault(int(path.name), path)
    return homes


def add_account(uid, username):
    if uid <= 0 or not username.strip() or username != username.strip():
        raise ValueError('invalid_local_account_config')
    primary_name, primary_uid, _ = load_identity(ACCOUNT_FILE)
    directory = STATE / 'accounts'
    home = directory / str(uid)
    if uid == primary_uid:
        existing = primary_name
    else:
        directory.mkdir(parents=True, exist_ok=True)
        # Publish a fully written profile at once, even if two registrations race.
        with TemporaryDirectory(dir=directory) as temporary:
            prepared = Path(temporary) / 'profile'
            state = prepared / 'state'
            state.mkdir(parents=True)
            config = {'uid': uid, 'username': username, 'checkin_mood_random': False}
            (state / 'account.json').write_text(json.dumps(config, ensure_ascii=False) + '\n', encoding='utf-8')
            try:
                prepared.rename(home)
            except OSError:
                if not home.is_dir():
                    raise
        existing, stored_uid, _ = load_identity(home / 'state' / 'account.json')
        if stored_uid != uid:
            raise ValueError('account_profile_mismatch')
    if existing != username:
        raise ValueError('account_profile_mismatch')
    return {'status': RunStatus.COMPLETE, 'uid': uid}


def _run_account(uid, home, operation, argument):
    env = os.environ.copy()
    if home is not None:
        env[DATA_HOME_ENV] = str(home.resolve())
    try:
        # Start the same revision and interpreter as the caller. settings reads the
        # account just once at import, so concurrent runs must be separate processes.
        _, configured, _ = load_identity(home / 'state' / 'account.json' if home else ACCOUNT_FILE)
        if configured != uid:
            raise ValueError('account_profile_mismatch')
        process = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'accounts.py'),
                                  str(uid), operation, argument], env=env, capture_output=True)
        if process.returncode:
            raise RuntimeError('account_worker_failed')
        result = json.loads(process.stdout)
        RunStatus(result['status'])
    except (OSError, KeyError, RuntimeError, ValueError, TypeError) as error:
        result = {'status': RunStatus.FAILED, 'error': format_error(error)}
    return {**result, 'uid': uid}


def login_account(uid, method):
    homes = account_homes()
    if uid not in homes:
        return {'uid': uid, 'status': RunStatus.FAILED, 'error': 'account_not_configured'}
    return _run_account(uid, homes[uid], 'login', method)


def checkin_all():
    homes = account_homes()
    day = site_day()
    if not homes:
        return {'status': RunStatus.FAILED, 'site_day': day, 'accounts': [], 'error': 'account_not_configured'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_account, uid, home, 'checkin', day) for uid, home in homes.items()]
        results = [future.result() for future in futures]
    statuses = {row['status'] for row in results}
    status = (RunStatus.FAILED if RunStatus.FAILED in statuses else
              RunStatus.NEEDS_ATTENTION if RunStatus.NEEDS_ATTENTION in statuses else RunStatus.COMPLETE)
    return {'status': status, 'site_day': day, 'accounts': results}


def _worker(uid, operation, argument):
    if uid != ACCOUNT_UID:
        raise ValueError('account_profile_mismatch')
    if operation == 'login':
        from browser import session_login
        return session_login(method=argument)
    if operation != 'checkin':
        raise ValueError('unsupported_account_operation')
    from daily import run_daily
    run = run_daily(checkin_only=True, _expected_day=argument)
    entry = next((row for row in run['actions'] if row['action'] == 'checkin'), {})
    return {'status': run['status'], 'run_id': run['run_id'], 'action': entry.get('status'),
            'reward_verified': run.get('reward_verified', {}).get('checkin'), 'error': run.get('error')}


if __name__ == '__main__':
    try:
        payload = _worker(int(sys.argv[1]), *sys.argv[2:])
    except Exception as error:
        payload = {'status': RunStatus.FAILED, 'error': format_error(error)}
    print(json.dumps(payload))
