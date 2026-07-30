---
name: strip-demo
description: >-
  Audit-first workflow for removing SpeedPy demo/placeholder content from a
  fork before production. Reads the demo-content.json manifest, searches for
  SPEEDPY_DEMO markers, produces a removal plan, and waits for confirmation
  before making any changes.
disable-model-invocation: true
---

# /strip-demo — Strip demo content for production

Audit-first workflow for turning a SpeedPy fork into a clean production app skeleton. This skill reads the manifest and markers, produces a plan, and requires explicit confirmation before editing or deleting anything.

## Prerequisites

Read these files before starting:

- `AGENTS.md` / `AGENTS-local.md` — project conventions and mode-specific commands
- `PRODUCTION_READY.md` — human checklist (the source of truth for removal steps)
- `demo-content.json` — machine-readable manifest of all demo artifacts

## Workflow

### Phase 1 — Audit (read-only, always safe)

1. **Parse the manifest.** Read `demo-content.json` and list every artifact by category.

2. **Scan for markers.** Run `rg SPEEDPY_DEMO` across the project. Cross-reference with the manifest to confirm every marker is accounted for.

3. **Check path existence.** For each artifact in the manifest, verify whether its paths exist in the current working tree. Note any already-removed items.

4. **Detect database state.** Determine if this is a fresh clone (no production data) or an existing database:
   - If `demoapp/migrations/` exists and migrations have been applied, warn about data migration needs.
   - Ask the user to confirm their scenario.

5. **Identify test dependencies.** Check which test files import from `demoapp` or reference demo API endpoints. List these as items that need migration to non-demo endpoints.

6. **Present the removal plan.** Organize findings into sections matching `PRODUCTION_READY.md`:
   - Items to **delete** (`safe_remove`)
   - Items to **review** before deciding (`review`)
   - Items to **replace** with fork-owner content (`replace`)
   - Test files that need endpoint migration
   - Database actions needed (if existing DB)

**Stop here and ask for confirmation.** Do not proceed to Phase 2 without explicit user approval.

### Phase 2 — Execute (destructive, only after confirmation)

Only perform removals that the user explicitly approved. For each approved section:

7. **Remove `demoapp/`.** Delete the directory, templates, INSTALLED_APPS entry, and URL include.

8. **Remove Product API.** Delete `mainapp/api/products.py`, remove imports/exports from `__init__.py` and `api_urls.py`, remove scopes and tags from settings.

9. **Remove demo job entry points.** Remove `DemoJobCreateView`, `run_demo_job` task, and their URL/import/export references. Keep `AsyncJob` and `JobStatusView` unless the user explicitly opted to remove them.

10. **Remove DEMO_MODE.** Remove the setting, context processor, template context processor reference, and template conditional blocks.

11. **Remove `appliku_demo.yml`.**

12. **Clean up SpeedPy UI preview.** Remove the "Demo App / CRUD Screens" section from the preview template.

13. **Clean up examples and docs.** Remove product-specific CLI/MCP references. Note that `generated_tools.py` should be regenerated.

14. **Update README.** Remove demo API references.

### Phase 3 — Verify

15. **Run verification checks:**

```bash
# No remaining demo markers (exclude guidance files)
rg SPEEDPY_DEMO --glob '!PRODUCTION_READY.md' --glob '!demo-content.json' --glob '!AGENTS.md' --glob '!README.md' --glob '!.claude/skills/strip-demo/*'

# No remaining demo references
rg "demoapp" --type py --type html
rg "demo_product" --type py --type html
rg "/api/v1/products/" --type py
rg "run_demo_job" --type py
rg "/api/v1/jobs/demo/" --type py
rg "DEMO_MODE" --type py --type html

# Django checks
python manage.py check

# Tests pass
python manage.py test

# Schema validates
python manage.py spectacular --file /tmp/speedpy-openapi.yaml --validate
```

16. **Report results.** Summarize what was removed, what was kept, and any remaining references that need manual attention (e.g., placeholder pages that need replacement content, generated files that need regeneration).

## Rules

- **Never delete files not listed in the manifest** unless the user explicitly confirms.
- **Never delete user-created files** just because they contain words like "demo" or "example".
- **Always present the plan first** — no edits before confirmation.
- **Respect the `review` action** — ask the user before removing items marked `review` in the manifest (e.g., AsyncJob infrastructure, example CLI/MCP code).
- **Placeholder pages are `replace`, not `delete`** — the root URL must resolve. Tell the user to provide replacement content.
- **Test dependencies must be migrated first** — do not delete the Product API if pagination/throttle/request-ID tests still depend on it without providing a migration path.
- **Database-aware** — if an existing DB is detected, include migration commands in the plan and warn about data loss.
