#!/usr/bin/env python3
"""
SpeedPy MCP Server — minimal Model Context Protocol server example.

Exposes SpeedPy API endpoints as MCP tools that AI assistants can call.

Tools provided:
  - get_profile: Read the authenticated user's profile (/api/v1/me/)
  - list_teams:  List the user's teams (/api/v1/teams/)
  - get_team:    Get details for a specific team (/api/v1/teams/{id}/)

Auth:
  Supports PAT (personal access token) or OAuth2 device flow.
  Set environment variables before starting:

    export SPEEDPY_BASE_URL=http://localhost:8000
    export SPEEDPY_TOKEN=spd_<hex>          # PAT auth
    # — OR —
    export SPEEDPY_CLIENT_ID=<client_id>    # device flow (interactive)

Setup:
    pip install mcp httpx

    # Register a device-flow OAuth2 app (if not using PAT):
    python manage.py create_oauth2_app "SpeedPy MCP" --grant-type device-code

Run:
    python speedpy_mcp.py

    # Or via the MCP CLI for testing:
    mcp dev speedpy_mcp.py
"""

from __future__ import annotations

import os
import sys
import time
import webbrowser

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("SPEEDPY_BASE_URL", "http://localhost:8000")
TOKEN = os.environ.get("SPEEDPY_TOKEN", "")
CLIENT_ID = os.environ.get("SPEEDPY_CLIENT_ID", "")

mcp = FastMCP(
    "SpeedPy",
    instructions=(
        "SpeedPy API server. Use get_profile to read the current user, "
        "list_teams to see available teams, and get_team for team details."
    ),
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_cached_token: str = ""


def _device_flow(client_id: str, scope: str = "read:profile read:teams") -> str:
    """Run OAuth2 device flow and return an access token."""
    resp = httpx.post(
        f"{BASE_URL}/o/device-authorization/",
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

    print(
        f"\n  Authenticate at: {verification_uri}\n  Code: {user_code}\n",
        file=sys.stderr,
    )
    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        token_resp = httpx.post(
            f"{BASE_URL}/o/token/",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code == 200:
            print("  Authenticated.\n", file=sys.stderr)
            return token_resp.json()["access_token"]

        error = token_resp.json().get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 1
            continue
        else:
            raise RuntimeError(f"Device flow error: {error}")

    raise RuntimeError("Device code expired.")


def _get_token() -> str:
    """Return a valid access token (PAT or device flow)."""
    global _cached_token
    if _cached_token:
        return _cached_token

    if TOKEN:
        _cached_token = TOKEN
        return _cached_token

    if CLIENT_ID:
        _cached_token = _device_flow(CLIENT_ID)
        return _cached_token

    raise RuntimeError(
        "Set SPEEDPY_TOKEN (PAT) or SPEEDPY_CLIENT_ID (device flow) "
        "before starting the MCP server."
    )


def _api_get(path: str) -> dict:
    """Authenticated GET against the SpeedPy API."""
    token = _get_token()
    resp = httpx.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 401:
        global _cached_token
        _cached_token = ""
        return {"error": "Authentication failed. Token may be expired or revoked."}
    if resp.status_code == 403:
        return {"error": "Forbidden. Token may lack required scopes."}
    if resp.status_code == 404:
        return {"error": f"Not found: {path}"}
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_profile() -> dict:
    """Get the authenticated user's profile (email, name, teams)."""
    return _api_get("/api/v1/me/")


@mcp.tool()
def list_teams() -> dict:
    """List all teams the authenticated user belongs to."""
    return _api_get("/api/v1/teams/")


@mcp.tool()
def get_team(team_id: str) -> dict:
    """Get details and members for a specific team.

    Args:
        team_id: UUID of the team to retrieve.
    """
    return _api_get(f"/api/v1/teams/{team_id}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
