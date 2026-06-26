# Production Readiness Checklist

This guide helps fork owners strip SpeedPy's demo and placeholder content before going to production. The canonical SpeedPy repo keeps these artifacts as teaching examples; your fork should remove or replace them.

**Two tools are available:**

- **This checklist** — for humans working through removal manually.
- **`/strip-demo` agent skill** — audit-first automation for AI coding agents.

**Quick audit:** Run `rg SPEEDPY_DEMO` to find all marked demo artifacts. The machine-readable manifest in `demo-content.json` is the authoritative list.

---

## Before You Start

- [ ] Create a feature branch: `git checkout -b strip-demo`
- [ ] Back up your database if it contains production data
- [ ] Determine your scenario:
  - **Fresh fork** (no production data): you can delete migrations and drop tables freely.
  - **Existing database**: you must write removal migrations or reset the DB before deleting model code.

---

## 1. Remove `demoapp/` (Product CRUD)

The `demoapp/` Django app provides a Product CRUD example at `/demo/products/`.

- [ ] Delete the `demoapp/` directory
- [ ] Delete `templates/demoapp/` (4 templates: product_list, product_form, product_detail, product_confirm_delete)
- [ ] Remove `"demoapp"` from `INSTALLED_APPS` in `project/settings.py`
- [ ] Remove `path("demo/", include("demoapp.urls"))` from `project/urls.py`
- [ ] **Existing DB only:** Drop the `demoapp_product` table or write a removal migration before deleting app code

---

## 2. Remove Product API

The read-only Product API at `/api/v1/products/` is a demo endpoint.

- [ ] Delete `mainapp/api/products.py`
- [ ] Remove `ProductListAPIView` and `ProductDetailAPIView` from `mainapp/api/__init__.py`
- [ ] Remove the product URL patterns from `project/api_urls.py`:
  - `path("v1/products/", ...)`
  - `path("v1/products/<uuid:pk>/", ...)`
  - The `from mainapp.api.products import ...` line
- [ ] Remove `"read:products"` scope from `OAUTH2_PROVIDER["SCOPES"]` in `project/settings.py`
- [ ] Remove the `products` tag from `SPECTACULAR_SETTINGS["TAGS"]` in `project/settings.py`
- [ ] Remove `"read:products"` from the OAuth2 flows in `SPECTACULAR_SETTINGS["APPEND_COMPONENTS"]`
- [ ] **Important:** Several shared tests use `/api/v1/products/` or import from `demoapp`. Move these tests to use your own domain endpoint before deleting the Product API:
  - `mainapp/tests/test_api_pagination.py`
  - `mainapp/tests/test_api_throttle.py`
  - `mainapp/tests/test_api_request_id.py`
  - `usermodel/tests/test_existing.py` (imports `demoapp.models.Product`, uses `read:products` scope)
  - `mainapp/tests/test_api_schema.py` (expects `listProducts`/`getProduct` operation IDs — remove them from `EXPECTED_OPERATION_IDS`)

---

## 3. Remove Demo Job Endpoint

The demo job endpoint at `/api/v1/jobs/demo/` and its Celery task are demo-only entry points. The `AsyncJob` model and `JobStatusView` are **reusable infrastructure** — keep them if your app needs async job tracking.

### Remove demo entry points (always):

- [ ] Remove `DemoJobCreateView` from `mainapp/api/jobs.py` (keep `JobStatusView`)
- [ ] Remove the `DemoJobCreateView` import from `project/api_urls.py`
- [ ] Remove `path("v1/jobs/demo/", ...)` from `project/api_urls.py`
- [ ] Remove `run_demo_job` from `mainapp/tasks/jobs.py` (keep the file for real tasks)
- [ ] Remove `run_demo_job` from `mainapp/tasks/__init__.py` (`__all__` and import)
- [ ] Delete `mainapp/tests/test_api_jobs.py` (or keep tests for JobStatusView if retaining the infrastructure)

### Optional — remove async job infrastructure entirely:

Only do this if your app has no background tasks that need status polling.

- [ ] Delete `mainapp/models/jobs.py` and remove `AsyncJob` from `mainapp/models/__init__.py`
- [ ] Delete `JobStatusView` from `mainapp/api/jobs.py` (or delete the file entirely)
- [ ] Remove `path("v1/jobs/<uuid:job_id>/", ...)` from `project/api_urls.py`
- [ ] Remove `"read:jobs"` and `"write:jobs"` from `OAUTH2_PROVIDER["SCOPES"]`
- [ ] Remove the `jobs` tag from `SPECTACULAR_SETTINGS["TAGS"]`
- [ ] Remove `"read:jobs"` and `"write:jobs"` from `SPECTACULAR_SETTINGS["APPEND_COMPONENTS"]` OAuth2 flows
- [ ] **Existing DB only:** Write a removal migration for the `mainapp_asyncjob` table

---

## 4. Remove DEMO_MODE

The `DEMO_MODE` flag shows hardcoded demo credentials on the login page.

- [ ] Remove `DEMO_MODE = env.bool(...)` from `project/settings.py`
- [ ] Remove the `demo_mode` function from `project/context_processors.py`
- [ ] Remove `"project.context_processors.demo_mode"` from `TEMPLATES` context processors in `project/settings.py`
- [ ] Remove the `{% if DEMO_MODE %}` block from `templates/account/login.html`

---

## 5. Remove Demo Deployment Config

- [ ] Delete `appliku_demo.yml` (keep `appliku.yml` for production)

---

## 6. Replace Placeholder Pages

These pages are functional placeholders — replace them with your own content rather than deleting them (the root URL must resolve).

- [ ] Replace `templates/mainapp/welcome.html` with your landing page
- [ ] Replace `templates/mainapp/pricing.html` with your pricing page (or remove the route if not needed)
- [ ] Replace `templates/mainapp/contact.html` with your contact page content

---

## 7. Clean Up SpeedPy UI Preview Demo Links

- [ ] Remove the "Demo App / CRUD Screens" section from `templates/mainapp/speedpyui_preview.html` (the section between `{# ---------- CRUD screens ---------- #}` and `{# ---------- Surfaces ---------- #}`)

---

## 8. Update Examples and Generated Code

- [ ] Remove product-specific subcommands from `examples/cli/speedpy_cli.py`
- [ ] Remove product-specific MCP tools from `examples/mcp_server/speedpy_mcp.py`
- [ ] Regenerate `examples/mcp_server/generated_tools.py` from the updated OpenAPI schema
- [ ] Update `examples/README.md` to remove product API references

---

## 9. Update Documentation

- [ ] Update `README.md` to remove `/api/v1/products/` and `read:products` references
- [ ] Update any AGENTS.md references to demo content

---

## 10. Verify

Run these checks to confirm all demo content is removed:

```bash
# Search for remaining demo markers (exclude guidance files that legitimately reference the marker)
rg SPEEDPY_DEMO --glob '!PRODUCTION_READY.md' --glob '!demo-content.json' --glob '!AGENTS.md' --glob '!README.md' --glob '!.claude/skills/strip-demo/*'

# Search for demo references
rg "demoapp" --type py --type html
rg "demo_product" --type py --type html
rg "/api/v1/products/" --type py
rg "run_demo_job" --type py
rg "/api/v1/jobs/demo/" --type py
rg "DEMO_MODE" --type py --type html

# Run Django checks
python manage.py check

# Run tests
python manage.py test

# Validate OpenAPI schema
python manage.py spectacular --file /tmp/speedpy-openapi.yaml --validate
```

All `SPEEDPY_DEMO` markers in source code, `demoapp` references, and demo endpoint references should be gone. The guidance files (`PRODUCTION_READY.md`, `demo-content.json`, `AGENTS.md`, `README.md`, and the `/strip-demo` skill) legitimately reference `SPEEDPY_DEMO` for documentation purposes and can be kept or removed at your discretion. Tests should pass. The OpenAPI schema should validate without the removed endpoints.
