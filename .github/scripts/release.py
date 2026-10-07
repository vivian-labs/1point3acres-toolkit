"""Release gates: tested main commit -> matching PyPI bytes -> GitHub Release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib
from urllib.error import HTTPError
from urllib.request import urlopen


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def github(path):
    result = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if result.returncode:
        if '(HTTP 404)' in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def version_number(value):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Only stable major.minor.patch versions may be published')
    return tuple(map(int, value.split('.')))


def version_changed(current, previous, registry):
    current_number, previous_number = version_number(current), version_number(previous)
    if registry['version'] != current or [p['version'] for p in registry['packages']] != [current]:
        raise ValueError('Package and registry versions differ')
    if current_number < previous_number:
        raise ValueError('Release versions must increase')
    return current_number > previous_number


def successful_ci(runs, sha):
    return any(r['head_sha'] == sha and r['head_branch'] == 'main'
               and r['event'] in ('push', 'workflow_dispatch')
               and r['status'] == 'completed' and r['conclusion'] == 'success' for r in runs)


def check_tag(repo, tag, sha):
    ref = github(f'repos/{repo}/git/ref/tags/{tag}')
    if ref is None:
        return
    obj = ref['object']
    while obj['type'] == 'tag':
        obj = github(f'repos/{repo}/git/tags/{obj["sha"]}')['object']
    if obj['type'] != 'commit' or obj['sha'] != sha:
        raise ValueError('Existing release tag points at a different commit')


def prepare():
    sha = command('git', 'rev-parse', 'HEAD')
    if sha not in command('git', 'rev-list', '--first-parent', 'origin/main').splitlines():
        raise ValueError('Release commit must be on the first-parent history of main')
    version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
    previous = tomllib.loads(command('git', 'show', 'HEAD^1:pyproject.toml'))['project']['version']
    changed = version_changed(version, previous, json.loads(Path('server.json').read_text()))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'publish={str(changed).lower()}\n')
        if not changed:
            return
        repo = os.environ['GITHUB_REPOSITORY']
        runs = github(f'repos/{repo}/actions/workflows/consistency.yml/runs?head_sha={sha}&per_page=100')
        if not successful_ci(runs['workflow_runs'], sha):
            raise ValueError('No successful main CI for the exact release commit')
        check_tag(repo, 'v' + version, sha)
        output.write(f'version={version}\nsha={sha}\ntag=v{version}\n')
    with open(os.environ['GITHUB_ENV'], 'a') as env:
        env.write('SOURCE_DATE_EPOCH=' + command('git', 'show', '-s', '--format=%ct', sha) + '\n')


def pypi_files(version):
    try:
        with urlopen(f'https://pypi.org/pypi/1point3acres-toolkit/{version}/json', timeout=30) as response:
            return json.load(response)['urls']
    except HTTPError as error:
        if error.code == 404:
            return []
        raise


def compare_files(local, remote, complete):
    uploaded = {}
    for item in remote:
        if item.get('yanked'):
            raise ValueError('Refusing a yanked release')
        uploaded[item['filename']] = item['digests']['sha256']
    if any(name not in local or local[name] != digest for name, digest in uploaded.items()):
        raise ValueError('PyPI already contains different files for this version')
    return uploaded == local if complete else True


def verify(version, complete=False):
    version_number(version)
    paths = sorted(Path('dist').iterdir())
    if len(paths) != 2 or sum(p.suffix == '.whl' for p in paths) != 1 or sum(p.name.endswith('.tar.gz') for p in paths) != 1:
        raise ValueError('Expected exactly one wheel and one sdist')
    local = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for attempt in range(12 if complete else 1):
        if compare_files(local, pypi_files(version), complete):
            return
        if attempt < 11:
            time.sleep(5)
    raise ValueError('PyPI does not yet contain every expected release file')


def release(version, sha):
    verify(version, complete=True)
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Expected a full commit SHA')
    repo, tag = os.environ['GITHUB_REPOSITORY'], 'v' + version
    check_tag(repo, tag, sha)
    existing = github(f'repos/{repo}/releases/tags/{tag}')
    if existing:
        if existing['draft'] or existing['prerelease']:
            raise ValueError('Existing GitHub Release is not a stable public release')
        return
    subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', sha,
                    '--title', tag, '--generate-notes', '--notes',
                    f'PyPI {version} wheel and sdist verified against commit {sha}.\n\n'
                    f'https://pypi.org/project/1point3acres-toolkit/{version}/'], check=True)
    check_tag(repo, tag, sha)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'verify', 'release'])
    parser.add_argument('--version')
    parser.add_argument('--sha')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'verify':
        verify(args.version)
    else:
        release(args.version, args.sha)
