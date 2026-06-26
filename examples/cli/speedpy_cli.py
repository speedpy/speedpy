#!/usr/bin/env python3
"""
SpeedPy CLI — minimal example for machine clients.

Authenticates via OAuth2 device flow or a personal access token (PAT),
then calls /api/v1/me/ and /api/v1/teams/.

Usage:
    # First-time setup (interactive, opens browser):
    python speedpy_cli.py --base-url http://localhost:8000 --client-id <CLIENT_ID> login

    # After login, credentials are stored — no flags needed:
    python speedpy_cli.py me
    python speedpy_cli.py teams

    # Personal access token (good for CI):
    python speedpy_cli.py --base-url http://localhost:8000 --token spd_<HEX> me

    # JSON output for scripting:
    python speedpy_cli.py --json me

    # Environment variables work too:
    export SPEEDPY_BASE_URL=http://localhost:8000
    export SPEEDPY_TOKEN=spd_abc123...
    python speedpy_cli.py me

Setup:
    pip install httpx

    # To create a device-flow OAuth2 app:
    python manage.py create_oauth2_app "SpeedPy CLI" --grant-type device-code

    # To create a PAT, visit /accounts/tokens/ in the web UI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser

import httpx


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_AUTH_ERROR = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5
EXIT_VALIDATION_ERROR = 6
EXIT_NETWORK_ERROR = 7


# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

def _config_dir() -> str:
    """Return the SpeedPy config directory, respecting XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "speedpy")


def _config_path() -> str:
    """Return the path to the config JSON file."""
    return os.path.join(_config_dir(), "config.json")


def load_config() -> dict:
    """Load config from disk. Returns empty dict if file doesn't exist."""
    path = _config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict) -> None:
    """Write config dict to disk as JSON."""
    directory = _config_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = _config_path()
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _output(data, *, json_mode: bool) -> None:
    """Print data as JSON or pretty-printed JSON (human-readable)."""
    if json_mode:
        print(json.dumps(data))
    else:
        print(json.dumps(data, indent=2))


def _output_error(message: str, *, json_mode: bool, code: int) -> None:
    """Print an error message and exit with the given code."""
    if json_mode:
        print(json.dumps({"error": message, "exit_code": code}))
    else:
        print(message, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def device_flow_authenticate(
    base_url: str,
    client_id: str,
    scope: str = "read:profile read:teams",
    *,
    json_mode: bool = False,
) -> str:
    """Run the OAuth2 device authorization flow and return an access token."""
    device_url = f"{base_url}/o/device-authorization/"
    token_url = f"{base_url}/o/token/"

    try:
        resp = httpx.post(
            device_url,
            data={"client_id": client_id, "scope": scope},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
    except httpx.RequestError:
        _output_error(
            f"Network error: cannot reach {base_url}",
            json_mode=json_mode,
            code=EXIT_NETWORK_ERROR,
        )
    except httpx.HTTPStatusError as exc:
        _output_error(
            f"Device authorization failed: HTTP {exc.response.status_code}",
            json_mode=json_mode,
            code=EXIT_AUTH_ERROR,
        )

    data = resp.json()

    verification_uri = data.get("verification_uri_complete") or data["verification_uri"]
    user_code = data["user_code"]
    device_code = data["device_code"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 600)

    if json_mode:
        print(json.dumps({
            "action": "device_flow_authorize",
            "verification_uri": verification_uri,
            "user_code": user_code,
        }), flush=True)
    else:
        print(f"\n  Open this URL in your browser:\n    {verification_uri}\n")
        print(f"  Enter code: {user_code}\n")

    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass  # headless environments

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            token_resp = httpx.post(
                token_url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.RequestError:
            _output_error(
                f"Network error: cannot reach {base_url}",
                json_mode=json_mode,
                code=EXIT_NETWORK_ERROR,
            )

        if token_resp.status_code == 200:
            token_data = token_resp.json()
            if not json_mode:
                print("  Authenticated successfully.\n")
            return token_data["access_token"]

        try:
            error = token_resp.json().get("error", "")
        except (ValueError, KeyError):
            _output_error(
                f"Token endpoint returned HTTP {token_resp.status_code} (non-JSON)",
                json_mode=json_mode,
                code=EXIT_VALIDATION_ERROR,
            )
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 1
            continue
        else:
            _output_error(
                f"Device flow error: {error}",
                json_mode=json_mode,
                code=EXIT_AUTH_ERROR,
            )

    _output_error(
        "Device code expired. Please try again.",
        json_mode=json_mode,
        code=EXIT_AUTH_ERROR,
    )
    return ""  # unreachable, _output_error calls sys.exit


def get_token(args: argparse.Namespace) -> str:
    """Resolve an access token from CLI flags, env vars, or config file."""
    json_mode = getattr(args, "json", False)

    # Precedence: CLI flag > env var > config file
    token = args.token or os.environ.get("SPEEDPY_TOKEN", "")
    if token:
        return token

    cfg = load_config()
    if cfg.get("token"):
        return cfg["token"]

    # No stored token — try device flow
    client_id = args.client_id or os.environ.get("SPEEDPY_CLIENT_ID", "") or cfg.get("client_id", "")
    if not client_id:
        _output_error(
            "Provide --token / SPEEDPY_TOKEN, run 'login', or provide "
            "--client-id / SPEEDPY_CLIENT_ID for device flow.",
            json_mode=json_mode,
            code=EXIT_AUTH_ERROR,
        )

    return device_flow_authenticate(args.base_url, client_id, json_mode=json_mode)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(base_url: str, path: str, token: str, *, json_mode: bool = False) -> dict:
    """GET an API endpoint and return parsed JSON."""
    url = f"{base_url}{path}"
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.RequestError:
        _output_error(
            f"Network error: cannot reach {base_url}",
            json_mode=json_mode,
            code=EXIT_NETWORK_ERROR,
        )
    except httpx.HTTPError as exc:
        _output_error(
            f"HTTP error: {exc}",
            json_mode=json_mode,
            code=EXIT_GENERAL_ERROR,
        )

    if resp.status_code == 401:
        _output_error(
            "Authentication failed. Check your token or run 'login'.",
            json_mode=json_mode,
            code=EXIT_AUTH_ERROR,
        )
    if resp.status_code == 403:
        _output_error(
            "Forbidden. Insufficient scopes or permissions.",
            json_mode=json_mode,
            code=EXIT_FORBIDDEN,
        )
    if resp.status_code == 404:
        _output_error(
            f"Not found: {path}",
            json_mode=json_mode,
            code=EXIT_NOT_FOUND,
        )
    if resp.status_code >= 400:
        _output_error(
            f"Server error: HTTP {resp.status_code}",
            json_mode=json_mode,
            code=EXIT_VALIDATION_ERROR,
        )

    return resp.json()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_login(args: argparse.Namespace) -> None:
    """Authenticate via device flow and save credentials to config."""
    json_mode = getattr(args, "json", False)
    cfg = load_config()
    client_id = args.client_id or os.environ.get("SPEEDPY_CLIENT_ID", "") or cfg.get("client_id", "")
    if not client_id:
        _output_error(
            "Provide --client-id or set SPEEDPY_CLIENT_ID for device flow login.",
            json_mode=json_mode,
            code=EXIT_CONFIG_ERROR,
        )

    token = device_flow_authenticate(args.base_url, client_id, json_mode=json_mode)

    cfg = load_config()
    cfg["base_url"] = args.base_url
    cfg["client_id"] = client_id
    cfg["token"] = token
    save_config(cfg)

    if json_mode:
        _output({"status": "ok", "config_path": _config_path()}, json_mode=True)
    else:
        print(f"  Token saved to {_config_path()}")


def cmd_me(args: argparse.Namespace) -> None:
    """Show current user profile."""
    json_mode = getattr(args, "json", False)
    token = get_token(args)
    data = api_get(args.base_url, "/api/v1/me/", token, json_mode=json_mode)
    _output(data, json_mode=json_mode)


def cmd_teams(args: argparse.Namespace) -> None:
    """List teams the authenticated user belongs to."""
    json_mode = getattr(args, "json", False)
    token = get_token(args)
    data = api_get(args.base_url, "/api/v1/teams/", token, json_mode=json_mode)

    if json_mode:
        _output(data, json_mode=True)
        return

    results = data.get("results", data) if isinstance(data, dict) else data
    if isinstance(results, list):
        for team in results:
            print(f"  {team['name']}  (id: {team['id']})")
        if not results:
            print("  No teams found.")
    else:
        print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _resolve_base_url(explicit_base_url: str | None) -> str:
    """Resolve base_url with flags > env > config > default precedence."""
    if explicit_base_url is not None:
        return explicit_base_url
    env = os.environ.get("SPEEDPY_BASE_URL", "")
    if env:
        return env
    cfg = load_config()
    if cfg.get("base_url"):
        return cfg["base_url"]
    return "http://localhost:8000"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpeedPy CLI — example client for the SpeedPy API",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="SpeedPy server URL (default: $SPEEDPY_BASE_URL or config or http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Personal access token (spd_...) or OAuth2 access token",
    )
    parser.add_argument(
        "--client-id",
        default="",
        help="OAuth2 client ID for device flow authentication",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON (for scripting/CI)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Authenticate via device flow and save credentials")
    sub.add_parser("me", help="Show current user profile")
    sub.add_parser("teams", help="List your teams")

    args = parser.parse_args()

    # Apply flags > env > config > default precedence for base_url
    args.base_url = _resolve_base_url(args.base_url)

    commands = {"login": cmd_login, "me": cmd_me, "teams": cmd_teams}
    commands[args.command](args)


if __name__ == "__main__":
    main()
