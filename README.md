# SpeedPy

**Django-based SaaS boilerplate for the modern AI era.**

Instantly start your next SaaS project. Built on the rock-solid foundation of Django, supercharged with production-ready APIs, Webhooks, OAuth2, and Model Context Protocol (MCP) for AI agents.

[Website](https://speedpy.com) | [Documentation](https://docs.speedpy.com) | [Discord](https://speedpy.com/discord)

## Features

* **Rock-Solid Foundation:** Django's battle-tested ORM, server-rendered UI with HTMX, Alpine.js, and TailwindCSS.
* **API-First & Integration Ready:** Comprehensive REST API built with Django Rest Framework (DRF) and documented via OpenAPI. Webhooks engine for real-time events.
* **Enterprise-Grade Authentication:** OAuth2 Provider, Personal Access Tokens (PATs), granular scopes, and team-scoped resources.
* **Built for the AI Era:** Out-of-the-box MCP server template, first-party CLI, and pre-written agent recipes to help AI coding assistants write integrations.
* **Multi-Tenant SaaS:** Teams, roles, and invitations out of the box with smart role-based permissions.
* **Background Tasks:** Celery integration for asynchronous processing.
* **Security First:** Multi-factor authentication (OTP) and encrypted database fields.
* **12 Factor App:** Uses environment variables for configuration.

## Quick Start

### Requirements

* Linux or macOS
* Git installed and configured
* One of the following environments:
  * **Docker mode:** Docker and Docker Compose
  * **Local mode:** [`uv`](https://docs.astral.sh/uv/) and Node.js (LTS)

### Installation

If you haven't cloned the repository, you can use the one-line download and start script:

```bash
wget -qO- https://speedpy.com/install | bash
```

If you have already cloned the repository, pick a mode and run the matching initialization script in the project root:

```bash
# Docker Compose: Postgres + Redis + Celery + nginx media
bash init-docker.sh

# uv + npm on the host: SQLite, no Redis, Celery in always-eager mode
bash init-local.sh
```

### Running the Project

**Local mode (uv):**
Start the development server in one terminal and Tailwind watch in another:

```bash
uv run bash dev.sh
npm run tailwind:watch
```

**Docker mode:**
The `web` service runs `bash dev.sh` automatically. Bring everything up with:

```bash
docker compose up -d
```

## Documentation

Comprehensive documentation is available at [docs.speedpy.com](https://docs.speedpy.com). 

Key documentation pages:
* [Installation & Requirements](https://docs.speedpy.com/docs/installation)
* [Project Layout](https://docs.speedpy.com/docs/project-layout)
* [Authentication](https://docs.speedpy.com/docs/authentication)
* [API Reference](https://docs.speedpy.com/docs/api)
* [Webhooks](https://docs.speedpy.com/docs/webhooks)
* [Integrations](https://docs.speedpy.com/docs/integrations)
* [Teams](https://docs.speedpy.com/docs/teams)
* [Deployment](https://docs.speedpy.com/docs/deployment)

## Project Structure

SpeedPy uses a single-app Django project layout. The majority of your code will live in the `mainapp` directory, which is structured as a series of Python packages instead of single files (e.g., `mainapp/models/`, `mainapp/views/`, `mainapp/forms/`).

A separate `usermodel` app handles the custom user model with email-based authentication.

## Production Readiness

Before deploying to production, ensure you remove demo content and placeholder pages. Refer to the `PRODUCTION_READY.md` file in the repository or the [Production Readiness](https://docs.speedpy.com/docs/production-readiness) documentation for a complete checklist.

## Deployment

SpeedPy includes an `appliku.yml` file for automatic configuration with [Appliku](https://appliku.com). See the [Deployment documentation](https://docs.speedpy.com/docs/deployment) for detailed instructions on setting up your application, databases, and background workers.
