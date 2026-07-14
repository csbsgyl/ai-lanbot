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
- Reuses the existing managed deployment's ports, container names, Compose
  project, source mode, and Box setting unless the current command overrides
  them with `LANBOT_*` variables.
- Starts from an immutable commit-tagged image when available.
- Confirms and pulls the target image before replacing managed source or
  bundled plugin files.
- Falls back to a local source build when no production image is reachable.
- Automatically uses the Docker accelerator for runtime/base images when direct Docker access is unavailable and the accelerator exposes the required image.
- Starts the LangBot and Plugin Runtime core services without the optional Box profile.
- Installs or updates the bundled IDC query plugin under `docker/data/plugins/idc_query`.
- Stages archive and bundled-plugin updates beside the existing deployment,
  then swaps them into place while preserving `docker/data` and `docker/.env`.
- Adds authenticated IDC gateway configuration under WebUI **Settings > IDC Query**.
- Preserves IDC group bindings separately under `docker/data/idc-query` during source updates.
- Keeps persistent data under `docker/data`.
- Includes an owner-only, checksum-verified local backup/restore command that
  stops running services while snapshotting `docker/data` for consistency.
- Waits for the Plugin Runtime to become healthy before starting LangBot.
- Waits for `/api/v1/system/info` to pass before reporting success.
- Prints the local URL, remote URL, first-time setup URL, login URL, and maintenance commands.
- Prints the QQ callback reverse-proxy upstream and the per-bot callback path.
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
replacing the running container, managed source, or bundled plugin when the
image is not available. Deployment and managed-update runs for the same install
directory are serialized when the host provides `flock`. Local source build
fallback remains available only for an operator-run one-click deployment.

## Login After Deployment

The script does not create or print a default username/password. A fresh LangBot instance has no default admin account.

- First deployment: open `/register` and create the first administrator account.
- After initialization: open `/login` and sign in with the account you created.
- If the health check fails, the script exits with an error and prints recent container status/logs instead of reporting success.

## QQ Official Callback

The production container publishes LangBot on host port `5300`. When the HTTPS
reverse proxy runs on the same server, use `http://127.0.0.1:5300` as its
upstream. When the reverse proxy runs elsewhere, use
`http://<server-ip>:5300` and restrict that port to the proxy server in the
host firewall or cloud security group.

The QQ Official adapter exposes a stable callback route:

```text
/qq/callback
```

Keep this path unchanged in the reverse proxy. The URL entered in the QQ
Open Platform must therefore be an externally reachable HTTPS URL such as:

```text
https://bot.example.com/qq/callback
```

The route selects the enabled QQ Official bot by QQ's `X-Bot-Appid` request
header. The existing `/bots/<bot-uuid>` route remains available for backward
compatibility and for other webhook adapters.

QQ currently permits callback ports `80`, `443`, `8080`, and `8443`; HTTPS is
required. The bundled QQ Official adapter handles the `op=13` callback
validation with a bounded challenge timestamp, verifies signed event callbacks,
and acknowledges accepted events
with `op=12`. Signed callbacks outside the accepted time window are rejected,
and recently seen event IDs are acknowledged without being processed twice.
Callback dispatch uses a bounded pending queue. If the queue is full, LangBot
returns `503` without marking the event as processed so QQ can retry it later.
Configure the reverse proxy to pass through this status code instead of
rewriting it to `200`; the callback diagnostics page reports current queue
usage and overload count.
Signed message events are checked against QQ's documented event shape before
they are acknowledged. Invalid message events receive a fixed `400` response,
while signed event types that the adapter does not consume are still
acknowledged for forward compatibility.
New QQ Official bots default to Webhook mode. WebSocket mode remains available
as an explicit adapter setting.

After signing in, open **Settings > IDC Query > QQ callback** to copy the
callback URL for the domain currently serving the WebUI and inspect runtime
readiness. The page distinguishes disabled, WebSocket, ready, and App ID
conflict states and shows content-free callback counters. It never exposes App
Secrets, query tokens, messages, QQ group IDs, or member IDs. The diagnostics
API requires a user login token and rejects API-key and MCP authentication.
Counters are in-memory operational data and reset when the QQ bot restarts.

Open **Settings > IDC Query > Overview** for a read-only production readiness
summary across the enabled QQ bot, callback or WebSocket transport, Plugin
Runtime, bundled IDC plugin, gateway configuration, TLS, optional gateway
token, and recent QQ/IDC activity. Refreshing the summary only reads local
runtime state and does not contact the query gateway or invoke a customer
query. A missing QQ bot, callback conflict, disconnected runtime, unloaded
plugin, or missing gateway URL blocks readiness; missing real traffic and an
optional gateway token are warnings. The summary contains only fixed status
codes and normalized timestamps. It never returns the gateway URL, App ID,
credentials, internal paths, runtime errors, messages, group IDs, or member
IDs, and its endpoint accepts administrator login tokens only.

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
IDC_QUERY_REQUESTS_PER_MINUTE=20
IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES=5
```

These are advanced overrides. The production command works without setting them.

`LANBOT_COMPOSE_PROFILES` is empty by default, so the IDC deployment does not
start the optional Box service or mount the host Docker socket. Set it to `all`
only when sandbox tools and Box-managed skills are intentionally required. If
an older deployment previously started Box, a default one-click upgrade stops
and removes that container without deleting its persisted data directory.

The IDC plugin is installed even when its gateway is not configured. In that
state it can display its command menu, but binding and data queries return a
configuration notice instead of fabricated results. After signing in as an
administrator, open **Settings > IDC Query** to configure the gateway URL,
service token, request timeout, and TLS verification. Saved changes are loaded
by the plugin on the next query without restarting the containers. The same
page configures per-member query and binding-attempt limits and shows the most
recent IDC operation outcomes. Its connection test checks DNS, network, TLS,
timeout, and the gateway's HTTP response without invoking a customer query.
Its **Group bindings** tab shows a read-only, masked inventory of active QQ
group bindings.

The WebUI stores these values in `docker/data/idc-query/config.env` with
owner-only permissions and preserves them on later one-click upgrades. The GET
API only reports whether a token exists; it never returns the token value. The
credential endpoint accepts administrator login tokens only, not API keys or
MCP authentication. The Plugin Runtime reads the mounted file directly because
plugin processes start with a clean environment. The token is not exposed
through Docker container environment metadata and must not be committed.

The plugin appends a bounded audit schema to
`docker/data/idc-query/audit.jsonl`, rotates it at 5 MiB, and keeps three
backups. Audit records contain operation categories, outcomes, QQ identifiers,
member identifiers, request IDs, and duration only. Message text, verification
codes, IP arguments, gateway tokens, and query response data are never logged.
Audit files use owner-only permissions. The audit endpoint has the same
user-login-only authentication boundary as credential configuration.

Active bindings are stored in `docker/data/idc-query/bindings.json`. Writes are
atomic and owner-only; each successful change refreshes
`bindings.json.bak`, which is used only when the primary file is corrupted and
the backup represents a committed state. Both files remain under the preserved
`docker/data` tree during one-click and in-app upgrades. The WebUI does not
offer a local force-delete action because bypassing the query gateway would
leave authorization state inconsistent.

The `IDC_QUERY_*` deployment variables above remain available for unattended
first-time provisioning. Later changes can be made from the WebUI.

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

### Local Data Backup

Create a consistent local-data snapshot:

```bash
/opt/ai-lanbot/scripts/data-backup.sh create /opt/ai-lanbot
```

Backups are written to `/opt/ai-lanbot-backups` by default, outside the managed
source and data trees. Each archive and SHA-256 sidecar is owner-only. The
script records which services were running, stops only those services while
archiving, then restarts them and waits for LangBot's HTTP health check. It
keeps the newest five archives by default; set `LANBOT_BACKUP_KEEP` to a value
from 1 to 100 or `LANBOT_BACKUP_DIR` to an absolute external backup directory.
Symbolic links are preserved for Box/Skill virtual environments, while archive
members nested through a link and device, FIFO, or socket entries are rejected.

Restore a snapshot into the currently installed application version:

```bash
/opt/ai-lanbot/scripts/data-backup.sh restore \
  /opt/ai-lanbot-backups/ai-lanbot-YYYYmmddTHHMMSSZ-000000-REVISION.tar.gz \
  /opt/ai-lanbot
```

Restore verifies the sidecar and archive layout, creates a fresh pre-restore
backup, stages the selected data, and starts the services. If startup or the
health check fails, it puts the untouched pre-restore data back. The deployment
`.env` is archived for disaster-recovery reference but is not applied during a
normal restore, so current ports and container names remain stable.

If both activation and automatic rollback fail at the filesystem level, the
script leaves services stopped and preserves `.restore-current.*` and
`.restore-failed.*` safeguard directories under `docker/` instead of deleting
either data set. The error output prints those exact paths for manual recovery.

This snapshot covers local `docker/data`, including the default SQLite
database, local storage, IDC credentials/state, plugins, and local vector/Box
data. PostgreSQL, S3, remote vector databases, and other external services must
be backed up with their native tools; this script does not claim to snapshot
them. Restore refuses a snapshot configured for an external database unless an
operator explicitly sets `LANBOT_ALLOW_EXTERNAL_RESTORE=true` after completing
the native database restore.
