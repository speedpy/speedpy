---
name: add-integration-api
description: >-
  Step-by-step recipe for adding a new integration API resource to SpeedPy:
  model, serializer, views, scopes, URLs, tests, schema, and optional webhook
  event. Use when adding a new /api/v1/ endpoint.
disable-model-invocation: true
---

# /add-integration-api — Add a new API resource

Numbered recipe for adding an integration API endpoint to SpeedPy. Follow every step in order; skip steps marked *(optional)*.

**References:** read-only resource `mainapp/api/products.py` | team-scoped CRUD `mainapp/api/teams.py` | webhooks `mainapp/api/webhooks.py` | permissions `speedpycom/api/permissions.py` | URLs `project/api_urls.py` | webhook events `mainapp/webhooks/events.py` | schema test `mainapp/tests/test_api_schema.py`

## Recipe

1. **Model** — Locate or create in `mainapp/models/<domain>.py`. Inherit `BaseModel` (UUID pk, timestamps) or `TeamModel` (adds `team` FK). Export from `mainapp/models/__init__.py`. Run `python manage.py makemigrations && python manage.py migrate`.

2. **Serializer** — Add in `mainapp/api/<domain>.py`. Use `ModelSerializer` with explicit `fields` + `read_only_fields` for model-backed endpoints (see `products.py`). Use plain `Serializer` only for deliberately shaped responses not backed 1:1 by a model (see `teams.py` `TeamSerializer`). Add a separate write serializer when create/update fields differ from the response.

3. **Views** — Class-based views in same file. `ListAPIView`/`RetrieveAPIView` for read-only; `APIView` for custom logic. Set `permission_classes = [HasScope]` and `required_scopes = ["read:<domain>"]` (or `write:<domain>`). Team-scoped: use `_get_membership(request.user, team_id)` pattern. Decorate every method with `@extend_schema(tags=[...], operation_id="...", summary="...", description="...", responses={...})`. Add `@idempotent` on POST/PATCH where replay safety matters.

4. **Re-export** — Add view imports to `mainapp/api/__init__.py`.

5. **URLs** — Register in `project/api_urls.py`. User-global: `/api/v1/<domain>/`. Team-scoped: `/api/v1/teams/<uuid:team_id>/<domain>/`.

6. **Scopes & tags** — Add `read:<domain>`/`write:<domain>` to: `OAUTH2_PROVIDER["SCOPES"]` in `project/settings.py`, `SCOPE_CHOICES` in `usermodel/forms.py`, and `SPECTACULAR_SETTINGS["APPEND_COMPONENTS"]` OAuth2 scopes. Add new tag to `SPECTACULAR_SETTINGS["TAGS"]` if introducing a new resource group.

7. **Tests** — Create `mainapp/tests/test_api_<domain>.py`: anonymous rejection (401/403), authenticated happy path, response field contract (exact key set), tenant isolation (if team-scoped), role boundaries, schema `operationId` presence. Add operation IDs to `EXPECTED_OPERATION_IDS` in `test_api_schema.py`. Run: `python manage.py test mainapp.tests.test_api_<domain> mainapp.tests.test_api_schema`.

8. **Schema validation** — `python manage.py spectacular --validate --fail-on-warn`. Fix warnings before proceeding.

9. **Webhook event** *(optional)* — Add constant to `mainapp/webhooks/events.py` (`resource.action` convention), update `ALL` and `CHOICES`. Fire from view or signal.

10. **CLI & MCP examples** — Add CLI subcommand in `examples/cli/speedpy_cli.py` (`api_get()`). Add `@mcp.tool()` in `examples/mcp_server/speedpy_mcp.py` (`_api_get()`).

11. **Verify** — All tests pass. Schema validates. `@extend_schema` on every endpoint. Scopes in settings, forms, schema. Tags in `SPECTACULAR_SETTINGS["TAGS"]`. Tenant isolation enforced if team-scoped.

## Checklist (copy-paste for tickets)

```
- [ ] Model in `mainapp/models/<domain>.py` (BaseModel or TeamModel)
- [ ] Migration created and applied
- [ ] Serializer + views in `mainapp/api/<domain>.py`
- [ ] Views re-exported from `mainapp/api/__init__.py`
- [ ] URLs in `project/api_urls.py`
- [ ] Scopes in settings.py, forms.py, schema components
- [ ] Tag added to `SPECTACULAR_SETTINGS["TAGS"]` (if new resource group)
- [ ] `HasScope` + `required_scopes` on views
- [ ] `@extend_schema` on every view method
- [ ] Tests: anon, happy path, field contract, isolation, roles, schema
- [ ] `EXPECTED_OPERATION_IDS` updated in test_api_schema.py
- [ ] `python manage.py spectacular --validate --fail-on-warn` passes
- [ ] Webhook event registered (if applicable)
- [ ] CLI + MCP examples updated
```
