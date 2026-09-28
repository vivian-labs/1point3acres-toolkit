# 1point3acres Toolkit

Local automation for the [1point3acres](https://www.1point3acres.com) forum that runs in your own Chrome on your own
machine. It completes the daily check-in and daily quiz and confirms the reward on the credits page, keeps an offline
library of interview-experience posts you can search and export, and offers read, post and reply tools. All of it is
available as a command line and as an MCP server over stdio for Claude Code, Codex and other MCP clients.

The full documentation, in Chinese, is in the repository: https://github.com/vivian-labs/1point3acres-toolkit

## Requirements

- macOS or Windows with Google Chrome installed
- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for the recommended uvx launcher
- A 1point3acres account

## Install

Recommended for users: run the MCP server straight from PyPI:

```sh
uvx 1point3acres-toolkit@latest
```

Or install it into an environment of your own:

```sh
pip install 1point3acres-toolkit
```

The pip installation puts two commands on your PATH: `1point3acres-toolkit` starts the MCP server on stdio, and
`1point3acres-toolkit-cli` runs the same functions from the command line (`1point3acres-toolkit-cli status` to begin).

Register the server with an MCP client:

```sh
claude mcp add --scope user 1point3acres-local -e PYTHONUTF8=1 -- uvx 1point3acres-toolkit@latest
codex mcp add 1point3acres-local --env PYTHONUTF8=1 -- uvx 1point3acres-toolkit@latest
```

`@latest` requests the latest compatible published version whenever the MCP process starts. Reconnect the server
after a release; an already running process does not update itself. Plain `uvx` can reuse an older cached version.
See [uv tool versions](https://docs.astral.sh/uv/concepts/tools/#tool-versions). No Git checkout or pull is needed.

For an existing client registration, set `command` to `uvx` and replace `args` with
`["1point3acres-toolkit@latest"]`, preserving environment variables. Use the absolute uvx path if the client cannot
find it. Editing a generated config alone does not update a registration already saved by the client.

uvx does not permanently install the CLI on PATH. Run it explicitly from the package:

```sh
uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli info
uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli status
```

Use the same prefix for `save-credentials` and other commands. For daily automation, configure the system scheduler
with the absolute uvx path and arguments `--from 1point3acres-toolkit@latest 1point3acres-toolkit-cli daily --resume`.
Use the same data directory as MCP and replace the previous daily task. Each launch checks the package index, adding
network and startup overhead even when the daily task is not due. For a schedule without these update checks, use a
pip-installed CLI and upgrade that environment manually with `python -m pip install --upgrade 1point3acres-toolkit`
while tasks are stopped; reconnect MCP afterward. pip users can also keep a direct MCP console-script registration
without uv. A checkout remains available for developers and requires Git updates.

Check `runtime_info` after reconnecting: verify the expected release and `restart_required=false`.
A clean fingerprint alone does not prove you have the newest published release. Personal data stays in the data
directory across package updates. Moving from a checkout requires a separate data migration; see the Chinese manual.
Maintainers must test and publish a new package to PyPI: pushing code to GitHub alone does not update package users.
Registry-based installs may pin the version in `server.json`; they do not necessarily use `@latest`.

## Where it keeps things

An installed copy writes everything to one per-user directory: `~/Library/Application Support/1point3acres-toolkit`
on macOS, `%LOCALAPPDATA%\1point3acres-toolkit` on Windows. Set `ONEPOINT3ACRES_HOME` to move it. Inside it:

- `state/account.json`: your forum username and numeric uid, the only account facts stored in a file
- `chrome-profile/`: the dedicated Chrome profile that holds the login session
- `state/interviews.sqlite` and `Stripe面经资料/`: the interview library and its exports
- `mcp.config.json`: a uvx `@latest` client entry preserving the data directory, written on first start (requires uv)

The forum password never goes in a file. Store it once with `1point3acres-toolkit-cli save-credentials`, which reads a
JSON object with `username` and `password` on standard input and keeps it in the macOS Keychain or Windows DPAPI.

## What it will not do

- It talks only to the forum's own hosts; there is no third-party server and no captcha service.
- Posting and replying preview by default; a real write to the site needs an explicit flag.
- It never buys unlocks, never mass-downloads and never marks notifications read.

## License

MIT. Source, issues and the Chinese manual: https://github.com/vivian-labs/1point3acres-toolkit

mcp-name: io.github.vivian-labs/1point3acres-toolkit
