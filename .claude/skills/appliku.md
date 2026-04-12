---
name: appliku
description: Use when working with the appliku CLI or SDK to manage Appliku-hosted applications, deployments, domains, datastores, servers, teams, or SSH keys. Covers authentication, all CLI commands, Python SDK usage, and common deployment workflows.
user-invocable: false
---

# Appliku CLI & SDK Reference

Appliku is a PaaS platform. The `appliku` package provides both a CLI and a Python SDK.

## Installation

### 1. Check for uv

```bash
uv --version
```

If the command is not found, install uv first:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, restart the shell (or source the profile) so `uv` is on `$PATH`.

### 2. Check for the appliku CLI

```bash
appliku --version
```

If not found, install it as a uv tool:

```bash
uv tool install appliku
```

Then verify:

```bash
appliku --help
```

### SDK (inside a Python project)

```bash
uv add appliku
# or
pip install appliku
```

Requires Python 3.10+.

## Authentication

Token resolution order (first match wins):

1. Explicit: `Appliku(token="...")`
2. Environment variable: `APPLIKU_TOKEN=...`
3. Config file: `~/.config/appliku/config.toml` → `[auth] token = "..."`

### For non-interactive / CI environments

```bash
export APPLIKU_TOKEN=your_api_token
```

### Interactive login (browser device flow)

```bash
appliku login              # opens browser to authorize
appliku login --token TOKEN  # direct token login (non-interactive)
appliku logout
appliku whoami
```

## Key Concepts

- **team_path**: a slug identifying your team (e.g. `my-team`). Required by most commands.
- **app id**: numeric ID of an application. Get it from `appliku apps list --team my-team --output json`.
- **resource id**: numeric ID for domains, datastores, volumes, crons, etc.
- Most list commands support `--output json` for machine-readable output.

## CLI Command Reference

### teams

```bash
appliku teams list
appliku teams get <team_path>
```

### apps

```bash
appliku apps list --team <team_path>
appliku apps list --team <team_path> --output json

# Application-level logs (async, polls until ready)
appliku apps logs --team <team_path> --app <id> --process web
appliku apps logs --team <team_path> --app <id> --process web --process celery --tail 200

# Service logs (direct, single process)
appliku apps service-logs --team <team_path> --app <id> --service web --tail 100

# Nginx / load balancer logs
appliku apps nginx-logs         --team <team_path> --app <id> --domain example.com --tail 100
appliku apps load-balancer-logs --team <team_path> --app <id> --domain example.com --tail 100
```

### deployments

```bash
appliku deployments list   --team <team_path> --app <id>
appliku deployments latest --team <team_path> --app <id>
appliku deployments logs   --team <team_path> --id <deployment_id>
```

### domains

```bash
appliku domains list      --team <team_path> --app <id>
appliku domains create    --team <team_path> --app <id> --domain example.com
appliku domains delete    --team <team_path> --app <id> --id <domain_id>
appliku domains check-dns --team <team_path> --app <id> --domain example.com
```

### datastores

```bash
appliku datastores list    --team <team_path> --app <id>
appliku datastores start   --team <team_path> --app <id> --id <datastore_id>
appliku datastores stop    --team <team_path> --app <id> --id <datastore_id>
appliku datastores restart --team <team_path> --app <id> --id <datastore_id>
appliku datastores delete  --team <team_path> --app <id> --id <datastore_id>
```

### volumes

```bash
appliku volumes list   --team <team_path> --app <id>
appliku volumes delete --team <team_path> --app <id> --id <volume_id>
```

### crons

```bash
appliku crons list   --team <team_path> --app <id>
appliku crons delete --team <team_path> --app <id> --id <cron_id>
```

### clusters

```bash
appliku clusters list   --team <team_path>
appliku clusters delete --team <team_path> --id <cluster_id>
```

### servers

```bash
appliku servers list --team <team_path>
appliku servers get  --team <team_path> --id <server_id>
```

### invites

```bash
appliku invites list   --team <team_path>
appliku invites delete --team <team_path> --id <invite_id>
```

### migrations

```bash
appliku migrations list --team <team_path>
appliku migrations logs --team <team_path> --id <migration_id>
```

### ssh-keys

```bash
appliku ssh-keys list
appliku ssh-keys add    --key "ssh-rsa AAAA... user@host"
appliku ssh-keys add    --key "$(cat ~/.ssh/id_ed25519.pub)"
appliku ssh-keys delete --id <key_id>
```

## Python SDK Reference

```python
from appliku import Appliku

client = Appliku()                     # uses APPLIKU_TOKEN or config file
client = Appliku(token="YOUR_TOKEN")   # explicit token
```

### apps

```python
client.apps.list("my-team")
client.apps.get("my-team", app_id=42)
client.apps.create("my-team", name="my-app", branch="main")
client.apps.update("my-team", app_id=42, branch="develop")
client.apps.delete("my-team", app_id=42)
client.apps.deploy("my-team", app_id=42)

# Config vars
vars = client.apps.get_config_vars("my-team", app_id=42)
client.apps.set_config_vars("my-team", app_id=42, vars={"DEBUG": "false"})

# Logs
logs = client.apps.get_logs("my-team", app_id=42, process="web", tail=100)
logs = client.apps.get_service_logs("my-team", app_id=42, service="web", tail=100)
logs = client.apps.get_nginx_logs("my-team", app_id=42, domain="example.com", tail=100)
logs = client.apps.get_load_balancer_logs("my-team", app_id=42, domain="example.com", tail=100)
```

### deployments

```python
client.deployments.list("my-team", app_id=42)
client.deployments.get("my-team", app_id=42, deployment_id=1234)
client.deployments.latest("my-team", app_id=42)
client.deployments.logs("my-team", deployment_id=1234)
```

### domains

```python
client.domains.list("my-team", app_id=42)
client.domains.get("my-team", app_id=42, domain_id=7)
client.domains.create("my-team", app_id=42, domain="example.com")
client.domains.delete("my-team", app_id=42, domain_id=7)
result = client.domains.check_dns("my-team", app_id=42, domain="example.com")
```

### datastores

```python
client.datastores.list("my-team", app_id=42)
client.datastores.get("my-team", app_id=42, datastore_id=5)
client.datastores.create("my-team", app_id=42, name="mydb", kind="postgresql")
client.datastores.start("my-team", app_id=42, datastore_id=5)
client.datastores.stop("my-team", app_id=42, datastore_id=5)
client.datastores.restart("my-team", app_id=42, datastore_id=5)
client.datastores.delete("my-team", app_id=42, datastore_id=5)
```

### volumes

```python
client.volumes.list("my-team", app_id=42)
client.volumes.create("my-team", app_id=42, name="uploads", mount_path="/app/uploads")
client.volumes.update("my-team", app_id=42, volume_id=3, mount_path="/app/media")
client.volumes.delete("my-team", app_id=42, volume_id=3)
```

### cron_jobs

```python
client.cron_jobs.list("my-team", app_id=42)
client.cron_jobs.create("my-team", app_id=42, schedule="0 * * * *", command="python manage.py clearsessions")
client.cron_jobs.update("my-team", app_id=42, cron_id=8, schedule="30 2 * * *")
client.cron_jobs.delete("my-team", app_id=42, cron_id=8)
```

### clusters

```python
client.clusters.list("my-team")
client.clusters.get("my-team", cluster_id=2)
client.clusters.create("my-team", name="prod-cluster")
client.clusters.delete("my-team", cluster_id=2)
```

### servers

```python
client.servers.list("my-team")
client.servers.get("my-team", server_id=10)
```

### invites

```python
client.invites.list("my-team")
client.invites.create("my-team", email="colleague@example.com")
client.invites.delete("my-team", invite_id=4)
```

### migrations

```python
client.migrations.list("my-team")
client.migrations.run("my-team", app_id=42, command="python manage.py migrate")
client.migrations.logs("my-team", migration_id=99)
```

### public_keys

```python
client.public_keys.list()
client.public_keys.create("ssh-rsa AAAA... user@host")
client.public_keys.delete(key_id=12)
```

## Error Handling (SDK)

```python
from appliku import (
    Appliku,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServerError,
)

client = Appliku()
try:
    client.teams.get("missing-team")
except AuthenticationError:
    print("Invalid or missing token")
except NotFoundError as exc:
    print(exc)
```

| Exception | HTTP status |
|---|---|
| `AuthenticationError` | 401 |
| `AuthorizationError` | 403 |
| `NotFoundError` | 404 |
| `ValidationError` | 400 |
| `RateLimitError` | 429 |
| `ServerError` | 5xx |

## Common Workflows

### Find an app and check its latest deployment

```bash
appliku teams list
appliku apps list --team my-team --output json   # grab the numeric app id
appliku deployments latest --team my-team --app 42
appliku deployments logs --team my-team --id <deployment_id>
```

### Tail application logs

```bash
# All processes (web + celery)
appliku apps logs --team my-team --app 42 --process web --process celery --tail 200

# Single service, direct (faster)
appliku apps service-logs --team my-team --app 42 --service web --tail 100
```

### Add a custom domain and verify DNS

```bash
appliku domains create    --team my-team --app 42 --domain example.com
appliku domains check-dns --team my-team --app 42 --domain example.com
```

### Restart a datastore

```bash
appliku datastores list    --team my-team --app 42   # get the datastore id
appliku datastores restart --team my-team --app 42 --id 5
```

## Gotchas

- **CLI surface < SDK surface**: The SDK exposes `create`, `update`, `deploy`, config vars, etc. that the CLI does not. Use the Python SDK for those operations.
- **`apps logs` is async**: It POSTs a request, then polls until logs are ready. `apps service-logs` is a single GET and returns immediately — prefer it when you only need one process.
- **`--process` is repeatable**: Pass it multiple times to fetch logs for multiple processes in one call: `--process web --process celery`.
- **Machine-readable output**: Add `--output json` to any list command when you need to parse IDs programmatically.
- **`APPLIKU_TOKEN` for CI**: Set this environment variable to avoid interactive login in automated contexts.
