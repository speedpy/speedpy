#!/usr/bin/env python3
"""
SpeedPy CLI — minimal example for machine clients.

Authenticates via OAuth2 device flow or a personal access token (PAT),
then calls /api/v1/me/ and /api/v1/teams/.

Usage:
    # Device flow (interactive, opens browser):
    python speedpy_cli.py --base-url http://localhost:8000 --client-id <CLIENT_ID> me
    python speedpy_cli.py --base-url http://localhost:8000 --client-id <CLIENT_ID> teams

    # Personal access token:
    python speedpy_cli.py --base-url http://localhost:8000 --token spd_<HEX> me
    python speedpy_cli.py --base-url http://localhost:8000 --token spd_<HEX> teams

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
# Auth helpers
# ---------------------------------------------------------------------------

def device_flow_authenticate(
    base_url: str, client_id: str, scope: str = "read:profile read:teams"
) -> str:
    """Run the OAuth2 device authorization flow and return an access token."""
    device_url = f"{base_url}/o/device-authorization/"
    token_url = f"{base_url}/o/token/"

    resp = httpx.post(
        device_url,
        data={"client_id": client_id, "scope": scope},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()

    verification_uri = data.get("verification_uri_complete") or data["verification_uri"]
    user_code = data["user_code"]
    device_code = data["device_code"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 600)

    print(f"\n  Open this URL in your browser:\n    {verification_uri}\n")
    print(f"  Enter code: {user_code}\n")

    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass  # headless environments

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        token_resp = httpx.post(
            token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code == 200:
            token_data = token_resp.json()
            print("  Authenticated successfully.\n")
            return token_data["access_token"]

        error = token_resp.json().get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 1
            continue
        else:
            print(f"  Device flow error: {error}", file=sys.stderr)
            sys.exit(1)

    print("  Device code expired. Please try again.", file=sys.stderr)
    sys.exit(1)


def get_token(args: argparse.Namespace) -> str:
    """Resolve an access token from CLI args or environment."""
    token = args.token or os.environ.get("SPEEDPY_TOKEN", "")
    if token:
        return token

    client_id = args.client_id or os.environ.get("SPEEDPY_CLIENT_ID", "")
    if not client_id:
        print(
            "Provide --token / SPEEDPY_TOKEN or --client-id / SPEEDPY_CLIENT_ID "
            "for device flow.",
            file=sys.stderr,
        )
        sys.exit(1)

    return device_flow_authenticate(args.base_url, client_id)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(base_url: str, path: str, token: str) -> dict:
    """GET an API endpoint and return parsed JSON."""
    url = f"{base_url}{path}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        print("Authentication failed. Check your token or re-authenticate.", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_me(args: argparse.Namespace) -> None:
    """Show current user profile."""
    token = get_token(args)
    data = api_get(args.base_url, "/api/v1/me/", token)
    print(json.dumps(data, indent=2))


def cmd_teams(args: argparse.Namespace) -> None:
    """List teams the authenticated user belongs to."""
    token = get_token(args)
    data = api_get(args.base_url, "/api/v1/teams/", token)
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpeedPy CLI — example client for the SpeedPy API",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SPEEDPY_BASE_URL", "http://localhost:8000"),
        help="SpeedPy server URL (default: $SPEEDPY_BASE_URL or http://localhost:8000)",
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

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("me", help="Show current user profile")
    sub.add_parser("teams", help="List your teams")

    args = parser.parse_args()
    commands = {"me": cmd_me, "teams": cmd_teams}
    commands[args.command](args)


if __name__ == "__main__":
    main()
