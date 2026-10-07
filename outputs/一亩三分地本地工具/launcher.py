"""Stable entry point: resolve a release before running business code in a fresh interpreter."""
import asyncio
import os
import sys

from settings import UPDATE_OFFLINE_COMMANDS, INSTALLED, CONFIG_FILE, mcp_config
from updates import Manager, command, atomic_json


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    mode = arguments.pop(0) if arguments else 'mcp'
    if mode not in ('cli', 'mcp'):
        raise ValueError('invalid_launcher_mode')
    offline = os.environ.get('ONEPOINT3ACRES_AUTO_UPDATE') == '0'
    if arguments[:1] == ['--offline']:
        offline = True
        arguments.pop(0)
    manager = Manager()
    if INSTALLED and not CONFIG_FILE.exists():
        # Registration always points at the stable installed bootstrap, never a candidate worker.
        atomic_json(CONFIG_FILE, mcp_config())
    if mode == 'mcp':
        from mcp_bridge import Bridge
        return asyncio.run(Bridge(manager, offline=offline).run())
    arguments = arguments or ['status']
    release = manager.resolve(offline=offline or arguments[0] in UPDATE_OFFLINE_COMMANDS)
    result = command([release.python, '-X', 'utf8', release.package / 'cli.py', *arguments],
                     cwd=release.package, env=manager.worker_env(), capture=False)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
