# 1point3acres Toolkit

Local automation for the [1point3acres](https://www.1point3acres.com) forum that runs in your own Chrome on your own
machine. It completes the daily check-in and daily quiz and confirms the reward on the credits page, keeps an offline
library of interview-experience posts you can search and export, and offers read, post and reply tools. All of it is
available as a command line and as an MCP server over stdio for Claude Code, Codex and other MCP clients.

The full documentation, in Chinese, is in the repository: https://github.com/vivian-labs/1point3acres-toolkit

## Requirements

- macOS or Windows with Google Chrome installed
- Python 3.12
- Git for the automatic source update channel
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for the recommended uvx launcher
- A 1point3acres account

## Install

Recommended for users: run the MCP server straight from PyPI:

```sh
uvx 1point3acres-toolkit@latest
```

**AI-assisted installation defaults to automatic updates.** When a user supplies this project and asks for setup,
use the `uvx …@latest` entries for both MCP and the daily scheduler. Follow the
[installation checklist](https://github.com/vivian-labs/1point3acres-toolkit/blob/main/outputs/一亩三分地本地工具/README.md#ai),
preserve existing data, and read back the saved client and scheduler configuration before reporting completion.
Use source checkouts or fixed installations only when requested. A one-time install does not configure automatic updates.

Alternatively, install the same bootstrap in your own environment:

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

`@latest` requests the latest compatible bootstrap release whenever the MCP process starts. From 1.2.0, the bootstrap
also follows this repository's main branch and accepts only the exact commit that passed the complete push CI workflow.
It prepares code and dependencies in an isolated private cache before activation. CLI business commands check before
execution; a connected MCP bridge checks before business calls and every 60 seconds while idle, switching workers only
after active requests finish. It keeps the client connection and never replays a submitted business request.
Git and network access are required. Failed updates keep the last validated version. Plain `uvx` can reuse an older
bootstrap; see [uv tool versions](https://docs.astral.sh/uv/concepts/tools/#tool-versions).

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
network and startup overhead even when the daily task is not due. The toolkit also checks approved source updates.
Use `ONEPOINT3ACRES_AUTO_UPDATE=0` to disable toolkit update checks for development or an offline installed environment;
uvx's package-index check is independent. `info` and `daily-history` are offline toolkit health queries.

Upgrade pre-1.2.0 installations and reconnect their old MCP process once to load the bootstrap. After that, compatible
business updates switch automatically; bootstrap, account configuration or incompatible protocol changes may still
require restarting. Check `runtime_info` for the actual `loaded.revision` and sanitized `updates` diagnostics. Personal
data stays in the same directory; moving from a checkout requires a separate data migration, covered in the manual.
The initial bootstrap release must be published to PyPI; subsequent compatible business changes can follow approved
GitHub main commits directly. Registry-based installs may pin the bootstrap version in `server.json`.

## Where it keeps things

An installed copy writes everything to one per-user directory: `~/Library/Application Support/1point3acres-toolkit`
on macOS, `%LOCALAPPDATA%\1point3acres-toolkit` on Windows. Set `ONEPOINT3ACRES_HOME` to move it. Inside it:

- `state/account.json`: your forum username and numeric uid, the only account facts stored in a file
- `chrome-profile/`: the dedicated Chrome profile that holds the login session
- `state/interviews.sqlite` and `Stripe面经资料/`: the interview library and its exports
- `mcp.config.json`: a uvx `@latest` client entry preserving the data directory, written on first start (requires uv)
- `updates/`: private source checkouts, dependency environments and the atomic active-version pointer

The forum password never goes in a file. Store it once with `1point3acres-toolkit-cli save-credentials`, which reads a
JSON object with `username` and `password` on standard input and keeps it in the macOS Keychain or Windows DPAPI.

## What it will not do

- Forum operations use only the forum's own hosts. Software updates access the fixed GitHub repository and API;
  dependency installation uses the configured package index. There is no captcha service.
- Posting and replying preview by default; a real write to the site needs an explicit flag.
- It never buys unlocks, never mass-downloads and never marks notifications read.

## License

MIT. Source, issues and the Chinese manual: https://github.com/vivian-labs/1point3acres-toolkit

mcp-name: io.github.vivian-labs/1point3acres-toolkit
