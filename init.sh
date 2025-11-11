#!/bin/bash
set -e  # Exit on error

# Get a list of all remote names
remotes=$(git remote 2>/dev/null || echo "")

if [ -z "$remotes" ]; then
  echo "No Git remotes found to delete."
else
  echo "Deleting the following Git remotes:"
  echo "$remotes"
  echo ""

  # Loop through each remote and remove it
  for remote in $remotes; do
    git remote remove "$remote" || true
    echo "Removed remote: $remote"
  done
  echo ""
  echo "All Git remotes have been deleted."
fi

# Backup docker-compose.yml before modifications
if [ ! -f "docker-compose.yml.bak" ]; then
  cp docker-compose.yml docker-compose.yml.bak
  echo "Created backup: docker-compose.yml.bak"
else
  # Restore from backup for clean slate
  cp docker-compose.yml.bak docker-compose.yml
  echo "Restored docker-compose.yml from backup"
fi

# Generate unique suffix based on directory path for Docker image names
# This prevents image name conflicts when running multiple instances in different directories
UNIQUE_SUFFIX="_$(pwd | md5sum | cut -c1-8)"
echo " * Using unique image suffix: $UNIQUE_SUFFIX"

# Replace the placeholder image name in docker-compose.yml with unique suffix
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS sed syntax
  sed -i '' "s/speedpy-image-suffix/speedpy${UNIQUE_SUFFIX}/g" docker-compose.yml
else
  # Linux sed syntax
  sed -i "s/speedpy-image-suffix/speedpy${UNIQUE_SUFFIX}/g" docker-compose.yml
fi

# Generate random port between 9000 and 9999


WEB_PORT=$((9000 + RANDOM % 501))
echo " * Using random port for Django: $WEB_PORT"

# Update docker-compose.yml with the random port
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/9000/$WEB_PORT/g" docker-compose.yml
else
  sed -i "s/9000/$WEB_PORT/g" docker-compose.yml
fi

# Generate random port between 9501 and 9999
NGINX_PORT=$((9501 + RANDOM % 499))
echo " * Using random port for nginx: $NGINX_PORT"

# Update docker-compose.yml with the random port
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/127.0.0.1:9001:80/127.0.0.1:$NGINX_PORT:80/g" docker-compose.yml
else
  sed -i "s/127.0.0.1:9001:80/127.0.0.1:$NGINX_PORT:80/g" docker-compose.yml
fi

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

# Configure TTY for docker compose
USE_TTY=""
if [ -t 1 ]; then
  USE_TTY="-T"
fi
echo "USE_TTY=${USE_TTY}"

# Initialize git repository
git init -b master >/dev/null 2>&1 || true

cp .docker.env .env
echo " * docker compose down -v --remove-orphans"
docker compose down -v --remove-orphans
echo " * Building the Docker image for the project (might take a while)"
docker compose build -q
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
