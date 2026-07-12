# One-Click Deploy

This fork includes a Linux deployment script for self-hosted use.

## Command

```bash
tmp=$(mktemp) && (curl -fsSL --connect-timeout 8 --max-time 20 https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp" || curl -fsSL https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh -o "$tmp") && bash "$tmp"
```

The production deployment uses `/opt/ai-lanbot`, HTTP port `5300`, plugin debug port
`5401`, reverse ports `2280-2285`, and the prebuilt image when available.

The command tries the official raw GitHub URL first and then falls back to the accelerator for downloading the script itself. The direct-download attempt has a short timeout so users in regions with slow GitHub access do not need to wait indefinitely. After the script starts, it automatically checks whether GitHub direct repository download works. If direct download is unavailable or too slow, it uses `https://github.xiaohangyun.org` to download the repository archive.

The script also checks Docker image access automatically. By default it starts from a prebuilt fork image for speed. If a Docker Hub image is available and Docker Hub direct access is slow or unavailable, it can use `https://docker.xiaohangyun.org` for the runtime image. When a local source build is requested or used as a fallback, it writes `LANBOT_DOCKER_IMAGE_PREFIX=docker.xiaohangyun.org/library/` to `docker/.env` when the required base images are available through the accelerator. Users do not need to enter either accelerator URL.

## What It Does

- Installs Docker and Docker Compose when missing on common Linux distributions.
- Downloads or updates `csbsgyl/ai-lanbot`.
- Deploys the production instance without requiring a deployment mode argument.
- Starts from an immutable commit-tagged image when available.
- Falls back to a local source build when no production image is reachable.
- Automatically uses the Docker accelerator for runtime/base images when direct Docker access is unavailable and the accelerator exposes the required image.
- Starts the LangBot and Plugin Runtime core services without the optional Box profile.
- Installs or updates the bundled IDC query plugin under `docker/data/plugins/idc_query`.
- Preserves IDC group bindings separately under `docker/data/idc-query` during source updates.
- Keeps persistent data under `docker/data`.
- Waits for the Plugin Runtime to become healthy before starting LangBot.
- Waits for `/api/v1/system/info` to pass before reporting success.
- Prints the local URL, remote URL, first-time setup URL, login URL, and maintenance commands.
- Installs a systemd path unit that accepts fixed update requests from the authenticated WebUI without mounting the host Docker socket into LangBot.

## In-App Updates

After the first deployment, open the update control beside the version in the
application sidebar. It compares the deployed commit with `main`, then allows
an authenticated administrator to request the update. The service restarts
during installation and the same page reports progress when it reconnects.

The WebUI only writes `docker/data/update-request/request.json`. The separate
status directory is mounted read-only in LangBot. A host-side systemd service
executes a root-owned updater installed under `/usr/local/libexec`; request data
cannot provide a shell command, repository, image name, or target revision.
Update status is stored in
`docker/data/update/status.json`, and host logs are written to
`docker/data/update/update.log`.

Managed updates download the updater and source from the same immutable commit
SHA and require that commit's published Docker image. They fail without
replacing the running container when the image is not available; local source
build fallback remains available only for an operator-run one-click deployment.

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
IDC_QUERY_API_BASE_URL=https://query.example.com
IDC_QUERY_API_TOKEN=replace-with-a-service-token
IDC_QUERY_TIMEOUT_SECONDS=8
IDC_QUERY_VERIFY_TLS=true
```

These are advanced overrides. The production command works without setting them.

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

`LANBOT_DEPLOY_MODE` remains an advanced override. Production defaults to
`image` and falls back to a local source build when necessary.

## Maintenance

```bash
cd /opt/ai-lanbot/docker
docker compose ps
docker compose logs -f langbot
docker compose down
```
