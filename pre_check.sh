#!/bin/bash
set -e
# Check Git
# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "Error: git is not installed"
    exit 1
fi

# Check git version
git_version=$(git --version)
echo "✓ Git is installed: $git_version"

# Check global user name
git_user=$(git config --global user.name)
if [ -z "$git_user" ]; then
    echo "Error: Git global user.name is not set"
    echo "Set it using: git config --global user.name \"Your Name\""
    exit 1
fi
echo "✓ Git user.name is set to: $git_user"

# Check global email
git_email=$(git config --global user.email)
if [ -z "$git_email" ]; then
    echo "Error: Git global user.email is not set"
    echo "Set it using: git config --global user.email \"your.email@example.com\""
    exit 1
fi
echo "✓ Git user.email is set to: $git_email"

echo "✓ Git is properly configured!"

# Check Docker
if command -v docker &> /dev/null; then
    echo "✓ Docker is installed"
    if ! docker info &> /dev/null; then
      echo "Error: Docker daemon is not running"
      if grep -qi microsoft /proc/version; then
        echo "Start Docker Desktop and ensure integration with WSL 2 is enabled"
      else
        echo "Start with: sudo service docker start"
      fi
      exit 1
    fi
else
    echo "Error: Docker is not installed"
    exit 1
fi

# Check Docker Compose
if docker compose version &> /dev/null; then
    echo "✓ Docker Compose is available"
else
    echo "Error: Docker Compose is not available"
    echo "Install Docker Compose or ensure Docker Desktop includes it"
    exit 1
fi

echo "✓ All required tools are installed"


