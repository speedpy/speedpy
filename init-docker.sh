#!/bin/bash
set -e  # Exit on error

# Get a list of all remote names
remotes=$(git remote 2>/dev/null || echo "")

# Rename origin to speedpy if it exists
if echo "$remotes" | grep -q "^origin$"; then
  git remote rename origin speedpy
  echo "Renamed remote 'origin' to 'speedpy'"
fi
echo "Creating a speedpy branch for future updates. "
git branch speedpy || true
git branch --set-upstream-to=speedpy/master speedpy 2>/dev/null || true
echo "Set speedpy branch to track speedpy/master"
# Unset upstream tracking for master branch
if git rev-parse --verify master >/dev/null 2>&1; then
  git branch --unset-upstream master 2>/dev/null || true
  echo "Unset upstream tracking for 'master' branch"
fi

# Per-checkout values. They go into .env (gitignored), which docker compose
# reads for variable substitution, so docker-compose.yml stays as committed.
# The image suffix keeps image names apart across checkouts in different
# directories (cksum: available on Linux and macOS, unlike md5sum).
IMAGE_SUFFIX="_$(pwd | cksum | cut -d' ' -f1)"
echo " * Using unique image suffix: $IMAGE_SUFFIX"

WEB_PORT=$((9000 + RANDOM % 501))
echo " * Using random port for Django: $WEB_PORT"

MEDIA_PORT=$((9501 + RANDOM % 499))
echo " * Using random port for nginx: $MEDIA_PORT"

# Write dev.sh with the chosen port. docker-compose.yml's web.command runs
# `bash dev.sh`, so this is what the web container actually executes.
cat > dev.sh <<EOF
#!/usr/bin/env bash
exec python manage.py runserver 0.0.0.0:$WEB_PORT
EOF
chmod a+x dev.sh

# Populate the mode-specific commands sheet for AI coding agents.
cp AGENTS-local.docker.md AGENTS-local.md

open_url() {
  local url="$1"

  case "$(uname -s)" in
  Linux*)
    if grep -qi microsoft /proc/version; then
      # WSL
      cmd.exe /c start "$url" >/dev/null 2>&1
    else
      # Regular Linux
      xdg-open "$url" >/dev/null 2>&1
    fi
    ;;
  Darwin*)
    # macOS
    open "$url" >/dev/null 2>&1
    ;;
  *)
    echo "Unsupported operating system"
    exit 1
    ;;
  esac
}
# Source pre-check script if it exists
if [ -f "./pre_check.sh" ]; then
  . ./pre_check.sh
fi

# The init commands below are not interactive and some write to files, so
# never allocate a TTY for them.
USE_TTY="-T"

# Create media/ as the current user. If it is missing, Docker creates it as
# root for the bind mount and the web container cannot save uploads.
mkdir -p media

cp .docker.env .env
{
  echo "SITE_URL=http://127.0.0.1:$WEB_PORT"
  echo "WEB_PORT=$WEB_PORT"
  echo "MEDIA_PORT=$MEDIA_PORT"
  echo "IMAGE_SUFFIX=$IMAGE_SUFFIX"
} >> .env
echo " * docker compose down -v --remove-orphans"
docker compose down -v --remove-orphans
echo " * Building the Docker image for the project (might take a while)"
docker compose build -q --no-cache
echo " * Starting DB and redis"
docker compose up -d db redis
sleep 2
echo " * Generating directories for tailwind config"
docker compose run --rm ${USE_TTY} web python manage.py generate_tailwind_directories
echo " * Installing tailwind and dependencies"
docker compose run --rm ${USE_TTY} web bash -c "npm i && npm run tailwind:build"
echo " * Initializing the project"
docker compose run --rm ${USE_TTY} web python manage.py makemigrations
docker compose run --rm ${USE_TTY} web python manage.py migrate
docker compose run --rm ${USE_TTY} web python manage.py makesuperuser >local_password.txt
cat local_password.txt
echo " * Created local superuser credentials are stored in local_password.txt file for your convenience"
git add .
git commit -q -m "Initial commit"

echo " * Starting the project..."
docker compose up -d
sleep 1

count=0
max_retries=5
until curl -s -f -o /dev/null "http://127.0.0.1:$WEB_PORT" || [ "$count" -ge "$max_retries" ]; do
  echo "Waiting... $((count + 1))/$max_retries"
  count=$((count + 1))
  sleep 1
done
if [ "$count" -lt "$max_retries" ]; then
  echo "Site is up!"
else
  echo "App seems to be still down after $max_retries retries"
fi

open_url "http://127.0.0.1:$WEB_PORT"
echo "Open your browser at http://127.0.0.1:$WEB_PORT"
