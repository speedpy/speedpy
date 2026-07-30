# Appliku Skill — Reference

This skill teaches Claude Code (and compatible AI agents) how to use the [Appliku](https://appliku.com) CLI and Python SDK. Once installed, the agent will know every command, flag, SDK method, and common workflow without you having to explain them.

## Installation

```bash
npx skills add appliku/skill -g -a claude-code
```

| Flag | Meaning |
|------|---------|
| `-g` | Install globally (`~/.claude/skills/`) rather than project-local |
| `-a claude-code` | Target the Claude Code agent |

After installing, Claude Code automatically loads the skill in every session.

## What the skill covers

- **Authentication** — token resolution order, `appliku login`, `APPLIKU_TOKEN` for CI
- **CLI commands** — full reference for `teams`, `apps`, `deployments`, `domains`, `datastores`, `volumes`, `crons`, `clusters`, `servers`, `invites`, `migrations`, `ssh-keys`
- **Python SDK** — every resource (`apps`, `deployments`, `domains`, `datastores`, `volumes`, `cron_jobs`, `clusters`, `servers`, `invites`, `migrations`, `public_keys`) with method signatures
- **Error handling** — all SDK exception types and their HTTP status codes
- **Common workflows** — finding an app, tailing logs, adding a domain, restarting a datastore
- **Gotchas** — async vs direct log commands, `--output json` for scripting, CLI/SDK capability differences

## Skill file

The skill definition lives at [`SKILL.md`](../SKILL.md) in the repo root. It is the file the agent reads — plain Markdown with YAML frontmatter understood by the `skills` toolchain.

## Requirements

- [Appliku](https://appliku.com) account with an API token
- [`uv`](https://docs.astral.sh/uv/) (recommended for CLI installation) or `pip`
- Python 3.10+ (SDK only)

## Quick-start after skill install

Ask the agent naturally:

> "List all my apps on team `my-team` and show me the latest deployment for the one called `api`."

> "Add `example.com` as a domain and check that DNS is pointed correctly."

> "Write a Python script that restarts the PostgreSQL datastore for app 42 and prints the result."

The agent will translate your intent into the right `appliku` CLI commands or SDK calls.
