#!/usr/bin/env python3
"""
SpeedPy MCP Server — minimal Model Context Protocol server example.

Exposes SpeedPy API endpoints as MCP tools that AI assistants can call.

Tools provided:
  - get_current_user: Read the authenticated user's profile (/api/v1/me/)
  - list_teams:       List the user's teams (/api/v1/teams/)
  - list_team_members: List members of a specific team (/api/v1/teams/{id}/members/)

Auth:
  Supports PAT (personal access token) or OAuth2 device flow.
  Set environment variables before starting:

    export SPEEDPY_API_URL=http://localhost:8000   # or SPEEDPY_BASE_URL
    export SPEEDPY_TOKEN=spd_<hex>                 # PAT auth
    # — OR —
    export SPEEDPY_CLIENT_ID=<client_id>           # device flow (interactive)

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

BASE_URL = (
    os.environ.get("SPEEDPY_API_URL")
    or os.environ.get("SPEEDPY_BASE_URL")
    or "http://localhost:8000"
).rstrip("/")

TOKEN = os.environ.get("SPEEDPY_TOKEN", "")
CLIENT_ID = os.environ.get("SPEEDPY_CLIENT_ID", "")

mcp = FastMCP(
    "SpeedPy",
    instructions=(
        "SpeedPy API server. Use get_current_user to read the current user, "
        "list_teams to see available teams, and list_team_members for team "
        "member details."
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

    return ""


def _api_get(path: str) -> dict:
    """Authenticated GET against the SpeedPy API.

    Returns the JSON response on success, or a structured error dict on
    failure (missing config, auth errors, network issues, non-JSON bodies).
    """
    token = _get_token()
    if not token:
        return {
            "error": "missing_credentials",
            "message": (
                "Set SPEEDPY_TOKEN (PAT) or SPEEDPY_CLIENT_ID (device flow) "
                "before starting the MCP server."
            ),
        }

    url = f"{BASE_URL}{path}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.ConnectError:
        return {
            "error": "connection_error",
            "message": f"Could not connect to {BASE_URL}. Is the server running?",
        }
    except httpx.HTTPError as exc:
        return {
            "error": "network_error",
            "message": str(exc),
        }

    if resp.status_code == 401:
        global _cached_token
        _cached_token = ""
        return {
            "error": "authentication_failed",
            "message": "Token may be expired or revoked.",
            "status": 401,
        }
    if resp.status_code == 403:
        return {
            "error": "forbidden",
            "message": "Token may lack required scopes.",
            "status": 403,
        }
    if resp.status_code == 404:
        return {
            "error": "not_found",
            "message": f"Not found: {path}",
            "status": 404,
        }

    if resp.status_code >= 400:
        return {
            "error": "api_error",
            "message": f"HTTP {resp.status_code}",
            "status": resp.status_code,
        }

    content_type = resp.headers.get("content-type", "")
    if "json" not in content_type:
        return {
            "error": "unexpected_content_type",
            "message": f"Expected JSON, got {content_type}",
        }

    return resp.json()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_current_user() -> dict:
    """Get the authenticated user's profile (email, name, teams).

    Requires scope: read:profile
    Endpoint: GET /api/v1/me/
    """
    return _api_get("/api/v1/me/")


@mcp.tool()
def list_teams(page: int | None = None) -> dict:
    """List all teams the authenticated user belongs to.

    Returns a paginated response with ``count``, ``next``, ``previous``,
    and ``results`` fields when DRF pagination is enabled, or a plain
    list otherwise.

    Args:
        page: Page number for paginated results (optional).

    Requires scope: read:teams
    Endpoint: GET /api/v1/teams/
    """
    path = "/api/v1/teams/"
    if page is not None:
        path = f"{path}?page={page}"
    return _api_get(path)


@mcp.tool()
def list_team_members(team_id: str, page: int | None = None) -> dict:
    """List members of a specific team.

    Args:
        team_id: UUID of the team whose members to list.
        page: Page number for paginated results (optional).

    Returns a paginated response with ``count``, ``next``, ``previous``,
    and ``results`` fields when DRF pagination is enabled, or a plain
    list otherwise.

    Requires scope: read:teams
    Endpoint: GET /api/v1/teams/{team_id}/members/
    """
    path = f"/api/v1/teams/{team_id}/members/"
    if page is not None:
        path = f"{path}?page={page}"
    return _api_get(path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
