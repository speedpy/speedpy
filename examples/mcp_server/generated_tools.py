"""
Auto-generated MCP tool wrappers from SpeedPy OpenAPI schema.

DO NOT EDIT — regenerate with:
    python examples/mcp_server/generate_mcp_tools.py <schema> -o <this-file>

Depends on ``speedpy_mcp.mcp`` (FastMCP instance) and ``speedpy_mcp._api_get``.
"""

from __future__ import annotations

from speedpy_mcp import _api_get, mcp

@mcp.tool()
def get_integration_manifest() -> dict:
    """Machine-readable integration manifest
    
    Returns public metadata about this SpeedPy installation: API schema URL,
    auth methods, scopes, endpoints, and capabilities. No authentication
    required. Agents, CLIs, and MCP servers should use this endpoint to
    discover available features and URLs.
    
    Endpoint: GET /api/v1/health/manifest/
    Requires scope: read:profile
    """
    return _api_get("/api/v1/health/manifest/")


@mcp.tool()
def get_current_user() -> dict:
    """Get the authenticated user
    
    Return the profile of the currently authenticated user. Requires the
    `read:profile` scope.
    
    Endpoint: GET /api/v1/me/
    Requires scope: read:profile
    """
    return _api_get("/api/v1/me/")


@mcp.tool()
def list_products(page: int | None = None) -> dict:
    """List products
    
    Return a paginated list of all products. Requires the `read:products`
    scope.
    
    Args:
        page: A page number within the paginated result set. (optional)
    
    Endpoint: GET /api/v1/products/
    Requires scope: read:profile
    """
    params = {}
    if page is not None:
        params['page'] = page
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/api/v1/products/"
    return _api_get(f"{url}?{qs}") if qs else _api_get(url)


@mcp.tool()
def get_product(id: str) -> dict:
    """Get a product
    
    Return a single product by its primary key. Requires the `read:products`
    scope.
    
    Args:
        id: 
    
    Endpoint: GET /api/v1/products/{id}/
    Requires scope: read:profile
    """
    return _api_get(f"/api/v1/products/{id}/")


@mcp.tool()
def list_teams(page: int | None = None) -> dict:
    """List teams for the authenticated user
    
    Return all active teams the authenticated user is a member of. Expired
    memberships are excluded. Requires the `read:teams` scope. Returns 404
    if the teams feature is disabled.
    
    Args:
        page: A page number within the paginated result set. (optional)
    
    Endpoint: GET /api/v1/teams/
    Requires scope: read:profile
    """
    params = {}
    if page is not None:
        params['page'] = page
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/api/v1/teams/"
    return _api_get(f"{url}?{qs}") if qs else _api_get(url)


@mcp.tool()
def get_team(team_id: str) -> dict:
    """Get a team
    
    Return details of a single team including its member count. The caller
    must be an active member of the team. Requires the `read:teams` scope.
    
    Args:
        team_id: 
    
    Endpoint: GET /api/v1/teams/{team_id}/
    Requires scope: read:profile
    """
    return _api_get(f"/api/v1/teams/{team_id}/")


@mcp.tool()
def list_team_members(team_id: str, page: int | None = None) -> dict:
    """List team members
    
    Return all members of the specified team, ordered by role then join
    date. The caller must be an active member. Requires the `read:teams`
    scope.
    
    Args:
        team_id: 
        page: A page number within the paginated result set. (optional)
    
    Endpoint: GET /api/v1/teams/{team_id}/members/
    Requires scope: read:profile
    """
    params = {}
    if page is not None:
        params['page'] = page
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/teams/{team_id}/members/"
    return _api_get(f"{url}?{qs}") if qs else _api_get(url)


@mcp.tool()
def list_team_webhook_endpoints(team_id: str) -> dict:
    """List webhook endpoints for a team
    
    Return a paginated list of webhook endpoints belonging to the team.
    Requires team membership and the `read:webhooks` scope.
    
    Args:
        team_id: 
    
    Endpoint: GET /api/v1/teams/{team_id}/webhooks/
    Requires scope: read:profile
    """
    return _api_get(f"/api/v1/teams/{team_id}/webhooks/")


@mcp.tool()
def get_team_webhook_endpoint(team_id: str, webhook_id: str) -> dict:
    """Get a webhook endpoint
    
    Return a single webhook endpoint by ID. Requires team membership and the
    `read:webhooks` scope.
    
    Args:
        team_id: 
        webhook_id: 
    
    Endpoint: GET /api/v1/teams/{team_id}/webhooks/{webhook_id}/
    Requires scope: read:profile
    """
    return _api_get(f"/api/v1/teams/{team_id}/webhooks/{webhook_id}/")


@mcp.tool()
def list_team_webhook_deliveries(team_id: str, webhook_id: str, page: int | None = None) -> dict:
    """List deliveries for a webhook endpoint
    
    Return a paginated list of delivery attempts for the specified webhook
    endpoint, ordered by most recent first. Requires the `read:webhooks`
    scope.
    
    Args:
        team_id: 
        webhook_id: 
        page: A page number within the paginated result set. (optional)
    
    Endpoint: GET /api/v1/teams/{team_id}/webhooks/{webhook_id}/deliveries/
    Requires scope: read:profile
    """
    params = {}
    if page is not None:
        params['page'] = page
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/teams/{team_id}/webhooks/{webhook_id}/deliveries/"
    return _api_get(f"{url}?{qs}") if qs else _api_get(url)


@mcp.tool()
def get_team_webhook_delivery(delivery_id: int, team_id: str, webhook_id: str) -> dict:
    """Get a webhook delivery
    
    Return full details of a delivery attempt, including the request payload
    and response body. Requires the `read:webhooks` scope.
    
    Args:
        delivery_id: 
        team_id: 
        webhook_id: 
    
    Endpoint: GET /api/v1/teams/{team_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/
    Requires scope: read:profile
    """
    return _api_get(f"/api/v1/teams/{team_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/")


@mcp.tool()
def list_user_webhook_endpoints(page: int | None = None) -> dict:
    """List webhook endpoints across all user's teams
    
    Return a combined list of webhook endpoints from every active team the
    authenticated user belongs to. Read-only. Requires the `read:webhooks`
    scope.
    
    Args:
        page: A page number within the paginated result set. (optional)
    
    Endpoint: GET /api/v1/webhooks/
    Requires scope: read:profile
    """
    params = {}
    if page is not None:
        params['page'] = page
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/api/v1/webhooks/"
    return _api_get(f"{url}?{qs}") if qs else _api_get(url)
