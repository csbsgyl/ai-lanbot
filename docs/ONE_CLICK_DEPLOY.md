# One-Click Deploy

This fork includes a Linux deployment script for self-hosted use.

## Command

```bash
tmp=$(mktemp) && (curl -fsSL --connect-timeout 8 --max-time 20 https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp" || curl -fsSL https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp") && bash "$tmp"
```

The command tries the official raw GitHub URL first and then falls back to the accelerator for downloading the script itself. The direct-download attempt has a short timeout so users in regions with slow GitHub access do not need to wait indefinitely. After the script starts, it automatically checks whether GitHub direct repository download works. If direct download is unavailable or too slow, it uses `https://github.xiaohangyun.org` to download the repository archive. Users do not need to enter the accelerator URL.

## What It Does

- Installs Docker and Docker Compose when missing on common Linux distributions.
- Downloads or updates `csbsgyl/ai-lanbot`.
- Builds the local fork image from source.
- Starts LangBot with Docker Compose profile `all`.
- Keeps persistent data under `docker/data`.

## Optional Environment Variables

```bash
LANBOT_INSTALL_DIR=/opt/ai-lanbot
LANBOT_BRANCH=main
LANBOT_HTTP_PORT=5300
LANBOT_COMPOSE_PROFILES=all
```

These are optional. The default command works without setting them.

## Maintenance

```bash
cd /opt/ai-lanbot/docker
docker compose -f docker-compose.yaml -f docker-compose.local-build.yaml --profile all ps
docker compose -f docker-compose.yaml -f docker-compose.local-build.yaml logs -f langbot
docker compose -f docker-compose.yaml -f docker-compose.local-build.yaml --profile all down
```
