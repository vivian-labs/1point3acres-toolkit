"""Entry points of the installed package: `pip install 1point3acres-toolkit` or `uvx 1point3acres-toolkit@latest`.

A checkout runs mcp_server.py and cli.py as scripts, so the flat modules import each other by bare name. The wheel
ships this directory as one package; these functions restore the script layout before importing anything else, so
an installed copy runs exactly the code the checkout runs."""
import sys
from pathlib import Path


def _script_layout():
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    _script_layout()
    from launcher import main as launch
    raise SystemExit(launch(['mcp']))


def cli():
    _script_layout()
    from launcher import main as launch
    raise SystemExit(launch(['cli', *sys.argv[1:]]))


if __name__ == '__main__':
    main()
