#!/usr/bin/env bash

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../../../.." && pwd)"
failures=0
warnings=0

ok() {
  printf '✓ %s\n' "$1"
}

fail() {
  printf '✗ %s\n' "$1"
  failures=$((failures + 1))
}

warn() {
  printf '! %s\n' "$1"
  warnings=$((warnings + 1))
}

kernel="$(uname -s 2>/dev/null || printf 'Unknown')"
environment="linux"

case "$kernel" in
  Darwin*) environment="macos" ;;
  MINGW*|MSYS*|CYGWIN*) environment="windows-shell" ;;
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      environment="wsl"
    fi
    ;;
  *) environment="unknown" ;;
esac

printf 'SpeedPy setup doctor\n'
printf 'Project: %s\n' "$project_root"
printf 'Environment: %s\n\n' "$environment"

if [ "$environment" = "windows-shell" ]; then
  fail "Use an Ubuntu terminal in WSL 2, rather than Git Bash or another native Windows shell."
elif [ "$environment" = "unknown" ]; then
  warn "This operating environment is not recognized; the Docker setup supports macOS, Linux, and Windows through WSL 2."
else
  ok "Supported operating environment detected."
fi

if [ "$environment" = "wsl" ] && [[ "$project_root" == /mnt/* ]]; then
  fail "Move or clone this project under your WSL home directory (for example, ~/projects/my-product), not under /mnt/c."
fi

if [ -f "$project_root/init-docker.sh" ] && [ -f "$project_root/docker-compose.yml" ]; then
  ok "This is a SpeedPy project root."
else
  fail "The project root must contain init-docker.sh and docker-compose.yml."
fi

if command -v git >/dev/null 2>&1; then
  ok "$(git --version)"
else
  fail "Git is not installed."
fi

git_user="$(git config --global user.name 2>/dev/null || true)"
git_email="$(git config --global user.email 2>/dev/null || true)"

if [ -n "$git_user" ]; then
  ok "Git author name is configured."
else
  fail "Git author name is missing. Set it with: git config --global user.name \"Your Name\""
fi

if [ -n "$git_email" ]; then
  ok "Git author email is configured."
else
  fail "Git author email is missing. Set it with: git config --global user.email \"you@example.com\""
fi

if command -v docker >/dev/null 2>&1; then
  ok "Docker is installed."
else
  fail "Docker is not installed."
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "Docker is running."
else
  case "$environment" in
    macos) fail "Docker is not running. Open Docker Desktop and wait until it is ready." ;;
    wsl) fail "Docker is not running. Open Docker Desktop and enable WSL integration for this Ubuntu distribution." ;;
    linux) fail "Docker is not running. Start the Docker service for this Linux distribution." ;;
    *) fail "Docker is not running." ;;
  esac
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "Docker Compose is available."
else
  fail "Docker Compose is not available. Docker Desktop includes it; Linux users need the Docker Compose plugin."
fi

if [ -e "$project_root/AGENTS-local.md" ] || [ -e "$project_root/docker-compose.yml.bak" ]; then
  warn "This project appears to have been initialized already. Do not run init-docker.sh again without reviewing local data and changes."
else
  ok "No generated initialization files were found."
fi

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'Ready: all required checks passed.'
  if [ "$warnings" -gt 0 ]; then
    printf ' Review the %s warning(s) above.' "$warnings"
  fi
  printf '\n'
  exit 0
fi

printf 'Not ready: fix %s failed check(s), then run this doctor again.\n' "$failures"
exit 1
