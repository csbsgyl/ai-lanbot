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
DOCKERHUB_IMAGE="${REPO_SLUG}:latest"
GHCR_IMAGE="ghcr.io/${REPO_SLUG}:latest"
DEPLOY_ENVIRONMENT="${LANBOT_ENVIRONMENT:-production}"
DEPLOY_MODE="${LANBOT_DEPLOY_MODE:-}"
ALLOW_BUILD_FALLBACK="${LANBOT_ALLOW_BUILD_FALLBACK:-true}"
SOURCE_MODE="${LANBOT_SOURCE_MODE:-archive}"
INSTALL_DIR="${LANBOT_INSTALL_DIR:-}"
COMPOSE_PROFILES="${LANBOT_COMPOSE_PROFILES:-}"
HTTP_PORT="${LANBOT_HTTP_PORT:-}"
COMPOSE_PROJECT="${LANBOT_COMPOSE_PROJECT_NAME:-}"
LANGBOT_CONTAINER_NAME="${LANBOT_CONTAINER_NAME:-}"
PLUGIN_RUNTIME_CONTAINER_NAME="${LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME:-}"
BOX_CONTAINER_NAME="${LANBOT_BOX_CONTAINER_NAME:-}"
PLUGIN_DEBUG_PORT="${LANBOT_PLUGIN_DEBUG_PORT:-}"
REVERSE_PORT_MAPPING="${LANBOT_REVERSE_PORT_MAPPING:-}"

log() {
  printf '[ai-lanbot] %s\n' "$*"
}

die() {
  printf '[ai-lanbot] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: one-click-deploy.sh [test|production]

  test        Isolated test deployment. Builds the latest source locally.
              Defaults: /opt/ai-lanbot-test, HTTP 5301.
  production  Production deployment. Uses a prebuilt image when available.
              Defaults: /opt/ai-lanbot, HTTP 5300. This is the default.

Advanced LANBOT_* environment variables can override these defaults.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      test|testing|--test)
        DEPLOY_ENVIRONMENT="test"
        ;;
      production|prod|--production)
        DEPLOY_ENVIRONMENT="production"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1. Use test, production, or --help."
        ;;
    esac
    shift
  done
}

configure_deployment() {
  local install_root

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    install_root="/opt"
  else
    install_root="${HOME}"
  fi

  case "$DEPLOY_ENVIRONMENT" in
    test|testing)
      DEPLOY_ENVIRONMENT="test"
      [ -n "$INSTALL_DIR" ] || INSTALL_DIR="${install_root}/${REPO_NAME}-test"
      [ -n "$DEPLOY_MODE" ] || DEPLOY_MODE="build"
      [ -n "$HTTP_PORT" ] || HTTP_PORT="5301"
      [ -n "$COMPOSE_PROJECT" ] || COMPOSE_PROJECT="ai-lanbot-test"
      [ -n "$LANGBOT_CONTAINER_NAME" ] || LANGBOT_CONTAINER_NAME="langbot_test"
      [ -n "$PLUGIN_RUNTIME_CONTAINER_NAME" ] || PLUGIN_RUNTIME_CONTAINER_NAME="langbot_plugin_runtime_test"
      [ -n "$BOX_CONTAINER_NAME" ] || BOX_CONTAINER_NAME="langbot_box_test"
      [ -n "$PLUGIN_DEBUG_PORT" ] || PLUGIN_DEBUG_PORT="5402"
      [ -n "$REVERSE_PORT_MAPPING" ] || REVERSE_PORT_MAPPING="3280-3285:2280-2285"
      ;;
    production|prod)
      DEPLOY_ENVIRONMENT="production"
      [ -n "$INSTALL_DIR" ] || INSTALL_DIR="${install_root}/${REPO_NAME}"
      [ -n "$DEPLOY_MODE" ] || DEPLOY_MODE="image"
      [ -n "$HTTP_PORT" ] || HTTP_PORT="5300"
      [ -n "$COMPOSE_PROJECT" ] || COMPOSE_PROJECT="docker"
      [ -n "$LANGBOT_CONTAINER_NAME" ] || LANGBOT_CONTAINER_NAME="langbot"
      [ -n "$PLUGIN_RUNTIME_CONTAINER_NAME" ] || PLUGIN_RUNTIME_CONTAINER_NAME="langbot_plugin_runtime"
      [ -n "$BOX_CONTAINER_NAME" ] || BOX_CONTAINER_NAME="langbot_box"
      [ -n "$PLUGIN_DEBUG_PORT" ] || PLUGIN_DEBUG_PORT="5401"
      [ -n "$REVERSE_PORT_MAPPING" ] || REVERSE_PORT_MAPPING="2280-2285:2280-2285"
      ;;
    *)
      die "Unsupported deployment environment: ${DEPLOY_ENVIRONMENT}. Use test or production."
      ;;
  esac
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

install_bundled_plugins() {
  local source_dir="${INSTALL_DIR}/bundled_plugins/idc_query"
  local plugin_dir="${INSTALL_DIR}/docker/data/plugins/idc_query"
  local state_dir="${INSTALL_DIR}/docker/data/idc-query"

  [ -f "${source_dir}/manifest.yaml" ] || die "Bundled IDC query plugin is missing from the source tree."
  mkdir -p "$(dirname "$plugin_dir")" "$state_dir"
  rm -rf "$plugin_dir"
  mkdir -p "$plugin_dir"
  cp -a "${source_dir}/." "$plugin_dir/"
  chmod 700 "$state_dir"
  log "Installed bundled IDC query plugin."
}

write_idc_query_config() {
  local config_file="${INSTALL_DIR}/docker/data/idc-query/config.env"

  mkdir -p "$(dirname "$config_file")"
  [ -f "$config_file" ] || : > "$config_file"
  set_env_key_if_missing "$config_file" "IDC_QUERY_API_BASE_URL" ""
  set_env_key_if_missing "$config_file" "IDC_QUERY_API_TOKEN" ""
  [ -n "${IDC_QUERY_API_BASE_URL:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_API_BASE_URL" "$IDC_QUERY_API_BASE_URL"
  [ -n "${IDC_QUERY_API_TOKEN:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_API_TOKEN" "$IDC_QUERY_API_TOKEN"
  [ -n "${IDC_QUERY_TIMEOUT_SECONDS:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_TIMEOUT_SECONDS" "$IDC_QUERY_TIMEOUT_SECONDS"
  [ -n "${IDC_QUERY_VERIFY_TLS:-}" ] \
    && set_env_key "$config_file" "IDC_QUERY_VERIFY_TLS" "$IDC_QUERY_VERIFY_TLS"
  chmod 600 "$config_file"
}

is_managed_install_dir() {
  [ -f "${INSTALL_DIR}/pyproject.toml" ] && [ -d "${INSTALL_DIR}/docker" ] && [ -f "${INSTALL_DIR}/scripts/one-click-deploy.sh" ]
}

can_use_direct_github() {
  local probe_url="${GITHUB_BASE}/${REPO_SLUG}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
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
  curl -fsL --connect-timeout 8 --max-time 20 "${DOCKER_ACCELERATOR}/v2/${REPO_SLUG}/tags/list" | grep -q '"latest"'
}

image_manifest_available() {
  run_with_timeout 30s docker manifest inspect "$1" >/dev/null 2>&1
}

resolve_runtime_image() {
  local candidate

  if [ -n "${LANBOT_IMAGE:-}" ]; then
    log "Using custom runtime image: ${LANBOT_IMAGE}" >&2
    printf '%s' "$LANBOT_IMAGE"
    return 0
  fi

  if [ "$DEPLOY_MODE" = "build" ]; then
    return 1
  fi

  if can_reach_dockerhub; then
    log "Checking Docker Hub prebuilt image: ${DOCKERHUB_IMAGE}" >&2
    if image_manifest_available "$DOCKERHUB_IMAGE"; then
      printf '%s' "$DOCKERHUB_IMAGE"
      return 0
    fi
  fi

  if docker_accelerator_has_runtime_image; then
    candidate="${DOCKER_ACCELERATOR#https://}/${DOCKERHUB_IMAGE}"
    log "Checking accelerated Docker image: ${candidate}" >&2
    if image_manifest_available "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  fi

  log "Checking GHCR prebuilt image: ${GHCR_IMAGE}" >&2
  if image_manifest_available "$GHCR_IMAGE"; then
    printf '%s' "$GHCR_IMAGE"
    return 0
  fi

  return 1
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
  local direct_url="${GITHUB_BASE}/${REPO_SLUG}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
  local accel_url="${GITHUB_ACCELERATOR}/${direct_url}"

  if can_use_direct_github; then
    log "GitHub direct download is available."
    curl -fL --retry 3 --connect-timeout 15 --max-time 300 -o "$archive" "$direct_url"
  else
    log "GitHub direct download is unavailable or slow. Using accelerator: ${GITHUB_ACCELERATOR}"
    curl -fL --retry 3 --connect-timeout 15 --max-time 300 -o "$archive" "$accel_url"
  fi
}

install_from_archive() {
  local tmp_dir archive extracted backup_dir
  tmp_dir="$(mktemp -d)"
  archive="${tmp_dir}/${REPO_NAME}.tar.gz"
  download_archive "$archive"
  tar -xzf "$archive" -C "$tmp_dir"
  extracted="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ -n "$extracted" ] || die "Downloaded archive did not contain a source directory."

  if [ -d "$INSTALL_DIR" ] && is_managed_install_dir; then
    log "Replacing managed source tree while preserving docker/data and docker/.env."
    backup_dir="$(mktemp -d)"
    mkdir -p "${backup_dir}/docker"
    [ -d "${INSTALL_DIR}/docker/data" ] && mv "${INSTALL_DIR}/docker/data" "${backup_dir}/docker/data"
    [ -f "${INSTALL_DIR}/docker/.env" ] && mv "${INSTALL_DIR}/docker/.env" "${backup_dir}/docker/.env"
    find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  else
    backup_dir=""
    mkdir -p "$INSTALL_DIR"
  fi

  shopt -s dotglob
  mv "${extracted}"/* "$INSTALL_DIR"/
  shopt -u dotglob

  if [ -n "$backup_dir" ]; then
    mkdir -p "${INSTALL_DIR}/docker"
    [ -d "${backup_dir}/docker/data" ] && mv "${backup_dir}/docker/data" "${INSTALL_DIR}/docker/data"
    [ -f "${backup_dir}/docker/.env" ] && mv "${backup_dir}/docker/.env" "${INSTALL_DIR}/docker/.env"
    rm -rf "$backup_dir"
  fi

  rm -rf "$tmp_dir"
}

fetch_source() {
  local repo_url="${GITHUB_BASE}/${REPO_SLUG}.git"

  if [ -d "${INSTALL_DIR}/.git" ]; then
    log "Updating existing checkout at ${INSTALL_DIR}."
    git -C "$INSTALL_DIR" remote set-url origin "$repo_url"
    if run_with_timeout 90s git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_BRANCH" \
      && git -C "$INSTALL_DIR" checkout -B "$REPO_BRANCH" "origin/${REPO_BRANCH}"; then
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

  if [ "$SOURCE_MODE" = "git" ] && command -v git >/dev/null 2>&1; then
    log "Trying git clone from GitHub."
    if run_with_timeout 90s git clone --depth 1 --branch "$REPO_BRANCH" "$repo_url" "$INSTALL_DIR"; then
      return 0
    fi
    log "git clone failed. Falling back to archive download."
    rm -rf "$INSTALL_DIR"
  fi

  install_from_archive
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
  set_env_key "$env_file" "LANBOT_DOCKER_IMAGE_PREFIX" "$docker_image_prefix"
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
    log "IDC query plugin: installed; configure docker/data/idc-query/config.env before using queries."
  fi

  if [ -n "$COMPOSE_PROFILES" ]; then
    log "Status: cd ${INSTALL_DIR}/docker && $(compose_cmd) --profile ${COMPOSE_PROFILES} ps"
  else
    log "Status: cd ${INSTALL_DIR}/docker && $(compose_cmd) ps"
  fi
  log "Logs: cd ${INSTALL_DIR}/docker && $(compose_cmd) logs -f langbot"
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
  configure_deployment

  [ "$(uname -s)" = "Linux" ] || die "This script supports Linux servers only."
  need_cmd curl
  need_cmd tar

  case "$HTTP_PORT" in
    ''|*[!0-9]*) die "LANBOT_HTTP_PORT must be a numeric TCP port." ;;
  esac
  if [ "$HTTP_PORT" -lt 1 ] || [ "$HTTP_PORT" -gt 65535 ]; then
    die "LANBOT_HTTP_PORT must be between 1 and 65535."
  fi

  log "Deployment environment: ${DEPLOY_ENVIRONMENT}"
  log "Deployment mode: ${DEPLOY_MODE}"
  log "Install directory: ${INSTALL_DIR}"
  log "HTTP port: ${HTTP_PORT}"

  case "$DEPLOY_MODE" in
    image|build) ;;
    *) die "Unsupported LANBOT_DEPLOY_MODE=${DEPLOY_MODE}. Use image or build." ;;
  esac
  case "$COMPOSE_PROFILES" in
    ''|box|all) ;;
    *) die "Unsupported LANBOT_COMPOSE_PROFILES=${COMPOSE_PROFILES}. Use box, all, or leave it empty." ;;
  esac

  if [ ! -d "${INSTALL_DIR}/docker" ]; then
    check_port
  fi
  ensure_docker_ready
  fetch_source
  install_bundled_plugins

  if [ "$DEPLOY_MODE" = "image" ]; then
    if ! runtime_image="$(resolve_runtime_image)"; then
      if [ "$ALLOW_BUILD_FALLBACK" = "true" ]; then
        log "No prebuilt image was reachable. Falling back to source build; this can be slow."
        DEPLOY_MODE="build"
      else
        die "No prebuilt image was reachable. Set LANBOT_DEPLOY_MODE=build to build locally."
      fi
    fi
  fi

  write_env "$runtime_image"
  remove_disabled_box
  start_services "$runtime_image"
  verify_deployment
  print_success_info
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
