# SpeedPy CLI & MCP Examples

Starter code for machine clients that authenticate against a SpeedPy project
and call the HTTP API.

## Prerequisites

1. A running SpeedPy instance (local or deployed).
2. Python 3.10+.
3. Install dependencies:

```bash
pip install httpx        # CLI only
pip install httpx mcp    # MCP server
```

## Authentication options

Both examples support two auth methods:

### Personal access token (PAT)

1. Log in to your SpeedPy instance.
2. Go to **Account → API Tokens** (`/accounts/tokens/`).
3. Create a token with the scopes you need (`read:profile`, `read:teams`, …).
4. Copy the token (shown once) and export it:

```bash
export SPEEDPY_API_URL=http://localhost:8000   # or SPEEDPY_BASE_URL
export SPEEDPY_TOKEN=spd_abc123...
```

### OAuth2 device flow

1. Register a device-flow OAuth2 application:

```bash
python manage.py create_oauth2_app "My CLI" --grant-type device-code
```

2. Note the **Client ID** from the output and export it:

```bash
export SPEEDPY_API_URL=http://localhost:8000   # or SPEEDPY_BASE_URL
export SPEEDPY_CLIENT_ID=<client_id>
```

3. When you run the CLI or MCP server, it will print a URL and code. Open the
   URL in your browser, enter the code, and approve the request.

## CLI example

```bash
cd examples/cli

# With PAT:
python speedpy_cli.py --token spd_... me
python speedpy_cli.py --token spd_... teams

# With device flow:
python speedpy_cli.py --client-id <CLIENT_ID> me

# With environment variables:
export SPEEDPY_TOKEN=spd_...
python speedpy_cli.py me
python speedpy_cli.py teams
```

### Available commands

| Command | Endpoint           | Description                                    |
|---------|--------------------|------------------------------------------------|
| `login` | (device flow)      | Authenticate and save credentials to config    |
| `me`    | `GET /api/v1/me/`  | Show your user profile                         |
| `teams` | `GET /api/v1/teams/` | List your teams                              |

### Config file

The CLI stores configuration in `~/.config/speedpy/config.json` (or
`$XDG_CONFIG_HOME/speedpy/config.json` if `XDG_CONFIG_HOME` is set).

The config file holds `base_url`, `client_id`, and `token`. After running
`login`, subsequent commands use the stored credentials automatically.

**Precedence** (highest to lowest):

1. CLI flags (`--base-url`, `--token`, `--client-id`)
2. Environment variables (`SPEEDPY_BASE_URL`, `SPEEDPY_TOKEN`, `SPEEDPY_CLIENT_ID`)
3. Config file (`~/.config/speedpy/config.json`)
4. Built-in defaults

### `login` command

Run `login` once to authenticate via device flow and persist your
credentials:

```bash
python speedpy_cli.py --client-id <CLIENT_ID> login
# or with a non-default server:
python speedpy_cli.py --base-url https://app.example.com --client-id <CLIENT_ID> login
```

The command opens a browser for approval, then stores the token, base URL,
and client ID in the config file. After that, `python speedpy_cli.py me`
works without any flags.

For CI, keep using `SPEEDPY_TOKEN` (a PAT) as an environment variable --
no login step needed.

### `--json` flag

Pass `--json` to any command to get machine-readable JSON output on
stdout:

```bash
python speedpy_cli.py --json me
python speedpy_cli.py --json teams
```

When `--json` is set, errors are also emitted as JSON:

```json
{"error": "Authentication failed. Check your token or run 'login'.", "exit_code": 3}
```

### Exit codes

| Code | Meaning                                  |
|------|------------------------------------------|
| 0    | Success                                  |
| 1    | General / unknown error                  |
| 2    | Config / usage error                     |
| 3    | Auth error (invalid/expired token)       |
| 4    | Forbidden (insufficient scopes)          |
| 5    | Not found                                |
| 6    | Validation / server error                |
| 7    | Network error (server unreachable)       |

## MCP server example

The MCP server exposes SpeedPy API endpoints as tools that AI assistants
(Claude, etc.) can call via the Model Context Protocol.

### Running

```bash
cd examples/mcp_server

# With PAT:
SPEEDPY_TOKEN=spd_... python speedpy_mcp.py

# With device flow (will prompt for browser auth on first tool call):
SPEEDPY_CLIENT_ID=<CLIENT_ID> python speedpy_mcp.py

# For development/testing with the MCP inspector:
mcp dev speedpy_mcp.py
```

### Available tools

| Tool                 | Endpoint                             | Scope          | Description                |
|----------------------|--------------------------------------|----------------|----------------------------|
| `get_current_user`   | `GET /api/v1/me/`                    | `read:profile` | Read current user profile  |
| `list_teams`         | `GET /api/v1/teams/`                 | `read:teams`   | List user's teams          |
| `list_team_members`  | `GET /api/v1/teams/{id}/members/`    | `read:teams`   | List members of a team     |

### Claude Desktop configuration

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "speedpy": {
      "command": "python",
      "args": ["/path/to/examples/mcp_server/speedpy_mcp.py"],
      "env": {
        "SPEEDPY_API_URL": "http://localhost:8000",
        "SPEEDPY_TOKEN": "spd_your_token_here"
      }
    }
  }
}
```

## Deployed environments

For production deployments, replace `http://localhost:8000` with your
production URL:

```bash
export SPEEDPY_API_URL=https://app.example.com
```

All auth flows work the same way — the device flow verification URL will
point to your production domain automatically.

## Distributing the CLI via Homebrew

Homebrew is the most popular way to distribute CLI tools on macOS (and Linux).
A Python CLI is shipped as a **Homebrew formula** in a custom **tap**
(Homebrew Cask is for GUI apps, not CLIs).

### 1. Make the CLI pip-installable

Add a `pyproject.toml` in `examples/cli/` (or at the project root if the CLI
ships with the main package):

```toml
[project]
name = "speedpy-cli"
version = "0.1.0"
description = "CLI client for the SpeedPy API"
requires-python = ">=3.10"
dependencies = ["httpx>=0.27"]

[project.scripts]
speedpy = "speedpy_cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Build a release tarball and publish to PyPI (or host it yourself):

```bash
cd examples/cli
pip install build twine
python -m build
twine upload dist/*
```

### 2. Create a Homebrew tap repository

Create a public GitHub repo named `homebrew-tap` under your org (e.g.
`speedpycom/homebrew-tap`). Homebrew resolves `brew tap speedpycom/tap` to
that repo automatically.

### 3. Write the formula

Create `Formula/speedpy-cli.rb` in the tap repo:

```ruby
class SpeedpyCli < Formula
  include Language::Python::Virtualenv

  desc "CLI client for the SpeedPy API"
  homepage "https://github.com/speedpycom/speedpy"
  url "https://files.pythonhosted.org/packages/source/s/speedpy-cli/speedpy_cli-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SHA256_OF_TARBALL"
  license "MIT"

  depends_on "python@3.12"

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/source/h/httpx/httpx-0.28.1.tar.gz"
    sha256 "REPLACE_WITH_HTTPX_SHA256"
  end

  # Add additional resources for httpx's dependencies (httpcore, etc.)
  # Generate them automatically with: brew update-python-resources speedpy-cli

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage:", shell_output("#{bin}/speedpy --help")
  end
end
```

Generate the `resource` blocks automatically instead of writing them by hand:

```bash
brew update-python-resources speedpy-cli
```

### 4. Compute the tarball SHA-256

```bash
curl -sL https://files.pythonhosted.org/packages/source/s/speedpy-cli/speedpy_cli-0.1.0.tar.gz \
  | shasum -a 256
```

### 5. Users install with two commands

```bash
brew tap speedpycom/tap
brew install speedpy-cli
```

After that `speedpy me` and `speedpy teams` work system-wide.

### 6. Updating

When you release a new version:

1. Publish the new tarball to PyPI.
2. Update `url` and `sha256` in the formula.
3. Push to the tap repo — users pick it up on their next `brew upgrade`.

### Self-hosted alternative (no PyPI)

If you prefer not to publish to PyPI, host the tarball on GitHub Releases and
point the formula `url` there:

```ruby
url "https://github.com/speedpycom/speedpy/releases/download/cli-v0.1.0/speedpy_cli-0.1.0.tar.gz"
```

The rest of the formula stays the same.

## Generating MCP tools from OpenAPI

Instead of hand-maintaining MCP tool wrappers, you can generate them from
the OpenAPI schema:

```bash
# 1. Generate the schema
cd speedpy
uv run python manage.py spectacular --file /tmp/speedpy-openapi.yaml --validate

# 2. Generate MCP tools (writes examples/mcp_server/generated_tools.py)
uv run python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml \
    -o examples/mcp_server/generated_tools.py
```

The generated file is checked in so the starter example works without
running the generator first.

### Filtering

```bash
# Only specific tags:
uv run python examples/mcp_server/generate_mcp_tools.py schema.yaml --tags teams,products

# Only specific operations:
uv run python examples/mcp_server/generate_mcp_tools.py schema.yaml \
    --operations listTeams,getTeam,listTeamMembers

# Show skipped write operations:
uv run python examples/mcp_server/generate_mcp_tools.py schema.yaml --unsafe
```

Only `GET` endpoints are generated. Write operations (POST, PUT, PATCH,
DELETE) require manual implementation; use `--unsafe` to see which ones
were skipped.

### CI freshness check

Add a step to your CI pipeline to verify the generated tools match the
current schema:

```bash
uv run python manage.py spectacular --file /tmp/schema.yaml --validate
uv run python examples/mcp_server/generate_mcp_tools.py /tmp/schema.yaml \
    -o examples/mcp_server/generated_tools.py --check
```

This exits with code 1 if the checked-in file is stale.

### Using generated tools

Import the generated module alongside the main MCP server to register
the tools automatically:

```python
# In your MCP server entry point
from speedpy_mcp import mcp
import generated_tools  # noqa: F401 — registers tools on import

if __name__ == "__main__":
    mcp.run()
```

## Extending

These examples are intentionally minimal. To add your own commands/tools:

1. Add API endpoints in `mainapp/api/<group>.py` following the conventions
   in `AGENTS.md`.
2. Add a new CLI subcommand in `speedpy_cli.py` using `api_get()`.
3. Add a new `@mcp.tool()` function in `speedpy_mcp.py` using `_api_get()`,
   or regenerate tools from the OpenAPI schema (see `mcp_server/generate_mcp_tools.py`).

The generated OpenAPI schema at `/api/schema/` is the source of truth for
all available endpoints, request/response shapes, and auth requirements.
