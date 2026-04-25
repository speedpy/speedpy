#!/bin/bash
set -e  # Exit on error

# ---------------------------------------------------------------------------
# Prerequisite checks: uv and npm/node must be on PATH (Linux + macOS).
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is not installed."
  echo ""
  echo "Install it with:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo ""
  echo "Or see https://docs.astral.sh/uv/getting-started/installation/ for alternatives (Homebrew, pipx, etc.)."
  exit 1
fi
echo "✓ uv is installed: $(uv --version)"

if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
  echo "Error: npm/node is not installed."
  echo ""
  echo "We recommend installing nvm and using the LTS Node:"
  echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
  echo "    # restart your shell (or 'source ~/.nvm/nvm.sh') and then:"
  echo "    nvm install --lts && nvm alias default 'lts/*'"
  exit 1
fi
echo "✓ node is installed: $(node --version)"
echo "✓ npm is installed: $(npm --version)"

# ---------------------------------------------------------------------------
# Git remote rewrite (matches init-docker.sh).
# ---------------------------------------------------------------------------
remotes=$(git remote 2>/dev/null || echo "")
if echo "$remotes" | grep -q "^origin$"; then
  git remote rename origin speedpy
  echo "Renamed remote 'origin' to 'speedpy'"
fi
echo "Creating a speedpy branch for future updates."
git branch speedpy || true
git branch --set-upstream-to=speedpy/master speedpy 2>/dev/null || true
echo "Set speedpy branch to track speedpy/master"
if git rev-parse --verify master >/dev/null 2>&1; then
  git branch --unset-upstream master 2>/dev/null || true
  echo "Unset upstream tracking for 'master' branch"
fi

# ---------------------------------------------------------------------------
# Environment + dev.sh (with a randomized port so multiple checkouts coexist).
# ---------------------------------------------------------------------------
cp .local.env .env
echo " * Copied .local.env to .env"

WEB_PORT=$((9000 + RANDOM % 501))
echo " * Using random port for Django: $WEB_PORT"

cat > dev.sh <<EOF
#!/usr/bin/env bash
exec python manage.py runserver 0.0.0.0:$WEB_PORT
EOF
chmod a+x dev.sh

# Populate the mode-specific commands sheet for AI coding agents.
cp AGENTS-local.uv.md AGENTS-local.md

# ---------------------------------------------------------------------------
# Python deps (uv) + frontend deps (npm) + Tailwind build.
# ---------------------------------------------------------------------------
echo " * Syncing Python dependencies with uv"
uv sync

echo " * Installing npm dependencies"
npm install

echo " * Generating Tailwind directories"
uv run python manage.py generate_tailwind_directories

echo " * Building Tailwind CSS"
npm run tailwind:build

# ---------------------------------------------------------------------------
# Database + superuser.
# ---------------------------------------------------------------------------
echo " * Running migrations"
uv run python manage.py migrate

echo " * Creating superuser (credentials in local_password.txt)"
uv run python manage.py makesuperuser >local_password.txt
cat local_password.txt

# ---------------------------------------------------------------------------
# Initial commit (mirrors init-docker.sh behavior).
# ---------------------------------------------------------------------------
git add .
git commit -q -m "Initial commit"

echo ""
echo "Setup complete."
echo ""
echo "Open two terminals:"
echo "    Terminal 1:  uv run bash dev.sh"
echo "    Terminal 2:  npm run tailwind:watch"
echo ""
echo "Then open http://127.0.0.1:$WEB_PORT in your browser."
