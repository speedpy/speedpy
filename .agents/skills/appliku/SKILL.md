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

`teams get` returns the same fields whatever your membership level, but values you
are not entitled to read come back as `null`. Admins see `null` for the billing
fields (`paddle_*`), `can_invite_members` and `name_picked`; developers
additionally see `null` for the deploy keys (`public_key`, `public_key_ed25519`)
and the notification webhook URLs. So a `null` means either "not set" or "not
visible to you" — for billing values, check as an owner before concluding a team
has no subscription. Requires CLI 0.5.0 or newer; older versions crashed for any
non-owner.

### apps

```bash
appliku apps list --team <team_path>
appliku apps list --team <team_path> --output json

# Create from GitHub or GitLab. Use exactly one positive target ID.
appliku apps create github owner/repository -t <team_path> -n myapp -b main --server <id>
appliku apps create gitlab group/repository -t <team_path> -n myapp -b main --cluster <id>

# Create from custom Git. A URL file can contain HTTPS credentials.
appliku apps create custom -t <team_path> -n myapp -b main --server <id> \
  --git-url-file <path-or-> [--private-key-file <path>]

# Trigger a deployment
appliku apps deploy --team <team_path> --app <id>

# Delete a single config var (leaves the rest untouched)
appliku apps delete-config-var --team <team_path> --app <id> --key SOME_VAR

# Application logs — one command, any deployment mode, one or more processes.
# With no --process it returns logs for ALL of the app's processes.
appliku apps logs --team <team_path> --app <id>
appliku apps logs --team <team_path> --app <id> --process web
appliku apps logs --team <team_path> --app <id> --process web --process celery --tail 200

# service-logs is DEPRECATED — use `apps logs -p <service>` instead.

# Nginx / load balancer logs
appliku apps nginx-logs         --team <team_path> --app <id> --domain example.com --tail 100
appliku apps load-balancer-logs --team <team_path> --app <id> --domain example.com --tail 100
```

Each create command accepts `--static-site` and `--output table|json`. Custom
Git also accepts a positional public URL, but exactly one positional URL or
`--git-url-file` is required. Use a file or standard input (`--git-url-file -`)
for a URL that contains credentials. Private keys are accepted only through
`--private-key-file`. Output is limited to safe application fields and does not
contain these secrets.

Create starts the asynchronous initial `appliku.yml` inspection. It does not
deploy the application. Deploy it separately when its setup is complete.

**The target must be ready.** A server or cluster that has not finished setup is
refused with HTTP 400. Check before creating — `appliku servers list` reports a
`ready` field, and only a ready target can host a new application:

```bash
appliku servers list --team <team_path> --output json | jq '.[] | select(.ready)'
```

A team whose servers are all still provisioning cannot create an application
yet. Wait for setup to finish rather than retrying immediately.

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

# Hetzner Cloud server provisioning (requires the team to have a stored
# Hetzner Cloud token, configured in the dashboard under Team Settings ->
# Cloud Providers).
appliku servers hetzner-info   --team <team_path> --show locations
appliku servers hetzner-info   --team <team_path> --show server-types \
  --category "ARM" --location nbg1
appliku servers create-hetzner --team <team_path> \
  --location nbg1 --server-type cax11 \
  [--enable-backups] [--cluster <cluster_id>]
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

**Only an OpenSSH public key is accepted.** The value must be one line starting
with a key type (`ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-nistp256`, ...) followed
by base64 key data; a comment after it is kept. Anything else is rejected with
HTTP 400.

Send the `.pub` file, never the private key. These are commonly pasted here by
mistake and all of them are refused:

- a private key (`-----BEGIN ... PRIVATE KEY-----`, or base64 starting
  `b3BlbnNzaC1rZXktdjEA`)
- a PuTTY/RFC4716 export (`---- BEGIN SSH2 PUBLIC KEY ----`) — convert it with
  `ssh-keygen -i -f key.pub` first
- a fingerprint (`SHA256:...`), a git remote URL, or an access token

Keys are also imported automatically when Git credentials are saved in the
dashboard. Keys the provider serves that are not valid OpenSSH public keys are
skipped, reported as `skipped_public_keys`, and summarized in one email.

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
client.apps.create_from_github(
    "my-team", "owner/repository", name="myapp", branch="main", server=12
)
client.apps.create_from_gitlab(
    "my-team", "group/repository", name="myapp", branch="main", cluster=7
)
client.apps.create_from_custom_git(
    "my-team",
    "git@example.com:team/repository.git",
    name="myapp",
    branch="main",
    server=12,
    private_key=private_key_contents,
)
client.apps.update("my-team", app_id=42, branch="develop")
client.apps.delete("my-team", app_id=42)
client.apps.deploy("my-team", app_id=42)

# Config vars. get returns {"env_vars": [...]}; set takes a flat mapping.
vars = client.apps.get_config_vars("my-team", app_id=42)

# set MERGES: variables not named in the call are left untouched.
client.apps.set_config_vars("my-team", app_id=42, vars={"DEBUG": "false"})

# An empty ("" or None) value DELETES the variable rather than blanking it.
client.apps.set_config_vars("my-team", app_id=42, vars={"DEBUG": ""})  # deletes DEBUG
client.apps.delete_config_var("my-team", app_id=42, key="OLD_VAR")  # returns remaining vars

# Logs — get_logs takes a list of processes (None = all), works on any mode.
logs = client.apps.get_logs("my-team", app_id=42)  # all processes
logs = client.apps.get_logs("my-team", app_id=42, processes=["web", "celery"], tail=100)
# get_service_logs is a deprecated shim that delegates to get_logs.
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

# Hetzner Cloud provisioning. Requires the team to have a stored Hetzner Cloud
# token. Server types and locations are pulled live from Hetzner.
info = client.servers.get_hetzner_cloud_info("my-team")
client.servers.create_hetzner_cloud(
    "my-team",
    location="nbg1",
    server_type="cax11",
    hetzner_backups_enabled=False,
    cluster=None,
)
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
# All processes (default when no --process is given)
appliku apps logs --team my-team --app 42 --tail 200

# Specific processes
appliku apps logs --team my-team --app 42 --process web --process celery --tail 200
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

- **Create does not deploy**: Application creation starts initial configuration inspection only. Deploy in a separate command after setup is complete.
- **`apps logs` is the one logs command**: It works for both server-mode and cluster-mode apps and returns logs for one or more processes. It POSTs a request, then polls until logs are ready. (`apps service-logs` still exists as a deprecated alias for `apps logs -p <service>`.)
- **`--process` is repeatable and optional**: Pass it multiple times for multiple processes (`--process web --process celery`); omit it entirely to get logs for **all** of the app's processes.
- **Machine-readable output**: Add `--output json` to any list command when you need to parse IDs programmatically.
- **`APPLIKU_TOKEN` for CI**: Set this environment variable to avoid interactive login in automated contexts.
