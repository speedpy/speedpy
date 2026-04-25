#!/bin/bash
echo "init.sh has been split into two scripts:"
echo ""
echo "  bash init-docker.sh    # boots the project with Docker Compose"
echo "  bash init-local.sh     # runs the project on the host with uv + npm + sqlite"
echo ""
echo "Pick the one that matches how you want to run the project and re-run that script."
exit 1
