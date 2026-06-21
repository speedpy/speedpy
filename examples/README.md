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
export SPEEDPY_BASE_URL=http://localhost:8000
export SPEEDPY_TOKEN=spd_abc123...
```

### OAuth2 device flow

1. Register a device-flow OAuth2 application:

```bash
python manage.py create_oauth2_app "My CLI" --grant-type device-code
```

2. Note the **Client ID** from the output and export it:

```bash
export SPEEDPY_BASE_URL=http://localhost:8000
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

| Command | Endpoint           | Description              |
|---------|--------------------|--------------------------|
| `me`    | `GET /api/v1/me/`  | Show your user profile   |
| `teams` | `GET /api/v1/teams/` | List your teams        |

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

| Tool          | Endpoint                      | Description                |
|---------------|-------------------------------|----------------------------|
| `get_profile` | `GET /api/v1/me/`             | Read current user profile  |
| `list_teams`  | `GET /api/v1/teams/`          | List user's teams          |
| `get_team`    | `GET /api/v1/teams/{id}/`     | Get a specific team        |

### Claude Desktop configuration

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "speedpy": {
      "command": "python",
      "args": ["/path/to/examples/mcp_server/speedpy_mcp.py"],
      "env": {
        "SPEEDPY_BASE_URL": "http://localhost:8000",
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
export SPEEDPY_BASE_URL=https://app.example.com
```

All auth flows work the same way — the device flow verification URL will
point to your production domain automatically.

## Extending

These examples are intentionally minimal. To add your own commands/tools:

1. Add API endpoints in `mainapp/api/<group>.py` following the conventions
   in `AGENTS.md`.
2. Add a new CLI subcommand in `speedpy_cli.py` using `api_get()`.
3. Add a new `@mcp.tool()` function in `speedpy_mcp.py` using `_api_get()`.

The generated OpenAPI schema at `/api/schema/` is the source of truth for
all available endpoints, request/response shapes, and auth requirements.
