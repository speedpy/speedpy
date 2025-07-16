# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SpeedPy Standard is a Django-based web application starter template featuring a single-app architecture with custom user authentication, Celery for background tasks, and Tailwind CSS for styling. The project follows a Docker-first development approach.

## Development Commands

### Docker Commands (Primary Development Method)
All development should be done through Docker containers:

```bash
# Initialize the project (first time setup)
make init

# Run development server
make dev
# OR: docker compose run --rm web python manage.py runserver

# Database operations
make mm  # makemigrations
make m   # migrate
# OR: docker compose run --rm web python manage.py makemigrations
# OR: docker compose run --rm web python manage.py migrate

# Tailwind CSS
make tw              # watch mode for development
make twb             # build once
make tailwind-watch  # watch with directory generation
make tailwind-build  # build with directory generation

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
- **Backend**: Django 5.1.2 with PostgreSQL
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
- Flowbite components integrated
- Static files served via WhiteNoise
- CSS compiled from `static/mainapp/input.css` to `static/mainapp/styles.css`

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