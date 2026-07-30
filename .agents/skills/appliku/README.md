# Appliku skill for Claude Code

A [Claude Code skill](https://github.com/anthropics/claude-code) that gives your AI coding assistant full knowledge of the Appliku CLI and Python SDK — so it can deploy apps, manage domains, check logs, and configure your infrastructure without you having to look anything up.

## Install

```bash
npx skills add appliku/skill -g -a claude-code
```

The `-g` flag installs it globally (available in all projects). The `-a claude-code` flag targets Claude Code specifically.

## What it covers

Once installed, Claude Code will know how to:

- **Authenticate** — token-based and browser device-flow login, `APPLIKU_TOKEN` for CI
- **Apps** — list, deploy, fetch logs (async advanced logs and direct service logs)
- **Deployments** — list, get latest, stream deployment logs
- **Domains** — create, delete, check DNS propagation
- **Datastores** — list, start, stop, restart, delete
- **Volumes** — list, delete
- **Cron jobs** — list, delete
- **Clusters & Servers** — list, inspect
- **Invites** — list, delete
- **Migrations** — list, stream logs
- **SSH keys** — list, add, delete
- **Python SDK** — full `Appliku` client API including `create`, `update`, config vars, error handling

## Requirements

- [uv](https://docs.astral.sh/uv/) — used to install the `appliku` package
- Python 3.10+

Install the CLI:

```bash
uv tool install appliku
appliku login
```

## Full documentation

[docs.appliku.com/docs/cli-sdk](https://docs.appliku.com/docs/cli-sdk/)
