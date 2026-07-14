#!/usr/bin/env bash
set -Eeuo pipefail

REPO_OWNER="csbsgyl"
REPO_NAME="ai-lanbot"
REPO_BRANCH="${LANBOT_BRANCH:-main}"
REPO_SLUG="${REPO_OWNER}/${REPO_NAME}"
GITHUB_BASE="https://github.com"
GITHUB_ACCELERATOR="https://github.xiaohangyun.org"
DOCKER_ACCELERATOR="https://docker.xiaohangyun.org"
DOCKER_ACCELERATOR_PREFIX="docker.xiaohangyun.org/library/"
DEPLOY_ENVIRONMENT="production"
DEPLOY_MODE="${LANBOT_DEPLOY_MODE:-image}"
ALLOW_BUILD_FALLBACK="${LANBOT_ALLOW_BUILD_FALLBACK:-true}"
SOURCE_MODE="${LANBOT_SOURCE_MODE:-archive}"
COMPOSE_PROFILES="${LANBOT_COMPOSE_PROFILES:-}"
HTTP_PORT="${LANBOT_HTTP_PORT:-5300}"
PUBLIC_URL="${LANBOT_PUBLIC_URL:-https://idc.csbsgyl.com}"
AUTO_BACKUP_BEFORE_UPDATE="${LANBOT_AUTO_BACKUP_BEFORE_UPDATE:-true}"
BACKUP_KEEP="${LANBOT_BACKUP_KEEP:-5}"
BACKUP_DIR="${LANBOT_BACKUP_DIR:-}"
COMPOSE_PROJECT="${LANBOT_COMPOSE_PROJECT_NAME:-docker}"
LANGBOT_CONTAINER_NAME="${LANBOT_CONTAINER_NAME:-langbot}"
PLUGIN_RUNTIME_CONTAINER_NAME="${LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME:-langbot_plugin_runtime}"
BOX_CONTAINER_NAME="${LANBOT_BOX_CONTAINER_NAME:-langbot_box}"
PLUGIN_DEBUG_PORT="${LANBOT_PLUGIN_DEBUG_PORT:-5401}"
REVERSE_PORT_MAPPING="${LANBOT_REVERSE_PORT_MAPPING:-2280-2285:2280-2285}"
TARGET_REVISION="${LANBOT_TARGET_REVISION:-}"
IMAGE_WAIT_SECONDS="${LANBOT_IMAGE_WAIT_SECONDS:-0}"
UPDATE_ENABLED="false"
DEPLOY_LOCK_FD=""
HOST_UPDATER_PATH="/usr/local/libexec/ai-lanbot-host-update"

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  DEFAULT_INSTALL_DIR="/opt/${REPO_NAME}"
else
  DEFAULT_INSTALL_DIR="${HOME}/${REPO_NAME}"
fi

INSTALL_DIR="${LANBOT_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

log() {
  printf '[ai-lanbot] %s\n' "$*"
}

die() {
  printf '[ai-lanbot] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: one-click-deploy.sh [production]

Deploys or updates the production instance. The production argument is
optional; running the script without arguments performs the same deployment.

Advanced LANBOT_* environment variables can override these defaults.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      production|prod|--production)
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1. This script deploys production only."
        ;;
    esac
    shift
  done
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

as_root() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "This step needs root privileges. Install sudo or run as root."
  fi
}

install_root_file_atomically() {
  local source="$1"
  local destination="$2"
  local mode="$3"
  local temporary="${destination}.tmp.$$"

  if ! as_root install -m "$mode" "$source" "$temporary"; then
    as_root rm -f "$temporary" || true
    return 1
  fi
  if ! as_root mv -f "$temporary" "$destination"; then
    as_root rm -f "$temporary" || true
    return 1
  fi
}

acquire_deployment_lock() {
  local lock_file="${INSTALL_DIR}.deploy.lock"

  if ! command -v flock >/dev/null 2>&1; then
    log "The flock command is unavailable; concurrent deployment protection is disabled."
    return 0
  fi

  mkdir -p "$(dirname "$lock_file")"
  if ! exec 9>"$lock_file"; then
    die "Could not open the deployment lock file."
  fi
  chmod 600 "$lock_file"
  flock -n 9 || die "Another deployment or managed update is already running for ${INSTALL_DIR}."
  DEPLOY_LOCK_FD="9"
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return 0
  fi
  return 1
}

compose_with_profiles() {
  local compose
  compose="$(compose_cmd)"
  if [ -n "$COMPOSE_PROFILES" ]; then
    $compose --profile "$COMPOSE_PROFILES" "$@"
  else
    $compose "$@"
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && compose_cmd >/dev/null 2>&1; then
    return 0
  fi

  log "Docker or Docker Compose is missing. Installing with the system package manager."

  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
  else
    die "Cannot detect Linux distribution from /etc/os-release."
  fi

  case "${ID:-}" in
    ubuntu|debian)
      as_root apt-get update
      as_root apt-get install -y ca-certificates curl gnupg
      if ! as_root apt-get install -y docker.io docker-compose-plugin; then
        curl -fsSL https://get.docker.com | as_root sh
      fi
      ;;
    centos|rhel|rocky|almalinux|fedora|amzn)
      local pkg_mgr="yum"
      command -v dnf >/dev/null 2>&1 && pkg_mgr="dnf"
      as_root "$pkg_mgr" install -y docker docker-compose-plugin || curl -fsSL https://get.docker.com | as_root sh
      ;;
    *)
      curl -fsSL https://get.docker.com | as_root sh
      ;;
  esac

  if command -v systemctl >/dev/null 2>&1; then
    as_root systemctl enable --now docker
  else
    as_root service docker start || true
  fi
}

ensure_docker_ready() {
  install_docker
  command -v docker >/dev/null 2>&1 || die "Docker installation did not provide the docker command."
  compose_cmd >/dev/null 2>&1 || die "Docker Compose is not available after Docker installation."

  if ! docker info >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1; then
      as_root systemctl start docker
    fi
  fi

  docker info >/dev/null 2>&1 || die "Docker daemon is not running or current user cannot access it."
}

check_port() {
  if command -v ss >/dev/null 2>&1 && ss -ltn "( sport = :${HTTP_PORT} )" | grep -q ":${HTTP_PORT}"; then
    die "Port ${HTTP_PORT} is already in use. Set LANBOT_HTTP_PORT before running if you need another port."
  fi
}

run_with_timeout() {
  local seconds="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$seconds" "$@"
  else
    "$@"
  fi
}

set_env_key() {
  local file="$1"
  local key="$2"
  local value="$3"
  local escaped

  escaped="$(printf '%s' "$value" | sed 's/[&|]/\\&/g')"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

set_env_key_if_missing() {
  local file="$1"
  local key="$2"
  local value="$3"

  if ! grep -q "^${key}=" "$file"; then
    set_env_key "$file" "$key" "$value"
  fi
}

read_existing_deployment_setting() {
  local key="$1"
  local env_file="${INSTALL_DIR}/docker/.env"

  [ -f "$env_file" ] || return 0
  sed -n "s/^${key}=//p" "$env_file" | tail -n 1
}

reuse_existing_deployment_setting() {
  local environment_name="$1"
  local file_key="$2"
  local target_name="$3"
  local value

  if declare -p "$environment_name" >/dev/null 2>&1; then
    return 0
  fi
  value="$(read_existing_deployment_setting "$file_key")"
  [ -n "$value" ] && printf -v "$target_name" '%s' "$value"
}

load_existing_deployment_settings() {
  local box_enabled

  is_managed_install_dir || return 0
  reuse_existing_deployment_setting "LANBOT_COMPOSE_PROJECT_NAME" "COMPOSE_PROJECT_NAME" "COMPOSE_PROJECT"
  reuse_existing_deployment_setting "LANBOT_HTTP_PORT" "LANGBOT_HTTP_PORT" "HTTP_PORT"
  reuse_existing_deployment_setting "LANBOT_PUBLIC_URL" "LANBOT_PUBLIC_URL" "PUBLIC_URL"
  reuse_existing_deployment_setting \
    "LANBOT_AUTO_BACKUP_BEFORE_UPDATE" "LANBOT_AUTO_BACKUP_BEFORE_UPDATE" "AUTO_BACKUP_BEFORE_UPDATE"
  reuse_existing_deployment_setting "LANBOT_BACKUP_KEEP" "LANBOT_BACKUP_KEEP" "BACKUP_KEEP"
  reuse_existing_deployment_setting "LANBOT_BACKUP_DIR" "LANBOT_BACKUP_DIR" "BACKUP_DIR"
  reuse_existing_deployment_setting "LANBOT_CONTAINER_NAME" "LANBOT_CONTAINER_NAME" "LANGBOT_CONTAINER_NAME"
  reuse_existing_deployment_setting \
    "LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME" "LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME" "PLUGIN_RUNTIME_CONTAINER_NAME"
  reuse_existing_deployment_setting "LANBOT_BOX_CONTAINER_NAME" "LANBOT_BOX_CONTAINER_NAME" "BOX_CONTAINER_NAME"
  reuse_existing_deployment_setting "LANBOT_PLUGIN_DEBUG_PORT" "LANBOT_PLUGIN_DEBUG_PORT" "PLUGIN_DEBUG_PORT"
  reuse_existing_deployment_setting "LANBOT_REVERSE_PORT_MAPPING" "LANBOT_REVERSE_PORT_MAPPING" "REVERSE_PORT_MAPPING"
  reuse_existing_deployment_setting "LANBOT_SOURCE_MODE" "LANBOT_SOURCE_MODE" "SOURCE_MODE"

  if ! declare -p LANBOT_COMPOSE_PROFILES >/dev/null 2>&1; then
    box_enabled="$(read_existing_deployment_setting "LANBOT_BOX_ENABLED")"
    if [ "$box_enabled" = "true" ]; then
      COMPOSE_PROFILES="all"
    elif [ "$box_enabled" = "false" ]; then
      COMPOSE_PROFILES=""
    fi
  fi
  log "Reusing resource settings from the existing managed deployment."
}

validate_public_url() {
  PUBLIC_URL="${PUBLIC_URL%/}"
  if [[ ! "$PUBLIC_URL" =~ ^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:(80|443|8080|8443))?$ ]]; then
    die "LANBOT_PUBLIC_URL must be an HTTPS origin without a path, query, or fragment."
  fi
}

validate_backup_settings() {
  case "$AUTO_BACKUP_BEFORE_UPDATE" in
    true|false) ;;
    *) die "LANBOT_AUTO_BACKUP_BEFORE_UPDATE must be true or false." ;;
  esac
  case "$BACKUP_KEEP" in
    ''|*[!0-9]*) die "LANBOT_BACKUP_KEEP must be an integer between 1 and 100." ;;
  esac
  if [ "$BACKUP_KEEP" -lt 1 ] || [ "$BACKUP_KEEP" -gt 100 ]; then
    die "LANBOT_BACKUP_KEEP must be an integer between 1 and 100."
  fi
  if [ -n "$BACKUP_DIR" ]; then
    case "$BACKUP_DIR" in
      /*) ;;
      *) die "LANBOT_BACKUP_DIR must be an absolute path." ;;
    esac
    case "$BACKUP_DIR" in
      *$'\n'*|*$'\r'*) die "LANBOT_BACKUP_DIR must not contain line breaks." ;;
    esac
  fi
}

install_bundled_plugins() {
  local source_dir="${INSTALL_DIR}/bundled_plugins/idc_query"
  local plugin_dir="${INSTALL_DIR}/docker/data/plugins/idc_query"
  local state_dir="${INSTALL_DIR}/docker/data/idc-query"
  local plugin_parent staged_dir backup_root backup_dir

  [ -f "${source_dir}/manifest.yaml" ] || die "Bundled IDC query plugin is missing from the source tree."
  plugin_parent="$(dirname "$plugin_dir")"
  mkdir -p "$plugin_parent" "$state_dir"
  chmod 700 "$state_dir"
  staged_dir="$(mktemp -d "${plugin_parent}/.idc-query.stage.XXXXXX")"
  if ! cp -a "${source_dir}/." "$staged_dir/"; then
    rm -rf "$staged_dir"
    die "Could not stage the bundled IDC query plugin."
  fi
  chmod 755 "$staged_dir"

  backup_root=""
  if [ -e "$plugin_dir" ] || [ -L "$plugin_dir" ]; then
    backup_root="$(mktemp -d "${plugin_parent}/.idc-query.backup.XXXXXX")"
    backup_dir="${backup_root}/plugin"
    if ! mv "$plugin_dir" "$backup_dir"; then
      rm -rf "$staged_dir" "$backup_root"
      die "Could not preserve the existing IDC query plugin."
    fi
  fi

  if ! mv "$staged_dir" "$plugin_dir"; then
    if [ -n "$backup_root" ]; then
      mv "$backup_dir" "$plugin_dir" || die "IDC plugin activation failed and the previous plugin could not be restored."
      rm -rf "$backup_root"
    fi
    rm -rf "$staged_dir"
    die "Could not activate the bundled IDC query plugin."
  fi

  if [ -n "$backup_root" ]; then
    rm -rf "$backup_root" || log "The previous IDC plugin staging directory could not be removed."
  fi
  log "Installed bundled IDC query plugin."
}

write_idc_query_config() {
  local config_file="${INSTALL_DIR}/docker/data/idc-query/config.env"

  mkdir -p "$(dirname "$config_file")"
  [ -f "$config_file" ] || : > "$config_file"
  set_env_key_if_missing "$config_file" "IDC_QUERY_API_BASE_URL" ""
  set_env_key_if_missing "$config_file" "IDC_QUERY_API_TOKEN" ""
  set_env_key_if_missing "$config_file" "IDC_QUERY_TIMEOUT_SECONDS" "8"
  set_env_key_if_missing "$config_file" "IDC_QUERY_VERIFY_TLS" "true"
  set_env_key_if_missing "$config_file" "IDC_QUERY_REQUESTS_PER_MINUTE" "20"
  set_env_key_if_missing "$config_file" "IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES" "5"
  [ -n "${IDC_QUERY_API_BASE_URL:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_API_BASE_URL" "$IDC_QUERY_API_BASE_URL"
  [ -n "${IDC_QUERY_API_TOKEN:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_API_TOKEN" "$IDC_QUERY_API_TOKEN"
  [ -n "${IDC_QUERY_TIMEOUT_SECONDS:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_TIMEOUT_SECONDS" "$IDC_QUERY_TIMEOUT_SECONDS"
  [ -n "${IDC_QUERY_VERIFY_TLS:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_VERIFY_TLS" "$IDC_QUERY_VERIFY_TLS"
  [ -n "${IDC_QUERY_REQUESTS_PER_MINUTE:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_REQUESTS_PER_MINUTE" "$IDC_QUERY_REQUESTS_PER_MINUTE"
  [ -n "${IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES" "$IDC_QUERY_BIND_ATTEMPTS_PER_10_MINUTES"
  chmod 600 "$config_file"
}

is_managed_install_dir() {
  [ -f "${INSTALL_DIR}/pyproject.toml" ] && [ -d "${INSTALL_DIR}/docker" ] && [ -f "${INSTALL_DIR}/scripts/one-click-deploy.sh" ]
}

is_valid_revision() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
}

revision_from_response() {
  local response="$1"
  local revision

  revision="$(printf '%s' "$response" | tr -d '[:space:]')"
  if is_valid_revision "$revision"; then
    printf '%s' "$revision" | tr '[:upper:]' '[:lower:]'
    return 0
  fi

  revision="$(
    printf '%s\n' "$response" \
      | sed -n 's#.*Grit::Commit/\([0-9a-fA-F]\{40\}\).*#\1#p' \
      | head -n 1
  )"
  if ! is_valid_revision "$revision"; then
    revision="$(
      printf '%s\n' "$response" \
        | sed -n 's/.*"sha"[[:space:]]*:[[:space:]]*"\([0-9a-fA-F]\{40\}\)".*/\1/p' \
        | head -n 1
    )"
  fi
  is_valid_revision "$revision" || return 1
  printf '%s' "$revision" | tr '[:upper:]' '[:lower:]'
}

fetch_revision_url() {
  local url="$1"
  local accept="$2"
  local response

  response="$(
    curl -fsSL \
      -H "Accept: ${accept}" \
      --connect-timeout 8 \
      --max-time 20 \
      --max-filesize 524288 \
      "$url" 2>/dev/null || true
  )"
  revision_from_response "$response"
}

is_safe_systemd_install_dir() {
  [[ "$INSTALL_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    && [[ "/${INSTALL_DIR#/}/" != *"/../"* ]]
}

repository_archive_url() {
  local base_url="$1"

  if [ -n "$TARGET_REVISION" ]; then
    printf '%s/%s/archive/%s.tar.gz' "$base_url" "$REPO_SLUG" "$TARGET_REVISION"
  else
    printf '%s/%s/archive/refs/heads/%s.tar.gz' "$base_url" "$REPO_SLUG" "$REPO_BRANCH"
  fi
}

resolve_target_revision() {
  local api_url atom_url revision url

  if [ -n "$TARGET_REVISION" ]; then
    is_valid_revision "$TARGET_REVISION" || die "LANBOT_TARGET_REVISION must be a 40-character Git commit SHA."
    TARGET_REVISION="$(printf '%s' "$TARGET_REVISION" | tr '[:upper:]' '[:lower:]')"
    return 0
  fi

  atom_url="https://github.com/${REPO_SLUG}/commits/${REPO_BRANCH}.atom"
  for url in "$atom_url" "${GITHUB_ACCELERATOR}/${atom_url}"; do
    if revision="$(fetch_revision_url "$url" 'application/atom+xml')"; then
      TARGET_REVISION="$revision"
      return 0
    fi
  done

  api_url="https://api.github.com/repos/${REPO_SLUG}/commits/${REPO_BRANCH}"
  for url in "$api_url" "${GITHUB_ACCELERATOR}/${api_url}"; do
    if revision="$(fetch_revision_url "$url" 'application/vnd.github.sha')"; then
      TARGET_REVISION="$revision"
      return 0
    fi
  done

  return 1
}

can_use_direct_github() {
  local probe_url
  probe_url="$(repository_archive_url "$GITHUB_BASE")"
  curl -fsL --connect-timeout 8 --max-time 15 --range 0-0 -o /dev/null "$probe_url" >/dev/null 2>&1
}

can_reach_dockerhub() {
  local status
  status="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 8 https://registry-1.docker.io/v2/ || true)"
  [ "$status" = "200" ] || [ "$status" = "401" ]
}

docker_accelerator_has_required_images() {
  curl -fsL --connect-timeout 8 --max-time 20 "${DOCKER_ACCELERATOR}/v2/library/node/tags/list" | grep -q '"22-alpine"' \
    && curl -fsL --connect-timeout 8 --max-time 20 "${DOCKER_ACCELERATOR}/v2/library/python/tags/list" | grep -q '"3.12.7-slim"'
}

docker_accelerator_has_runtime_image() {
  local image_tag="$1"
  curl -fsL --connect-timeout 8 --max-time 20 "${DOCKER_ACCELERATOR}/v2/${REPO_SLUG}/tags/list" \
    | grep -Fq "\"${image_tag}\""
}

image_manifest_available() {
  run_with_timeout 30s docker manifest inspect "$1" >/dev/null 2>&1
}

resolve_runtime_image_once() {
  local candidate dockerhub_image ghcr_image image_tag
  image_tag="${TARGET_REVISION:-latest}"
  dockerhub_image="${REPO_SLUG}:${image_tag}"
  ghcr_image="ghcr.io/${REPO_SLUG}:${image_tag}"

  if can_reach_dockerhub; then
    log "Checking Docker Hub prebuilt image: ${dockerhub_image}" >&2
    if image_manifest_available "$dockerhub_image"; then
      printf '%s' "$dockerhub_image"
      return 0
    fi
  fi

  if docker_accelerator_has_runtime_image "$image_tag"; then
    candidate="${DOCKER_ACCELERATOR#https://}/${dockerhub_image}"
    log "Checking accelerated Docker image: ${candidate}" >&2
    if image_manifest_available "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  fi

  log "Checking GHCR prebuilt image: ${ghcr_image}" >&2
  if image_manifest_available "$ghcr_image"; then
    printf '%s' "$ghcr_image"
    return 0
  fi

  return 1
}

resolve_runtime_image() {
  local deadline remaining wait_for

  if [ -n "${LANBOT_IMAGE:-}" ]; then
    log "Using custom runtime image: ${LANBOT_IMAGE}" >&2
    printf '%s' "$LANBOT_IMAGE"
    return 0
  fi

  if [ "$DEPLOY_MODE" = "build" ]; then
    return 1
  fi

  deadline=$((SECONDS + IMAGE_WAIT_SECONDS))
  while true; do
    if resolve_runtime_image_once; then
      return 0
    fi
    if [ "$IMAGE_WAIT_SECONDS" -eq 0 ] || [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi

    remaining=$((deadline - SECONDS))
    wait_for=30
    [ "$remaining" -lt "$wait_for" ] && wait_for="$remaining"
    log "The revision image is not published yet; checking again in ${wait_for}s." >&2
    sleep "$wait_for"
  done
}

prepare_runtime_image() {
  local runtime_image="$1"

  if [ -n "${LANBOT_IMAGE:-}" ] && docker image inspect "$runtime_image" >/dev/null 2>&1; then
    log "Custom runtime image is already available locally: ${runtime_image}"
    return 0
  fi

  log "Pulling the selected runtime image before changing the managed source tree: ${runtime_image}"
  run_with_timeout 900s docker pull "$runtime_image"
}

resolve_docker_image_prefix() {
  if [ -n "${LANBOT_DOCKER_IMAGE_PREFIX:-}" ]; then
    printf '%s' "$LANBOT_DOCKER_IMAGE_PREFIX"
    return 0
  fi

  if can_reach_dockerhub; then
    log "Docker Hub direct access is available." >&2
    printf ''
    return 0
  fi

  if docker_accelerator_has_required_images; then
    log "Docker Hub direct access is unavailable. Using accelerator: ${DOCKER_ACCELERATOR}" >&2
    printf '%s' "$DOCKER_ACCELERATOR_PREFIX"
    return 0
  fi

  log "Docker Hub direct access failed, but Docker accelerator did not expose required base images. Continuing without a mirror." >&2
  printf ''
}

download_archive() {
  local archive="$1"
  local direct_url accel_url
  direct_url="$(repository_archive_url "$GITHUB_BASE")"
  accel_url="${GITHUB_ACCELERATOR}/${direct_url}"

  if can_use_direct_github; then
    log "GitHub direct download is available."
    curl -fL --retry 3 --connect-timeout 15 --max-time 300 -o "$archive" "$direct_url"
  else
    log "GitHub direct download is unavailable or slow. Using accelerator: ${GITHUB_ACCELERATOR}"
    curl -fL --retry 3 --connect-timeout 15 --max-time 300 -o "$archive" "$accel_url"
  fi
}

download_revision_file() {
  local relative_path="$1"
  local destination="$2"
  local source_ref="${TARGET_REVISION:-$REPO_BRANCH}"
  local direct_url="https://raw.githubusercontent.com/${REPO_SLUG}/${source_ref}/${relative_path}"
  local accel_url="${GITHUB_ACCELERATOR}/${direct_url}"

  if ! curl -fL --retry 3 --connect-timeout 10 --max-time 120 --max-filesize 1048576 \
    -o "$destination" "$direct_url"; then
    curl -fL --retry 3 --connect-timeout 10 --max-time 120 --max-filesize 1048576 \
      -o "$destination" "$accel_url"
  fi
}

create_pre_update_backup() {
  local installed_script="${INSTALL_DIR}/scripts/data-backup.sh"
  local backup_script="$installed_script"
  local temporary_script=""

  [ "$AUTO_BACKUP_BEFORE_UPDATE" = "true" ] || {
    log "Automatic pre-update backup is disabled."
    return 0
  }
  is_managed_install_dir || return 0

  if [ ! -f "$installed_script" ] || ! grep -q 'LANBOT_BACKUP_LOCK_FD' "$installed_script"; then
    temporary_script="$(mktemp)"
    if ! download_revision_file "scripts/data-backup.sh" "$temporary_script" \
      || ! grep -q 'LANBOT_BACKUP_LOCK_FD' "$temporary_script" \
      || ! bash -n "$temporary_script"; then
      [ -z "$temporary_script" ] || rm -f "$temporary_script"
      die "Could not prepare the target revision's data backup tool; the existing deployment was not changed."
    fi
    backup_script="$temporary_script"
  fi

  log "Creating a consistent pre-update data backup."
  if [ -n "$DEPLOY_LOCK_FD" ]; then
    if ! LANBOT_BACKUP_LOCK_FD="$DEPLOY_LOCK_FD" \
      LANBOT_BACKUP_KEEP="$BACKUP_KEEP" \
      LANBOT_BACKUP_DIR="$BACKUP_DIR" \
      bash "$backup_script" create "$INSTALL_DIR"; then
      [ -z "$temporary_script" ] || rm -f "$temporary_script"
      die "Pre-update data backup failed; the existing deployment was not changed."
    fi
  elif ! LANBOT_BACKUP_KEEP="$BACKUP_KEEP" \
    LANBOT_BACKUP_DIR="$BACKUP_DIR" \
    bash "$backup_script" create "$INSTALL_DIR"; then
    [ -z "$temporary_script" ] || rm -f "$temporary_script"
    die "Pre-update data backup failed; the existing deployment was not changed."
  fi
  [ -z "$temporary_script" ] || rm -f "$temporary_script"
}

restore_staged_install() {
  local backup_root="$1"
  local backup_dir="$2"
  local staged_dir="$3"
  local preserved_data="$4"
  local preserved_env="$5"
  local restore_failed="false"

  mkdir -p "${backup_dir}/docker" || restore_failed="true"
  if [ "$preserved_data" = "true" ]; then
    if [ -d "${staged_dir}/docker/data" ]; then
      mv "${staged_dir}/docker/data" "${backup_dir}/docker/data" || restore_failed="true"
    else
      restore_failed="true"
    fi
  fi
  if [ "$preserved_env" = "true" ]; then
    if [ -f "${staged_dir}/docker/.env" ]; then
      mv "${staged_dir}/docker/.env" "${backup_dir}/docker/.env" || restore_failed="true"
    else
      restore_failed="true"
    fi
  fi
  if [ ! -e "$INSTALL_DIR" ] && [ ! -L "$INSTALL_DIR" ]; then
    mv "$backup_dir" "$INSTALL_DIR" || restore_failed="true"
  else
    restore_failed="true"
  fi

  if [ "$restore_failed" = "true" ]; then
    return 1
  fi
  rm -rf "$staged_dir" "$backup_root" || log "Source restore completed, but a staging directory remains."
}

install_from_archive() {
  local tmp_dir archive extracted install_parent staged_dir backup_root backup_dir
  local preserved_data="false"
  local preserved_env="false"

  install_parent="$(dirname "$INSTALL_DIR")"
  mkdir -p "$install_parent"
  tmp_dir="$(mktemp -d)"
  archive="${tmp_dir}/${REPO_NAME}.tar.gz"
  download_archive "$archive"
  if ! tar -xzf "$archive" -C "$tmp_dir"; then
    rm -rf "$tmp_dir"
    die "Downloaded source archive could not be extracted."
  fi
  extracted="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -print -quit)"
  if [ -z "$extracted" ] \
    || [ ! -f "${extracted}/pyproject.toml" ] \
    || [ ! -f "${extracted}/docker/docker-compose.yaml" ] \
    || [ ! -f "${extracted}/scripts/one-click-deploy.sh" ]; then
    rm -rf "$tmp_dir"
    die "Downloaded archive did not contain a valid ai-lanbot source tree."
  fi

  staged_dir="$(mktemp -d "${install_parent}/.${REPO_NAME}.stage.XXXXXX")"
  if ! cp -a "${extracted}/." "$staged_dir/"; then
    rm -rf "$staged_dir" "$tmp_dir"
    die "Could not stage the downloaded source tree."
  fi
  chmod 755 "$staged_dir"
  if [ -e "${staged_dir}/docker/data" ] || [ -e "${staged_dir}/docker/.env" ]; then
    rm -rf "$staged_dir" "$tmp_dir"
    die "Downloaded source archive unexpectedly contained deployment data."
  fi

  if [ -d "$INSTALL_DIR" ] && is_managed_install_dir; then
    log "Activating a staged source tree while preserving docker/data and docker/.env."
    backup_root="$(mktemp -d "${install_parent}/.${REPO_NAME}.backup.XXXXXX")"
    backup_dir="${backup_root}/source"
    if ! mv "$INSTALL_DIR" "$backup_dir"; then
      rm -rf "$staged_dir" "$backup_root" "$tmp_dir"
      die "Could not preserve the existing managed source tree."
    fi

    if [ -d "${backup_dir}/docker/data" ]; then
      if mv "${backup_dir}/docker/data" "${staged_dir}/docker/data"; then
        preserved_data="true"
      else
        if ! restore_staged_install "$backup_root" "$backup_dir" "$staged_dir" "$preserved_data" "$preserved_env"; then
          rm -rf "$tmp_dir"
          die "Data preservation failed and the previous installation could not be restored automatically."
        fi
        rm -rf "$tmp_dir"
        die "Could not preserve the deployment data directory."
      fi
    fi
    if [ -f "${backup_dir}/docker/.env" ]; then
      if mv "${backup_dir}/docker/.env" "${staged_dir}/docker/.env"; then
        preserved_env="true"
      else
        if ! restore_staged_install "$backup_root" "$backup_dir" "$staged_dir" "$preserved_data" "$preserved_env"; then
          rm -rf "$tmp_dir"
          die "Environment preservation failed and the previous installation could not be restored automatically."
        fi
        rm -rf "$tmp_dir"
        die "Could not preserve the deployment environment file."
      fi
    fi

    if ! mv "$staged_dir" "$INSTALL_DIR"; then
      if ! restore_staged_install "$backup_root" "$backup_dir" "$staged_dir" "$preserved_data" "$preserved_env"; then
        rm -rf "$tmp_dir"
        die "Source activation failed and the previous installation could not be restored automatically."
      fi
      rm -rf "$tmp_dir"
      die "Could not activate the staged source tree; the previous installation was restored."
    fi

    rm -rf "$backup_root" || log "The previous source staging directory could not be removed."
  else
    if [ -e "$INSTALL_DIR" ] || [ -L "$INSTALL_DIR" ]; then
      if [ ! -d "$INSTALL_DIR" ] || [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        rm -rf "$staged_dir" "$tmp_dir"
        die "Install directory is not empty and is not an ai-lanbot install: ${INSTALL_DIR}"
      fi
      rmdir "$INSTALL_DIR"
    fi
    if ! mv "$staged_dir" "$INSTALL_DIR"; then
      rm -rf "$staged_dir" "$tmp_dir"
      die "Could not activate the downloaded source tree."
    fi
  fi

  rm -rf "$tmp_dir" || log "The downloaded source temporary directory could not be removed."
}

fetch_source() {
  local repo_url="${GITHUB_BASE}/${REPO_SLUG}.git"
  local source_ref="${TARGET_REVISION:-$REPO_BRANCH}"

  [ ! -L "$INSTALL_DIR" ] || die "Symbolic-link install directories are not supported: ${INSTALL_DIR}"

  if [ -d "${INSTALL_DIR}/.git" ]; then
    is_managed_install_dir || die "Existing Git checkout is not an ai-lanbot install: ${INSTALL_DIR}"
    log "Updating existing checkout at ${INSTALL_DIR}."
    git -C "$INSTALL_DIR" remote set-url origin "$repo_url"
    if run_with_timeout 90s git -C "$INSTALL_DIR" fetch --depth 1 origin "$source_ref" \
      && git -C "$INSTALL_DIR" checkout -B "$REPO_BRANCH" FETCH_HEAD; then
      return 0
    fi
    log "git update failed. Falling back to archive download."
    install_from_archive
    return 0
  fi

  if [ -e "$INSTALL_DIR" ] && [ "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)" -gt 0 ]; then
    if is_managed_install_dir; then
      log "Updating existing archive-based install at ${INSTALL_DIR}."
      install_from_archive
      return 0
    fi
    die "Install directory is not empty and is not an ai-lanbot install: ${INSTALL_DIR}"
  fi

  mkdir -p "$(dirname "$INSTALL_DIR")"

  if [ "$SOURCE_MODE" = "git" ] && [ -z "$TARGET_REVISION" ] && command -v git >/dev/null 2>&1; then
    log "Trying git clone from GitHub."
    if run_with_timeout 90s git clone --depth 1 --branch "$REPO_BRANCH" "$repo_url" "$INSTALL_DIR"; then
      return 0
    fi
    log "git clone failed. Falling back to archive download."
    rm -rf "$INSTALL_DIR"
  fi

  install_from_archive
}

install_host_updater() {
  local template_dir="${INSTALL_DIR}/deploy/systemd"
  local update_dir="${INSTALL_DIR}/docker/data/update"
  local update_request_dir="${INSTALL_DIR}/docker/data/update-request"
  local tmp_dir escaped_install_dir

  UPDATE_ENABLED="false"
  mkdir -p "$update_dir" "$update_request_dir"
  chmod 755 "$update_dir"
  chmod 700 "$update_request_dir"
  if [ ! -f "${update_request_dir}/request.json" ]; then
    printf '{}\n' > "${update_request_dir}/request.json"
  fi
  if [ ! -f "${update_dir}/status.json" ]; then
    printf '{"state":"idle","message":"ready","current_revision":"","target_revision":"","updated_at":""}\n' \
      > "${update_dir}/status.json"
  fi
  chmod 600 "${update_request_dir}/request.json"
  chmod 644 "${update_dir}/status.json"

  if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    log "systemd is unavailable; in-app automatic updates will be disabled."
    return 0
  fi
  if [ -n "${LANBOT_IMAGE:-}" ]; then
    log "A custom runtime image is configured; in-app automatic updates will be disabled."
    return 0
  fi
  if ! is_safe_systemd_install_dir; then
    log "The install path cannot be represented safely in a systemd unit; in-app automatic updates will be disabled."
    return 0
  fi
  if [ ! -f "${template_dir}/ai-lanbot-update.service.in" ] \
    || [ ! -f "${template_dir}/ai-lanbot-update.path.in" ] \
    || [ ! -f "${INSTALL_DIR}/scripts/host-update.sh" ]; then
    log "Managed updater files are missing; in-app automatic updates will be disabled."
    return 0
  fi

  tmp_dir="$(mktemp -d)"
  escaped_install_dir="$(printf '%s' "$INSTALL_DIR" | sed 's/[&|\\]/\\&/g')"
  sed "s|@INSTALL_DIR@|${escaped_install_dir}|g" \
    "${template_dir}/ai-lanbot-update.service.in" > "${tmp_dir}/ai-lanbot-update.service"
  sed "s|@INSTALL_DIR@|${escaped_install_dir}|g" \
    "${template_dir}/ai-lanbot-update.path.in" > "${tmp_dir}/ai-lanbot-update.path"

  if ! as_root install -d -m 0755 "$(dirname "$HOST_UPDATER_PATH")" \
    || ! install_root_file_atomically "${INSTALL_DIR}/scripts/host-update.sh" "$HOST_UPDATER_PATH" 0755 \
    || ! install_root_file_atomically \
      "${tmp_dir}/ai-lanbot-update.service" /etc/systemd/system/ai-lanbot-update.service 0644 \
    || ! install_root_file_atomically \
      "${tmp_dir}/ai-lanbot-update.path" /etc/systemd/system/ai-lanbot-update.path 0644 \
    || ! as_root systemctl daemon-reload \
    || ! as_root systemctl enable --now ai-lanbot-update.path; then
    rm -rf "$tmp_dir"
    log "Could not activate the managed updater; in-app automatic updates will be disabled."
    return 0
  fi

  rm -rf "$tmp_dir"
  UPDATE_ENABLED="true"
  log "Installed the managed in-app updater."
}

write_env() {
  local runtime_image="${1:-}"
  local env_file="${INSTALL_DIR}/docker/.env"
  local docker_image_prefix
  local box_enabled="false"

  mkdir -p "$(dirname "$env_file")"
  [ -f "$env_file" ] || : > "$env_file"

  docker_image_prefix="$(resolve_docker_image_prefix)"
  set_env_key "$env_file" "COMPOSE_PROJECT_NAME" "$COMPOSE_PROJECT"
  set_env_key "$env_file" "LANBOT_ENVIRONMENT" "$DEPLOY_ENVIRONMENT"
  set_env_key "$env_file" "LANGBOT_HTTP_PORT" "$HTTP_PORT"
  set_env_key "$env_file" "LANBOT_PUBLIC_URL" "$PUBLIC_URL"
  set_env_key "$env_file" "LANBOT_AUTO_BACKUP_BEFORE_UPDATE" "$AUTO_BACKUP_BEFORE_UPDATE"
  set_env_key "$env_file" "LANBOT_BACKUP_KEEP" "$BACKUP_KEEP"
  set_env_key "$env_file" "LANBOT_BACKUP_DIR" "$BACKUP_DIR"
  set_env_key "$env_file" "LANGBOT_BOX_ROOT" "${INSTALL_DIR}/docker/data/box"
  set_env_key "$env_file" "LANBOT_CONTAINER_NAME" "$LANGBOT_CONTAINER_NAME"
  set_env_key "$env_file" "LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME" "$PLUGIN_RUNTIME_CONTAINER_NAME"
  set_env_key "$env_file" "LANBOT_BOX_CONTAINER_NAME" "$BOX_CONTAINER_NAME"
  set_env_key "$env_file" "LANBOT_PLUGIN_DEBUG_PORT" "$PLUGIN_DEBUG_PORT"
  set_env_key "$env_file" "LANBOT_REVERSE_PORT_MAPPING" "$REVERSE_PORT_MAPPING"
  if [ "$COMPOSE_PROFILES" = "all" ] || [ "$COMPOSE_PROFILES" = "box" ]; then
    box_enabled="true"
  fi
  set_env_key "$env_file" "LANBOT_BOX_ENABLED" "$box_enabled"
  set_env_key "$env_file" "LANBOT_DEPLOY_MODE" "$DEPLOY_MODE"
  set_env_key "$env_file" "LANBOT_SOURCE_MODE" "$SOURCE_MODE"
  set_env_key "$env_file" "LANBOT_BRANCH" "$REPO_BRANCH"
  set_env_key "$env_file" "LANBOT_DOCKER_IMAGE_PREFIX" "$docker_image_prefix"
  set_env_key "$env_file" "LANBOT_BUILD_REVISION" "$TARGET_REVISION"
  set_env_key "$env_file" "LANBOT_UPDATE_ENABLED" "$UPDATE_ENABLED"
  set_env_key "$env_file" "LANBOT_UPDATE_REPOSITORY" "$REPO_SLUG"
  set_env_key "$env_file" "LANBOT_UPDATE_BRANCH" "$REPO_BRANCH"
  if [ -n "$runtime_image" ]; then
    set_env_key "$env_file" "LANBOT_IMAGE" "$runtime_image"
  fi
  chmod 600 "$env_file"
  write_idc_query_config
}

show_compose_diagnostics() {
  local compose
  compose="$(compose_cmd)"
  cd "${INSTALL_DIR}/docker"
  log "Docker Compose status:"
  compose_with_profiles ps || true
  log "Recent LangBot logs:"
  $compose logs --tail=80 langbot || true
  log "Recent Plugin Runtime logs:"
  $compose logs --tail=80 langbot_plugin_runtime || true
}

wait_for_plugin_runtime() {
  local status

  for _ in $(seq 1 60); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}' \
      "$PLUGIN_RUNTIME_CONTAINER_NAME" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    if [ "$status" = "unhealthy" ]; then
      return 1
    fi
    sleep 2
  done

  return 1
}

remove_disabled_box() {
  local compose

  [ -z "$COMPOSE_PROFILES" ] || return 0
  docker inspect "$BOX_CONTAINER_NAME" >/dev/null 2>&1 || return 0

  compose="$(compose_cmd)"
  cd "${INSTALL_DIR}/docker"
  log "Removing the previously started Box container because Box is disabled."
  if ! $compose --profile all rm -s -f langbot_box; then
    die "The disabled Box container could not be removed."
  fi
}

start_services() {
  local runtime_image="${1:-}"
  local compose
  compose="$(compose_cmd)"
  cd "${INSTALL_DIR}/docker"
  if [ "$DEPLOY_MODE" = "build" ]; then
    log "Building the Plugin Runtime from source."
    if ! $compose -f docker-compose.yaml -f docker-compose.local-build.yaml up -d --build langbot_plugin_runtime; then
      show_compose_diagnostics
      die "Plugin Runtime build/start failed. Deployment was not completed."
    fi
    log "Waiting for the Plugin Runtime health check."
    if ! wait_for_plugin_runtime; then
      show_compose_diagnostics
      die "Plugin Runtime did not become healthy. Deployment was not completed."
    fi
    log "Building and starting the remaining services from source."
    if ! compose_with_profiles -f docker-compose.yaml -f docker-compose.local-build.yaml up -d --build; then
      show_compose_diagnostics
      die "Service build/start failed. Deployment was not completed."
    fi
    return 0
  fi

  log "Starting the Plugin Runtime from prebuilt image: ${runtime_image}"
  if ! $compose -f docker-compose.yaml up -d langbot_plugin_runtime; then
    show_compose_diagnostics
    die "Plugin Runtime start failed. Deployment was not completed."
  fi
  log "Waiting for the Plugin Runtime health check."
  if ! wait_for_plugin_runtime; then
    show_compose_diagnostics
    die "Plugin Runtime did not become healthy. Deployment was not completed."
  fi
  log "Starting the remaining services from prebuilt image: ${runtime_image}"
  if ! compose_with_profiles -f docker-compose.yaml up -d; then
    show_compose_diagnostics
    die "Service start failed. Deployment was not completed."
  fi
}

wait_for_http() {
  local url="$1"

  for _ in $(seq 1 60); do
    if curl -fsS --connect-timeout 2 --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  return 1
}

server_ip() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [ -n "$ip" ]; then
    printf '%s' "$ip"
    return 0
  fi

  ip="$(curl -fsS --connect-timeout 2 --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  printf '%s' "$ip"
}

is_initialized() {
  local base_url="$1"
  local response
  response="$(curl -fsS --connect-timeout 2 --max-time 5 "${base_url}/api/v1/user/init" 2>/dev/null || true)"
  printf '%s' "$response" | grep -q '"initialized"[[:space:]]*:[[:space:]]*true'
}

print_success_info() {
  local local_url="http://127.0.0.1:${HTTP_PORT}"
  local ip remote_url
  ip="$(server_ip)"
  if [ -n "$ip" ]; then
    remote_url="http://${ip}:${HTTP_PORT}"
  else
    remote_url="http://<server-ip>:${HTTP_PORT}"
  fi

  log "Deployment completed and health check passed."
  log "Environment: ${DEPLOY_ENVIRONMENT}"
  log "Install directory: ${INSTALL_DIR}"
  log "Local URL: ${local_url}"
  log "Remote URL: ${remote_url}"
  log "Public URL: ${PUBLIC_URL}"
  log "QQ callback upstream (reverse proxy on this server): ${local_url}"
  log "QQ callback upstream (reverse proxy on another server): ${remote_url}"
  log "QQ callback upstream: ${local_url}/qq/callback"
  log "QQ platform callback after HTTPS proxy: ${PUBLIC_URL}/qq/callback"

  if is_initialized "$local_url"; then
    log "Admin account: already initialized."
    log "Login page: ${remote_url}/login"
  else
    log "Admin account: no default username or password."
    log "First-time setup: ${remote_url}/register"
    log "Create the first administrator account on /register, then use /login."
  fi

  if grep -Eq '^IDC_QUERY_API_BASE_URL=.+$' "${INSTALL_DIR}/docker/data/idc-query/config.env"; then
    log "IDC query plugin: installed and query gateway configured."
  else
    log "IDC query plugin: installed; configure it in WebUI Settings > IDC Query before using queries."
  fi
  if [ "$UPDATE_ENABLED" = "true" ]; then
    log "In-app updates: enabled."
  else
    log "In-app updates: unavailable because the host updater could not be activated."
  fi
  if [ "$AUTO_BACKUP_BEFORE_UPDATE" = "true" ]; then
    log "Pre-update backups: enabled; keep ${BACKUP_KEEP} in ${BACKUP_DIR:-${INSTALL_DIR}-backups}."
  else
    log "Pre-update backups: disabled by LANBOT_AUTO_BACKUP_BEFORE_UPDATE."
  fi

  if [ -n "$COMPOSE_PROFILES" ]; then
    log "Status: cd ${INSTALL_DIR}/docker && $(compose_cmd) --profile ${COMPOSE_PROFILES} ps"
  else
    log "Status: cd ${INSTALL_DIR}/docker && $(compose_cmd) ps"
  fi
  log "Logs: cd ${INSTALL_DIR}/docker && $(compose_cmd) logs -f langbot"
  log "Backup: ${INSTALL_DIR}/scripts/data-backup.sh create ${INSTALL_DIR}"
  log "Restore: ${INSTALL_DIR}/scripts/data-backup.sh restore <archive.tar.gz> ${INSTALL_DIR}"
}

verify_deployment() {
  local health_url="http://127.0.0.1:${HTTP_PORT}/api/v1/system/info"
  log "Waiting for LangBot health check: ${health_url}"
  if ! wait_for_http "$health_url"; then
    show_compose_diagnostics
    die "LangBot did not pass the HTTP health check. Deployment was not completed."
  fi
}

main() {
  local runtime_image=""

  parse_args "$@"
  load_existing_deployment_settings

  [ "$(uname -s)" = "Linux" ] || die "This script supports Linux servers only."
  need_cmd curl
  need_cmd tar

  case "$HTTP_PORT" in
    ''|*[!0-9]*) die "LANBOT_HTTP_PORT must be a numeric TCP port." ;;
  esac
  if [ "$HTTP_PORT" -lt 1 ] || [ "$HTTP_PORT" -gt 65535 ]; then
    die "LANBOT_HTTP_PORT must be between 1 and 65535."
  fi
  validate_public_url
  validate_backup_settings
  case "$IMAGE_WAIT_SECONDS" in
    ''|*[!0-9]*) die "LANBOT_IMAGE_WAIT_SECONDS must be a non-negative integer." ;;
  esac

  if resolve_target_revision; then
    log "Target revision: ${TARGET_REVISION}"
  else
    log "Could not resolve the branch revision; continuing with the latest branch/image reference."
  fi

  log "Deployment environment: ${DEPLOY_ENVIRONMENT}"
  log "Deployment mode: ${DEPLOY_MODE}"
  log "Install directory: ${INSTALL_DIR}"
  log "HTTP port: ${HTTP_PORT}"
  log "Public URL: ${PUBLIC_URL}"

  case "$DEPLOY_MODE" in
    image|build) ;;
    *) die "Unsupported LANBOT_DEPLOY_MODE=${DEPLOY_MODE}. Use image or build." ;;
  esac
  case "$COMPOSE_PROFILES" in
    ''|box|all) ;;
    *) die "Unsupported LANBOT_COMPOSE_PROFILES=${COMPOSE_PROFILES}. Use box, all, or leave it empty." ;;
  esac
  case "$SOURCE_MODE" in
    archive|git) ;;
    *) die "Unsupported LANBOT_SOURCE_MODE=${SOURCE_MODE}. Use archive or git." ;;
  esac

  acquire_deployment_lock

  if [ ! -d "${INSTALL_DIR}/docker" ]; then
    check_port
  fi
  ensure_docker_ready

  if [ "$DEPLOY_MODE" = "image" ]; then
    if ! runtime_image="$(resolve_runtime_image)"; then
      if [ "$ALLOW_BUILD_FALLBACK" = "true" ]; then
        log "No prebuilt image was reachable. Falling back to source build; this can be slow."
        DEPLOY_MODE="build"
      else
        die "No prebuilt image was reachable. Set LANBOT_DEPLOY_MODE=build to build locally."
      fi
    elif ! prepare_runtime_image "$runtime_image"; then
      if [ "$ALLOW_BUILD_FALLBACK" = "true" ]; then
        log "The selected image could not be pulled. Falling back to source build; this can be slow."
        runtime_image=""
        DEPLOY_MODE="build"
      else
        die "The selected prebuilt image could not be pulled; the existing deployment was not changed."
      fi
    fi
  fi

  create_pre_update_backup
  fetch_source
  install_bundled_plugins
  install_host_updater

  write_env "$runtime_image"
  remove_disabled_box
  start_services "$runtime_image"
  verify_deployment
  print_success_info
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
