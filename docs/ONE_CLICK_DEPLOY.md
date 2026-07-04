# One-Click Deploy

This fork includes a Linux deployment script for self-hosted use.

## Command

```bash
tmp=$(mktemp) && (curl -fsSL --connect-timeout 8 --max-time 20 https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp" || curl -fsSL https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp") && bash "$tmp"
```

The command tries the official raw GitHub URL first and then falls back to the accelerator for downloading the script itself. The direct-download attempt has a short timeout so users in regions with slow GitHub access do not need to wait indefinitely. After the script starts, it automatically checks whether GitHub direct repository download works. If direct download is unavailable or too slow, it uses `https://github.xiaohangyun.org` to download the repository archive.

The script also checks Docker image access automatically. By default it starts from a prebuilt fork image for speed. If a Docker Hub image is available and Docker Hub direct access is slow or unavailable, it can use `https://docker.xiaohangyun.org` for the runtime image. When a local source build is requested or used as a fallback, it writes `LANBOT_DOCKER_IMAGE_PREFIX=docker.xiaohangyun.org/library/` to `docker/.env` when the required base images are available through the accelerator. Users do not need to enter either accelerator URL.

## What It Does

- Installs Docker and Docker Compose when missing on common Linux distributions.
- Downloads or updates `csbsgyl/ai-lanbot`.
- Starts LangBot from a prebuilt fork image by default.
- Falls back to local source build only when no prebuilt image is reachable, or when `LANBOT_DEPLOY_MODE=build` is set.
- Automatically uses the Docker accelerator for runtime/base images when direct Docker access is unavailable and the accelerator exposes the required image.
- Starts LangBot with Docker Compose profile `all`.
- Keeps persistent data under `docker/data`.
- Waits for `/api/v1/system/info` to pass before reporting success.
- Prints the local URL, remote URL, first-time setup URL, login URL, and maintenance commands.

## Login After Deployment

The script does not create or print a default username/password. A fresh LangBot instance has no default admin account.

- First deployment: open `/register` and create the first administrator account.
- After initialization: open `/login` and sign in with the account you created.
- If the health check fails, the script exits with an error and prints recent container status/logs instead of reporting success.

## Optional Environment Variables

```bash
LANBOT_INSTALL_DIR=/opt/ai-lanbot
LANBOT_BRANCH=main
LANBOT_HTTP_PORT=5300
LANBOT_COMPOSE_PROFILES=all
LANBOT_DEPLOY_MODE=image
LANBOT_ALLOW_BUILD_FALLBACK=true
LANBOT_IMAGE=ghcr.io/csbsgyl/ai-lanbot:latest
LANBOT_SOURCE_MODE=archive
```

These are optional. The default command works without setting them.

Use `LANBOT_DEPLOY_MODE=build` only when you intentionally want to build the local checkout on the server. That path is slower because it installs frontend/backend dependencies and compiles the sandbox binary.

## Maintenance

```bash
cd /opt/ai-lanbot/docker
docker compose --profile all ps
docker compose logs -f langbot
docker compose --profile all down
```
