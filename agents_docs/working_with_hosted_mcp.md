# Working with a hosted remote MCP endpoint

SpeedPy ships **without** a hosted MCP endpoint, on purpose. Most projects never
need an AI agent to connect to them over OAuth, and the feature drags in a
production OAuth surface (audience-bound tokens, a consent screen, host
isolation, a discovery plane) that costs every reader tokens they do not want.
The boilerplate already carries the OAuth *substrate* — django-oauth-toolkit
(DOT), PKCE, scopes, `HasScope`, PAT auth, DCR, `create_oauth2_app` — so a
hosted MCP is an **extension of what is already here**, not a new stack.

This document is the recipe for adding it. It is written from a production build
that ships it (withfeedback.com — 17 tools, listed in the ChatGPT and Claude
directories) and from two `codex` reviews of the backport plan. (withfeedback's hosted endpoint
and one-click connection from ChatGPT and Claude are live; the public directory
*listings* in those stores are a separate, still-open task — do not assume a
directory listing follows automatically from a working connector.)

> **Status of this document (read first).**
> This is a **design draft + checklist**, not yet a frozen set of copy-paste
> templates. The generic pieces described in §3 are being ported into
> `speedpycom/` under a plan (see `specs/` if present, or the withfeedback
> `specs/plans/hosted-mcp.md`). Until that port lands and withfeedback is
> rewired onto it, treat the code sketches here as **shape, not final API** —
> the module paths and signatures are the target, and the invariants in §2 are
> already firm. The verification checklist in §7 is usable today.

Read it before designing anything MCP-shaped. The order of the sections is the
order of the decisions.

---

## 0. What a hosted remote MCP actually is here

An AI agent (Claude, ChatGPT, Cursor, Kimi) is given **one URL** and nothing
else. From it, the agent discovers how to authenticate, the user approves a
named scope in the browser, and the connection works. Concretely:

- **One POST endpoint** at `https://mcp.<domain>/mcp`, answering
  `application/json` for every non-notification response (a notification gets an
  empty `202`), speaking both eras of the MCP protocol (the modern stateless
  `2026-07-28` shape and the older `initialize` handshake). No SSE, no ASGI, no
  new runtime.
- **OAuth 2.1 authorization-code + PKCE**, with the token **bound to the URL**
  as its RFC 8707 audience. No cookies, no PAT, no session on this endpoint.
- **Discovery** via RFC 8414 (authorization-server metadata) and RFC 9728
  (protected-resource metadata), plus **CIMD** (Client ID Metadata Documents) so
  the big directories can connect without dynamic registration.
- A **consent screen** that names the client by the host of its `client_id` URL
  and states exactly what the grant covers.

DOT 3.4 supplies the OAuth machinery. This feature adds the transport, the
audience rules, the consent hardening, host isolation, the tool catalogue, and
the tool handlers.

---

## 1. Decide your resource shape (tenancy) before anything else

The **URL is the OAuth `resource`; the token's audience is the boundary.** The
shape of that URL is the first decision and it threads through every later file,
so get it right first. Three common shapes:

| Shape | URL grammar | Use when |
|---|---|---|
| **Single-tenant** | `…/mcp` only | the token's user *is* the tenant (no teams). |
| **Team** | `…/mcp` (all my teams) and `…/mcp/t/{team}` (one team) | team multi-tenancy (e.g. uptimefor.me). |
| **Team + project** | add `…/mcp/t/{team}/p/{project}` | a second level under a team (e.g. withfeedback). |

Rules that hold for every shape:

- **Matching is exact.** A token minted for `…/mcp` must **not** satisfy
  `…/mcp/t/acme`. (DOT's default is a permissive prefix match — the shipped
  audience rule replaces it with equality.)
- **An unbound token is refused.** A token with no `resource` was never consented
  to a tenant, so the MCP endpoint fails it closed. (The REST API keeps accepting
  unbound tokens — that difference is deliberate.)
- **Slugs, never ids.** Resolved server-side; membership and role are re-checked
  on every call against the token's user, never inferred from the path.
- **A scoped URL removes the bound arguments from the advertised schema**, so an
  agent on `…/p/widgets` cannot name a different project.

The canonical `…/mcp` grant ("all my teams") is evaluated **at call time**, not
frozen at consent — a team joined later is included, a team left is not. Anyone
wanting a fixed boundary uses the scoped URL.

---

## 2. The invariants you must not break

These are firm regardless of your app. They are **shipped as code** (§3), not
left to your handlers — but you must not undo them:

1. **Exact audience match + refuse unbound token** on the MCP endpoint. And the
   issuance side must be just as strict, because DOT by itself is not: an
   authorization/token request must carry **exactly one** `resource`, it must be
   **one of your configured MCP resource shapes** (not an arbitrary absolute
   URL), the team/project it names must be **validated for the user at
   authorization time**, only **connector scopes** may be granted (never
   `admin`), and a token exchange must be **refused if it tries to attach a
   `resource` the authorization grant did not have**. DOT will otherwise accept
   repeated resources, foreign absolute URLs, and a grant→token resource upgrade.
2. **Fail-closed consent.** The consent screen names the client by the **host of
   its `client_id` URL**, not by its self-asserted `client_name` (a CIMD client
   can claim any name). It must **block**, not merely display, an unknown,
   repeated, or foreign resource and any non-connector scope. *(The current
   withfeedback reference view displays these rather than blocking; the port must
   harden it — see §3.)*
3. **Resource-aware re-prompt.** Approving a client for one resource must not
   silently grant it another. DOT's skip compares user+app+scopes, not the
   resource — the shipped consent view overrides that.
4. **Host isolation.** The MCP endpoint answers only on the `mcp.` host; the app
   host does not serve MCP, and the MCP host does not serve app pages. The
   allowlist is deny-by-default: it must reject `/`, broad prefixes, and any
   OAuth/account/API/static path.
5. **`SITE_URL` is not the MCP host.** Enforced by a deploy check that must
   compare **hostnames** — a same-host, different-scheme/port spelling must not
   slip through and take the app host off the air. *(The withfeedback reference
   check currently compares normalized URL strings; the port must switch it to a
   hostname comparison.)*
6. **Confused-deputy defense.** For a scoped resource, the bound team/project is
   filled from the URL and the endpoint **refuses a caller-supplied override** of
   those arguments.
7. **Authorization ordering.** Scope **preflight → resource binding →
   authoritative re-check**, in that order. The scope preflight runs *before*
   membership so an insufficient-scope call returns a `403` naming the exact
   scope. This is an intentional exception to "membership first" — keep it.
8. **CIMD requires the custom consent screen.** Never enable `CIMD_ENABLED`
   without the hardened consent view (invariant 2). They ship as one unit.
9. **Descriptions describe, never instruct.** Anthropic rejects a tool whose
   description tells the model how to behave, pulls in instructions, or promotes
   anything. Keep tool text purely descriptive.

---

## 3. What the boilerplate ships vs what you write

**The port will add (as code) the pure core and every security invariant to
`speedpycom/api/`.** These modules **do not exist in `speedpycom/` yet** — the
paths and APIs below are the target the port implements; until it lands, the
working reference is the withfeedback code cited in §8. Rows marked *(new)* are
not in the withfeedback build either; they are fresh design the port introduces.

| Shipped | Module | What it is |
|---|---|---|
| Audience rules | `mcp_audience.py` | RFC 8707 exact-match + refuse-unbound. |
| Resource codec | `mcp_resource.py` | Parse/build/canonicalize a resource URL (no DB). You subclass it with your grammar. |
| Host isolation | `mcp_host.py` | Middleware gated on `MCP_ENABLED`, deny-by-default allowlist. |
| Deploy checks | `checks.py` | Base-URL shape; host ≠ `SITE_URL` (hostname compare). |
| Scope evaluation | `scopes.py` (`ScopeEvaluator`) | Pure token-scope check, shared with `HasScope`. |
| OAuth validator | `oauth_validator.py` | The CIMD public-downgrade apparatus (one-click ChatGPT/Claude). Parametrized cache namespace; pinned to DOT `<4.0` with parity tests. |
| Transport base | `mcp.py` | JSON-RPC framing, dual-era negotiation, origin check, RFC 6750/9728 challenge shapes, error taxonomy. Driven by the interfaces in §3a. |
| Metadata view | `mcp_metadata.py` | RFC 9728 protected-resource document, narrowed to your real shapes. |
| Catalogue protocol | `mcp_catalogue.py` | `Tool` dataclass + `tools/list` + `securitySchemes` derivation. |
| Call framework | `mcp_calls.py` | `ToolError`, `McpContext`, dispatch/validation, cursor codec, **the confused-deputy refusal**, **the authorization ordering** (all present in the withfeedback build). *(new)* **audit + throttle invocation** and **a fail-closed exception mapper** — the withfeedback transport dispatches directly with neither today, and the boilerplate audit middleware only covers `/api/`, so these are new design the port must add. |
| Consent guards | `oauth_consent.py` + a base `authorize.html` | Fail-closed + resource-aware re-prompt (invariants 2, 3). You `{% extends %}` the base and supply labels. |

**You write (the recipe — genuine app choices):**

1. **Scopes** — add your domain scopes to `OAUTH2_PROVIDER["SCOPES"]`.
2. **Resource grammar** — a `ResourceCodec` subclass + the matching URL routes
   (transport + RFC 9728 metadata).
3. **`ResourcePolicy`** — the lookup callbacks: resolve a slug → tenant for the
   token's user, and refuse a caller override of bound arguments.
4. **Tool catalogue rows** — your `TOOLS`: name, title, *descriptive* text,
   `input_schema`, one `scope` each, `read_only`/annotations.
5. **Handlers** — each calls **your own services**, not the REST views, and
   records `interface=MCP` **where the service tracks attribution** (see §5).
6. **`authorize_call` callbacks** — membership → role → billing/feature. The
   *ordering and the authoritative re-check are core*; only these decisions are
   yours.
7. **Consent labels** (`_resource_label`) and the **connect UI**.
8. **Audit storage** and the **throttle rate/key policy** (the *invocation* is
   shipped; where it lands and the limits are yours).

### 3a. The interfaces the shipped transport expects

Your project supplies: a `ResourceCodec` (+ `ResourcePolicy` lookups), the
catalogue + dispatch, a `ScopeEvaluator` binding, an exception→tool-error mapper
(the default is fail-closed), server metadata (name, instructions, icon), an
audit hook, and a throttle hook.

### 3b. The single-tenant default is deny-all

The boilerplate default resolver exposes **no tools** until you install a
catalogue and an authorization policy. A permissive no-op default would be an
unsafe connector out of the box — so an un-configured MCP endpoint grants
nothing.

---

## 4. Turn on the wiring (once the port has landed)

These steps assume the §3 modules exist in `speedpycom/`. Until the port lands,
they describe the target configuration, not something you can switch on today.

1. **Dependencies.** DOT must be `>=3.4.1,<4.0` (the boilerplate default pin is
   `>=3.3.0` — the MCP feature raises it and adds the `<4.0` ceiling the CIMD
   code needs). `pyjwt[crypto]` is already a direct dependency; the CIMD
   validator itself only calls `jwt.get_unverified_header` (no cryptography, so
   base `PyJWT` would suffice for *that* use) — keep the `[crypto]` extra because
   other parts of the app rely on it, but do not justify it by the CIMD code.
2. **Settings.** Set `MCP_ENABLED=True` and `MCP_BASE_URL=https://mcp.<domain>`
   (a bare origin — its own host, **not** `SITE_URL`). Ship the hardened
   `OAUTH2_PROVIDER` flag block (RFC 9700 gates, `CIMD_ENABLED`, exact resource
   validator, `iss`), repointing `OAUTH2_VALIDATOR_CLASS` and
   `RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR` at the `speedpycom` modules.
3. **Middleware.** Put the host-isolation middleware **above WhiteNoise**.
4. **URLs.** Mount DOT route-by-route (base + management + oidc), **excluding**
   DOT's aggregate metadata and DCR url lists; mount the custom consent first;
   put RFC 8414 metadata at the **issuer/app** host root and RFC 9728 metadata on
   the **MCP** host (they live on different hosts — see the checklist).
5. **Both DCR doors stay shut** and are tested off: DOT's
   `OAUTH2_PROVIDER["DCR_ENABLED"]` **and** the boilerplate's top-level
   `DCR_ENABLED` (which defaults to `DEBUG`).
6. **Register the connector client** in your release script:
   `create_oauth2_app "<name> connector" --grant-type authorization-code …` with the
   Claude/ChatGPT callback URIs plus the RFC 8252 loopback. Note: `--scopes`
   only **prints** the scopes; it does not store or restrict them, so the scope
   subset is documentation, not enforcement.
7. **DNS + host.** Provision `mcp.<domain>`, add it to `ALLOWED_HOSTS`, keep
   `SITE_URL` explicitly set and different.

### 4a. The DOT 3.3 → 3.4 upgrade is a data event, not a version bump

DOT 3.4 adds `oauth2_provider` migrations 0015–0022 (inside the pip package —
you run them as shipped, you cannot regenerate them):

- `0015` backfills a checksum on **every** refresh token (batches of 1,000) and
  makes the column non-null + changes refresh-token uniqueness;
- `0018` adds the resource columns audience binding needs;
- `0020` widens the unique, indexed `client_id` and adds `cimd_expires_at`;
- `0022` adds an index on `RefreshToken.token_family`.

Therefore: **measure your token-table sizes and rehearse on a data copy**; deploy
**with no mixed versions** (after `0015`, a DOT 3.3 worker can no longer mint
refresh tokens); keep a backup/restore point. On small OAuth tables this runs
fast — but prove it, do not assume it.

**Migration hygiene, generally:** applied migrations are immutable. A boilerplate
sync **adds** normal or merge migrations; it does not squash as part of syncing.
Squashing is a separate, per-repo, reviewed operation over a settled graph — and
only ever for an exclusively upstream-owned app.

---

## 5. `interface=MCP` attribution — a per-handler decision

The point of MCP handlers calling your **services** (not your REST views) is
honest attribution: an approval made by an agent should be recorded as an MCP
action, not an API call. But this is not mechanical:

- Apply `interface=MCP`/`source=MCP` to a handler **only where its authoritative
  service records interface/source**. Do not force it on read-only handlers, or
  on writes whose service uses a different attribution mechanism.
- If your service layer hardcodes `source="api"` today, adding MCP attribution is
  a **service refactor**, sometimes with a migration (e.g. adding an `MCP` choice
  to a `trigger`/`interface` field). Plan that before writing handlers.

---

## 6. Store submission notes

Both directories reject a server that gets these wrong:

- Every tool needs a `title` and `readOnlyHint`/`destructiveHint`.
- ChatGPT reads per-tool `securitySchemes` to know a tool needs OAuth.
- Tool descriptions must be descriptive only (invariant 9).
- Submitting to Anthropic requires a Claude Team/Enterprise org.
- Add any directory-verification well-known paths (e.g. the OpenAI apps
  challenge) to the host allowlist — as settings, not hardcoded.

---

## 7. Definition of done — the verification checklist

Run this whole list before calling a connector wired. It is designed to catch a
mis-wired connector, not just a smoke test.

**OAuth flow**
- Full authorization-code + **S256** PKCE: discovery → consent → code → token.
- The `resource` **survives the consent form** and is copied onto **both** the
  access and refresh tokens; a refresh preserves it.
- Changed-resource consent **re-prompts**; a blank/invalid consent **fails closed**.

**Resource-binding — the negative cases** (a normal resource surviving is not
enough; these are where a mis-wired connector leaks):
- authorization with **no** `resource`, then a token exchange that tries to
  **add** one → refused.
- **repeated** `resource` parameters → refused.
- a **foreign or malformed-but-absolute** resource URL → refused.
- a **nonexistent or unauthorized** scoped resource at authorization time →
  refused (membership/object validated before consent completes).
- a **non-connector scope** (e.g. `admin`) requested for the connector → refused.
- a refresh that tries to **narrow or change** the resource/scope → refused.

**Credential refusal** — all of these are refused on `/mcp`:
- revoked, expired, malformed, device-grant, session-cookie, PAT, **unbound**,
  and **wrong-resource** tokens.

**Discovery on the correct host**
- RFC 8414 authorization-server metadata answers on the **issuer/app host**.
- RFC 9728 protected-resource metadata answers on the **MCP host**.
- Each **404s on the wrong host.**

**Host isolation (both directions)**
- On the **MCP host**, `/`, `/o/`, `/accounts/`, `/api/`, and `/static/` all
  **404** (the app is not reachable there).
- On the **app host**, every `/mcp…` route **404s** (MCP is not reachable there).

**Catalogue** — for **every** row, not just one:
- the handler exists; the schema reflects the bound (removed) arguments;
  read/write annotations are accurate; and the declared scope is not just
  *registered* but **matches end to end** — catalogue scope = the scope the
  preflight `403` names = the scope the authoritative handler enforces. Where you
  promise REST parity, check the role × scope × resource grid.
- every **attributable write** records `interface/source=MCP` (not merely a
  generic request-audit line).

**Tenancy**
- cross-team/project ids are refused; a caller override of a fixed argument is
  refused; inactive objects, expired membership, each role, billing state, and
  feature gate all behave correctly.

**Throttle + audit**
- real throttle exhaustion returns `429` + `Retry-After`;
- audit records success, tool error, scope failure, invalid token, and internal
  exception — and **never logs secrets or raw bearer tokens.**

**Protocol** — concretely, not just "both eras work":
- modern: a **missing or mismatched** `MCP-Protocol-Version`/`Mcp-Method`/
  `Mcp-Name` header → `400`; an **unsupported version** → `400` with
  `data.supported`; an **unknown method** → `404`.
- legacy: `initialize` requests are accepted **without** the modern headers.
- notifications → empty **`202`**; `GET`/`DELETE` → **`405`**.
- malformed JSON-RPC and the DNS-rebinding **origin** check behave.

**Both DCR doors closed** — the project `/o/register/` and DOT's
registration/management routes.

**Migrations** — measured row counts; non-null checksum validated; indexes
present; refresh rotation/replay regression; rollback rehearsed.

**Deploy** — `makemigrations --check` clean; both system checks pass; host ≠
`SITE_URL`.

**Live client** — a real Claude/ChatGPT connection against staging, not only the
Django test client.

---

## 8. Reference

The production implementation is withfeedback.com: `mainapp/api/mcp.py`,
`mainapp/oauth.py`, `mainapp/services/mcp_*.py`, `mainapp/views/oauth.py`,
`mainapp/middleware.py`, `project/settings.py` (the `OAUTH2_PROVIDER` block), and
`specs/plans/hosted-mcp.md`. When the `speedpycom` port lands, this document's
code sketches are replaced by the shipped module APIs.
