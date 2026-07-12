# One-Click Deploy

This fork includes a Linux deployment script for self-hosted use.

## Test Deployment

```bash
tmp=$(mktemp) && (curl -fsSL --connect-timeout 8 --max-time 20 https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp" || curl -fsSL https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp") && bash "$tmp" test
```

Test mode builds the latest `main` source and uses isolated defaults:
`/opt/ai-lanbot-test`, HTTP port `5301`, plugin debug port `5402`, and
reverse ports `3280-3285`.

## Production Deployment

```bash
tmp=$(mktemp) && (curl -fsSL --connect-timeout 8 --max-time 20 https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp" || curl -fsSL https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp") && bash "$tmp" production
```

Production mode uses `/opt/ai-lanbot`, HTTP port `5300`, plugin debug port
`5401`, reverse ports `2280-2285`, and the prebuilt image when available.

The two modes use separate Compose projects, container names, configuration,
bindings, and data directories, so test and production can run on one server.
Running the same command again updates only that environment.

Both commands try the official raw GitHub URL first and then fall back to the accelerator for downloading the script itself. The direct-download attempt has a short timeout so users in regions with slow GitHub access do not need to wait indefinitely. After the script starts, it automatically checks whether GitHub direct repository download works. If direct download is unavailable or too slow, it uses `https://github.xiaohangyun.org` to download the repository archive.

The script also checks Docker image access automatically. By default it starts from a prebuilt fork image for speed. If a Docker Hub image is available and Docker Hub direct access is slow or unavailable, it can use `https://docker.xiaohangyun.org` for the runtime image. When a local source build is requested or used as a fallback, it writes `LANBOT_DOCKER_IMAGE_PREFIX=docker.xiaohangyun.org/library/` to `docker/.env` when the required base images are available through the accelerator. Users do not need to enter either accelerator URL.

## What It Does

- Installs Docker and Docker Compose when missing on common Linux distributions.
- Downloads or updates `csbsgyl/ai-lanbot`.
- Supports explicit `test` and `production` modes through the same script.
- Builds the latest source in test mode.
- Starts production from a prebuilt fork image by default.
- Falls back to a local source build when no production image is reachable.
- Automatically uses the Docker accelerator for runtime/base images when direct Docker access is unavailable and the accelerator exposes the required image.
- Starts the LangBot and Plugin Runtime core services without the optional Box profile.
- Installs or updates the bundled IDC query plugin under `docker/data/plugins/idc_query`.
- Preserves IDC group bindings separately under `docker/data/idc-query` during source updates.
- Keeps persistent data under `docker/data`.
- Waits for the Plugin Runtime to become healthy before starting LangBot.
- Waits for `/api/v1/system/info` to pass before reporting success.
- Prints the local URL, remote URL, first-time setup URL, login URL, and maintenance commands.

## Login After Deployment

The script does not create or print a default username/password. A fresh LangBot instance has no default admin account.

- First deployment: open `/register` and create the first administrator account.
- After initialization: open `/login` and sign in with the account you created.
- If the health check fails, the script exits with an error and prints recent container status/logs instead of reporting success.

## Optional Environment Variables

```bash
LANBOT_ENVIRONMENT=production
LANBOT_INSTALL_DIR=/opt/ai-lanbot
LANBOT_BRANCH=main
LANBOT_HTTP_PORT=5300
LANBOT_COMPOSE_PROFILES=all
LANBOT_DEPLOY_MODE=image
LANBOT_ALLOW_BUILD_FALLBACK=true
LANBOT_IMAGE=ghcr.io/csbsgyl/ai-lanbot:latest
LANBOT_SOURCE_MODE=archive
IDC_QUERY_API_BASE_URL=https://query.example.com
IDC_QUERY_API_TOKEN=replace-with-a-service-token
IDC_QUERY_TIMEOUT_SECONDS=8
IDC_QUERY_VERIFY_TLS=true
```

These are advanced overrides. The test and production commands work without
setting them.

`LANBOT_COMPOSE_PROFILES` is empty by default, so the IDC deployment does not
start the optional Box service or mount the host Docker socket. Set it to `all`
only when sandbox tools and Box-managed skills are intentionally required. If
an older deployment previously started Box, a default one-click upgrade stops
and removes that container without deleting its persisted data directory.

The IDC plugin is installed even when its gateway is not configured. In that
state it can display its command menu, but binding and data queries return a
configuration notice instead of fabricated results. The deployment variables
are written to `docker/data/idc-query/config.env` with owner-only permissions
and preserved on later one-click upgrades. The plugin reads this mounted file
directly because the Linux Plugin Runtime intentionally starts plugin processes
with a clean environment. The token is not exposed through Docker container
environment metadata and must not be committed.

The normalized gateway contract is documented in
[`IDC_QUERY_GATEWAY.md`](IDC_QUERY_GATEWAY.md).

`LANBOT_DEPLOY_MODE` remains an advanced override. Test mode already defaults
to `build`; production defaults to `image`.

## Maintenance

```bash
# Production
cd /opt/ai-lanbot/docker
docker compose ps
docker compose logs -f langbot
docker compose down

# Test
cd /opt/ai-lanbot-test/docker
docker compose ps
docker compose logs -f langbot
docker compose down
```
