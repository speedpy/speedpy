---
name: start-speedpy
description: Prepare a newly cloned SpeedPy project for Docker, diagnose Git and Docker prerequisites, run the Docker initializer, and verify the local site. Use when someone asks to install, set up, start, or get a fresh SpeedPy project running. Do not use for the uv/local setup path or feature development in an initialized project.
---

# Start SpeedPy

Help the user get a fresh SpeedPy project running with Docker. Explain unfamiliar terms in plain language and perform safe terminal work for them whenever possible.

## Check the computer

From the SpeedPy project root, run:

```bash
bash .agents/skills/start-speedpy/scripts/doctor.sh
```

Use its results to resolve every failed check before initialization. Do not silently install operating-system packages or Docker Desktop.

- On Windows, use WSL 2 with an Ubuntu terminal. Docker Desktop must be running with WSL integration enabled. Keep the repository in the Linux home directory, such as `~/projects/my-product`, not under `/mnt/c`.
- On macOS, install and start Docker Desktop. macOS may offer to install Git developer tools the first time `git` runs.
- On Linux, use Docker Engine and the Compose plugin from Docker's documentation for the user's distribution. If a package command needs `sudo`, show what it will do and obtain permission before running it.
- If Git has no global name or email, ask for the values and configure them with `git config --global`. Never invent either value.

After the user completes a graphical installer, restarts the computer, opens Docker Desktop, or enables WSL integration, rerun the doctor rather than assuming the change worked.

## Initialize only a fresh project

`init-docker.sh` replaces local configuration, removes this project's Docker volumes, creates local credentials, and makes an initial Git commit. Before running it:

1. Confirm the current directory is the intended SpeedPy clone and contains `init-docker.sh` and `docker-compose.yml`.
2. Inspect `git status --short`, `git log -3 --oneline`, and whether `AGENTS-local.md` or `docker-compose.yml.bak` already exists.
3. Treat the project as already initialized if either generated file exists. Do not rerun initialization unless the user explicitly asks to reset it and accepts that this removes local Docker data.
4. If there are unexpected uncommitted changes, explain them and stop before initialization.

When the checks pass and the clone is fresh, run:

```bash
bash init-docker.sh
```

Monitor the command through completion. Diagnose failures from the command output instead of restarting the entire initializer blindly.

## Verify the result

After initialization:

1. Run `docker compose ps` and confirm the application services are running.
2. Read the generated port from `dev.sh` and request `http://127.0.0.1:<port>` with `curl`.
3. If the request fails, inspect `docker compose logs --tail=100 web` and the relevant dependency service logs.
4. Tell the user the local URL and that login details are stored in `local_password.txt`. Do not repeat the password in chat unless the user asks.

Finish by suggesting that the user open the folder in their coding agent and describe the product they want to build. Do not begin feature work unless requested.
