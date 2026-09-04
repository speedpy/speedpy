"""A URLconf that mounts the hardened MCP consent screen for tests.

The project only mounts ``ConsentAuthorizationView`` when ``MCP_ENABLED``, and
that decision is made once at import — ``override_settings`` cannot re-run it. So
consent/CIMD HTTP tests point ``ROOT_URLCONF`` here. It reuses the full project
URLs (so ``base.html`` can resolve its named routes) and prepends the consent
view ahead of DOT's ``o/`` routes, exactly as ``project/urls.py`` does when MCP
is on.
"""

from django.urls import path

from project.urls import urlpatterns as project_urlpatterns
from speedpycom.api.oauth_consent import ConsentAuthorizationView

urlpatterns = [
    path("o/authorize/", ConsentAuthorizationView.as_view(), name="mcp_authorize"),
    *project_urlpatterns,
]
