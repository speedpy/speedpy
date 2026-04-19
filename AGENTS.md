# CLAUDE.md

This file provides guidance to AI Coding Agents when working with code in this repository.

## Project Overview

SpeedPy Standard is a Django-based web application starter template featuring a single-app architecture with custom user
authentication, Celery for background tasks, and Tailwind CSS for styling. The project follows a Docker-first
development approach.

## Development Commands

### Docker Commands (Primary Development Method)

All development should be done through Docker containers:

```bash
# Initialize the project (first time setup)
make init

# Run development server
docker compose up -d web
# Database operations
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate
# tailwind
docker compose run web npm run tailwind:build # to build once
docker compose run web npm run tailwind:watch # to start watch & build

# General command runner
docker compose run --rm web <command>

# Access shell
docker compose run --rm web bash
```

### NPM Commands

```bash
npm run tailwind:build  # Build Tailwind CSS
npm run tailwind:watch  # Watch Tailwind CSS changes
```

### Testing and Quality

The project includes Django's testing framework. Run tests with:

```bash
docker compose run --rm web python manage.py test
```

## Architecture

### Apps Structure

- **`mainapp`**: Primary application containing all business logic
    - Models organized in separate files under `mainapp/models/`
    - Views organized in separate files under `mainapp/views/`
    - Forms organized in separate files under `mainapp/forms/`
    - All models/views/forms must be imported in respective `__init__.py` files
- **`usermodel`**: Dedicated app for custom User model with email-based authentication
- **`speedpycom`**: Contains management commands (e.g., `generate_tailwind_directories`)

### Key Architectural Patterns

- Single Django app architecture (mainapp + usermodel)
- Class-based views preferred over function-based views
- Foreign key references use string notation: `'mainapp.ModelName'`
- Templates stored in root `templates/` directory, organized by app
- Package-style organization for models, views, and forms (separate files in directories)

### Technology Stack

- **Backend**: Django 6.0.3 with PostgreSQL
- **Frontend**: Tailwind CSS 3.4.0 with Alpine.js
- **Authentication**: django-allauth with custom email-based user model
- **Background Tasks**: Celery with Redis
- **Deployment**: Docker with Docker Compose

### Database Configuration

- Supports PostgreSQL (recommended), SQLite (development), and MySQL
- Database collation automatically configured per engine
- Uses django-environ for environment variable management

### Styling and Static Files

- Tailwind CSS with custom configuration
- SpeedPy UI design system (see below) — do NOT introduce Flowbite, DaisyUI, or other component libraries
- Static files served via WhiteNoise
- CSS compiled from `static/mainapp/input.css` to `static/mainapp/styles.css`

## SpeedPy UI Design System

The project uses an in-house design system called **SpeedPy UI**. A live catalogue of every
primitive lives at `/speedpyui-preview/` — open it before designing new pages or components
to see what's already available and reuse the existing look.

### Design tokens (colors, surfaces, shadows)

Colors and surfaces are declared as CSS variables in `static/mainapp/input.css` and wired into
Tailwind via `tailwind.config.js`. They automatically swap between light and dark mode, so in
templates you write **one** utility name per slot — never pair a light utility with a `dark:`
variant for token-driven colors.

Use these Tailwind utilities (bound to the tokens):

- Background: `bg-background` (app chrome), `bg-background-paper` (cards, modals, raised surfaces)
- Text: `text-fg` (primary), `text-fg-secondary` (muted / helper text)
- Borders: `border-divider`
- Brand / status: `bg-primary`, `text-primary`, `bg-secondary`, `bg-success`, `bg-info`,
  `bg-warning`, `bg-error` — each has `-light`, `-dark`, and `-contrast` variants
  (e.g. `text-primary-contrast` for text placed on a `bg-primary` surface)
- Numbered brand scale (`bg-primary-50` … `bg-primary-900`) exists for backwards compatibility
  but prefer the token-driven `primary` / `primary-dark` / `primary-light` names
- Neutrals `neutral-50`…`neutral-950` are static (same value in both modes) — use them only
  for things that must NOT follow the theme
- Elevation: `shadow-speedpyui-1 | -3 | -8 | -12 | -16 | -24` (use `-16` for cards, `-24`
  for modals). Do not add raw `shadow-lg` / `shadow-md` — they look off against the palette.

**Do not** write `bg-white`, `bg-gray-*`, `text-gray-*`, `text-black` for surfaces or
body/heading copy. Those bypass the theme and will not follow dark mode. The only exceptions
are utility text like `text-primary-contrast` on brand-filled buttons, or `neutral-*` where
a deliberately static color is needed.

### Dark mode

- Tailwind is configured with `darkMode: 'class'` and the `.dark` class is toggled on
  `<html>` by the inline script at the top of `templates/base.html`.
- User preference is stored in `localStorage['theme-preference']` with values
  `'light' | 'dark' | 'auto'` (default `'auto'` follows `prefers-color-scheme`). The nav bar
  includes a three-state theme toggle (`#theme-toggle`) wired in `static/mainapp/index.js`.
- Because colors come from CSS variables, **most new markup does not need `dark:` variants**.
  Only add `dark:` prefixes for things the token system doesn't cover (e.g. legacy
  `neutral-*` scales on third-party widgets).

### Component classes

Re-use these `@layer components` classes from `input.css` rather than hand-rolling new styles:

Open `/speedpyui-preview/` before adding or changing UI. It shows rendered examples and
copyable snippets for the current SpeedPy UI primitives.

Full-page demos that are meant to teach boilerplate users should live in `demoapp`, not
`mainapp`. Keep them conventional and easy to copy: model in `demoapp/models.py`, form in
`demoapp/forms.py`, generic class-based views in `demoapp/views.py`, routes in
`demoapp/urls.py`, and templates under `templates/demoapp/`. The Product CRUD demo at
`/demo/products/` is the canonical example for `ListView`, `CreateView`, `UpdateView`,
`DetailView`, and `DeleteView` screens using SpeedPy UI classes. Do not seed demo rows in migrations; expose
an explicit POST action, like the Product "Generate demo products" button, and only show it
when the demo table is empty.

**Buttons** — compose three axes: variant + color + size. Size defaults to `btn-md`.

```html
<button class="btn btn-contained btn-primary">Save</button>
<button class="btn btn-outlined btn-error btn-sm">Delete</button>
<a href="..." class="btn btn-text btn-secondary btn-lg">Learn more</a>
```

- Variants: `btn-contained` (filled), `btn-outlined` (border only), `btn-text` (ghost)
- Colors: `btn-primary`, `btn-secondary`, `btn-success`, `btn-info`, `btn-warning`,
  `btn-error`, `btn-inherit`
- Sizes: `btn-sm`, `btn-md` (default), `btn-lg`

**Form inputs** — `input-outlined`, `textarea-outlined`, `select-outlined`, `checkbox`,
`radio`, `switch` (with `.switch-track` and `.switch-thumb`). Pair with
`.form-field`, `.input-label`, `.input-helper`, `.input-error`, `.input-error-text` for
layout. `crispy-tailwind` field templates already emit these classes, so crispy forms pick
them up automatically. Use `/speedpyui-preview/FormView` as the canonical working example
of a Django `FormView` styled by crispy forms.

**Typography and page layout** — use these for regular page structure instead of repeating
long wrapper and heading utilities:

```html
<main class="section">
  <div class="page-container">
    <div class="section-header">
      <p class="eyebrow">Overview</p>
      <h1 class="h1">Dashboard</h1>
      <p class="lead">Summary text.</p>
    </div>
  </div>
</main>
```

- Layout: `section`, `section-paper`, `page-container`, `page-header`, `section-header`
- Page headers with top-level actions must use the action layout:
  `page-header-actions` with `page-header-main` for copy and `page-header-buttons` for
  actions. Top-level action buttons (Add, Create, Delete, Generate, etc.) belong on the
  right on desktop, never centered under the title.
- Typography: `h1`, `h2`, `h3`, `h4`, `h5`, `eyebrow`, `lead`
- Icons and avatars: `media-icon`, `avatar-sm`, `avatar-xs`

**Cards, status, lists, and tables** — use these for dashboard panels, account pages, status
rows, and simple data display:

```html
<div class="card">
  <div class="card-header"><h2 class="h3">Title</h2></div>
  <div class="card-body">Content</div>
  <div class="card-footer">Actions</div>
</div>

<span class="badge badge-success">Verified</span>
<div class="alert alert-warning">Review this setting.</div>
```

- Cards: `card`, `card-header`, `card-body`, `card-footer`
- Lists: `list-group`, `list-group-item`
- Badges: `badge`, `badge-lg`, `badge-primary`, `badge-secondary`, `badge-success`,
  `badge-info`, `badge-warning`, `badge-error`
- Alerts: `alert`, `alert-primary`, `alert-secondary`, `alert-success`, `alert-info`,
  `alert-warning`, `alert-error`, `alert-danger`, `alert-light`, `alert-neutral`
- Tables: `table`, `table-hover`, `table-striped`, `table-sm`
- Pagination: use `pagination`, `pagination-summary`, `pagination-list`,
  `pagination-link`, `pagination-link-active`, `pagination-link-disabled`, and
  `pagination-ellipsis` for list footers. Prefer numbered, elided pagination with a
  result count summary over Previous/Next-only controls.

**Account and sidebar navigation** — use these for settings pages and dashboard sidebar
links rather than repeating link classes:

```html
<a href="..." class="account-nav-link account-nav-link-active">Profile</a>
<a href="..." class="sidebar-link sidebar-link-active">
  <svg class="sidebar-link-icon">...</svg>
  Dashboard
</a>
```

- Account: `account-shell`, `account-nav`, `account-nav-link`, `account-nav-link-active`
- Top nav: `top-nav`, `top-nav-inner`, `top-nav-brand`, `top-nav-logo`,
  `top-nav-title`, `top-nav-actions`, `top-nav-menu`, `top-nav-list`,
  `top-nav-item`, `top-nav-link`, `top-nav-icon-button`, `top-nav-user-button`,
  `top-nav-auth-link`, `top-nav-dropdown`, `top-nav-dropdown-header`,
  `top-nav-dropdown-link`
- Sidebar: `sidebar`, `sidebar-brand`, `sidebar-brand-text`, `sidebar-section-label`,
  `sidebar-nav`, `sidebar-link`, `sidebar-link-active`, `sidebar-link-icon`,
  `sidebar-divider`, `sidebar-select`, `sidebar-dropdown`, `sidebar-dropdown-item`,
  `sidebar-dropdown-item-active`

### Alpine.js conventions

Alpine 3.15.x is loaded via `templates/base.html`. A few gotchas we hit the hard way:

- **Do not reuse the variable name `open` across nested `x-data` scopes.** The nav wrapper
  in `templates/components/nav.html` declares `x-data="{open: false}"` for the mobile menu;
  nested scopes (user menu dropdown, etc.) must pick a different name — e.g.
  `userMenuOpen`, `sidebarOpen`. Reusing `open` shadows the outer scope and causes reads and
  writes to resolve against different proxies, leaving the dropdown permanently hidden.
- **Do not add `x-transition` to the user menu dropdown** (or any dropdown that starts with
  `display:none`). In this bundle the inline-style transition gets stuck at opacity 0 and the
  element never becomes visible. Toggle visibility with `x-show` + `x-cloak` only; if you
  need a fade, use explicit `x-transition:enter-*` / `x-transition:leave-*` class directives
  with CSS classes, not the bare `x-transition` shortcut.
- **Do not toggle `hidden` on `.top-nav-menu`.** The desktop navigation is shown by the
  component class via `lg:flex`; adding a runtime `hidden` class after Alpine initializes
  can override it and make the links disappear on desktop. Keep `.top-nav-menu` hidden by
  default in CSS and use `:class="open ? '!flex' : ''"` for the mobile-open state.
- Use `x-model` on the hidden checkbox inside a `.switch` to bind a boolean state. See
  `templates/mainapp/pricing.html` for the monthly / yearly toggle example
  (`x-model="yearly"`, `x-text="yearly ? '$801' : '$89'"`).

### User profile pictures

The custom user model (`usermodel.models.User`) has two image fields:

- `profile_picture` — full upload (`ImageField`, stored under `media/profile_pictures/`)
- `profile_picture_thumbnail` — 96×96 thumbnail auto-generated on save (stored under
  `media/profile_pictures/thumbnails/`), used in nav avatars

Render avatars with the three-tier fallback used in `templates/components/nav_auth.html`
and `templates/components/sidebar_layout/user_menu.html`:

```django
{% if user.profile_picture_thumbnail %}
    <img src="{{ user.profile_picture_thumbnail.url }}" class="w-8 h-8 rounded-full object-cover" …>
{% elif user.profile_picture %}
    <img src="{{ user.profile_picture.url }}" class="w-8 h-8 rounded-full object-cover" …>
{% else %}
    <span class="w-8 h-8 rounded-full bg-gray-600 text-white flex items-center justify-center text-xs font-semibold">
        {{ user.first_name|slice:":1"|upper }}{{ user.last_name|slice:":1"|upper }}
    </span>
{% endif %}
```

Profile editing lives at `/accounts/profile/` (`ProfileEditView` +
`templates/account/profile/edit.html`). The form MUST use `enctype="multipart/form-data"`
because `UserProfileForm` exposes `profile_picture`. Dev media is served via the
`if settings.DEBUG: urlpatterns += static(...)` block at the bottom of `project/urls.py`.

### Account / settings pages

Account pages (change password, email addresses, OTP settings, profile edit) extend
`templates/account/base_manage.html`, which renders a sidebar layout with a left nav of
account links. New account pages should reuse this base and follow the header style from
`templates/account/password_change.html` (`<h2>` with the shared classes) so the pages
line up visually.

### Tours (Driver.js)

`templates/partials/_tour.html` wires Driver.js with SpeedPy-themed popovers (overrides in
the `.driver-popover*` block at the bottom of `input.css`). Tours are only rendered when
the context contains non-empty `tour_steps`. Guard new tour styles outside `@layer
components` because Tailwind would otherwise purge them (the class names live in vendor JS,
not in the `content` globs).

## Code Conventions

### Models

- Create separate files in `mainapp/models/` for different model groups
- Import all models in `mainapp/models/__init__.py` with `__all__` list
- Use string references for foreign keys: `ForeignKey('mainapp.ModelName')`

### Views

- Use class-based views (inherit from Django's generic views)
- Organize views in separate files under `mainapp/views/`
- Import all views in `mainapp/views/__init__.py`

### Admin

- Use meaningful `list_display`, `search_fields`, and filters
- Implement `django_raw_fields` for foreign key fields

### Performance

- Use `select_related()` and `prefetch_related()` for query optimization
- Implement caching with Redis backend
- Use Celery for long-running or I/O-bound operations

### Sending emails

Sending emails is performed with django-post_office library.

If a new email sending is needed to be perfomed then use the following structure:

```python

context = {
    'team_name': membership.team.name,
    'old_role': old_role,
    'new_role': new_role,
    'team_url': f"{settings.SITE_URL}/teams/{membership.team.id}/dashboard/",
}
subject = f"Your role in {membership.team.name} has changed"
html_message = render_to_string("emails/team_role_changed.html", context=context)
mail.send(
    membership.user.email,
    settings.DEFAULT_FROM_EMAIL,
    html_message=html_message,
    subject=subject,
    priority='now',
)

```

Don't use the post_office template attribute, but instead use django's render_to_template to prepare the email message.

New email templates must be placed into `templates/emails/` folder.

### Logging

For logging we use `structlog`.

Example usage:

```python
import structlog

logger = structlog.get_logger(__name__)


def something(user_id: int, something_else: str):
    logger.info("Something happened", user_id=user_id, something_else=something_else)
```

## Forms

In Django forms always use djago crispy forms layout in the `__init__` form and ` {% crispy form %}` to render the form.

For groups of fields that should be collapsed use `crispy_tailwind.layout.Collapse`.

For example:

```python
# forms.py

from django import forms
from django.conf import settings
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, HTML, Div
from crispy_tailwind.layout import Submit, Collapse
import json

from mainapp.models import HTTPMonitor


class HttpMonitorForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False

        self.helper.layout = Layout(
            # Basic Information
            HTML(
                '<div class="mb-6"><h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">Basic Information</h3></div>'),
            Field('name'),
            Field('url'),
            Div(
                Div(Field('method'), css_class='w-1/2 pr-2'),
                Div(Field('check_interval'), css_class='w-1/2 pl-2'),
                css_class='flex'
            ),
            Div(
                Div(Field('is_active'), css_class='mr-4'),
                css_class='flex items-center space-x-4 my-4'
            ),
            Div(
                Div(Field('is_paused'), css_class=''),
                css_class='flex items-center space-x-4 my-4'
            ),

            # Response Validation (Collapsible)
            Collapse(
                "Response Validation",
                HTML(
                    '<p class="text-sm text-gray-600 dark:text-gray-400">Define what a successful response looks like</p>'),
                Field('expected_status_codes'),
                HTML(
                    '<p class="text-xs text-gray-500">Comma-separated list, e.g., 200, 201, 202. Defaults to 200.</p>'),
                Field('expected_content'),
            ),
        )

```

## Environment Setup

The project uses environment variables for configuration. Key variables:

- `DEBUG`: Development mode toggle
- `SECRET_KEY`: Django secret key
- `DATABASE_URL`: Database connection string
- `CELERY_BROKER_URL`: Redis URL for Celery
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts

## Deployment

The project is configured for deployment with Appliku:

- Dockerfile included for containerization
- Static file serving via WhiteNoise
- Celery worker and beat processes configured


### Appliku team and application

This section describes the Team and Application name(s) when deployed with Appliku.

It helps AI Agents to properly use Appliku CLI. If the project has more then one environment, all of them must be listed.

Team path: not set
Application name: not set
