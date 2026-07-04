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

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  DEFAULT_INSTALL_DIR="/opt/${REPO_NAME}"
else
  DEFAULT_INSTALL_DIR="${HOME}/${REPO_NAME}"
fi

INSTALL_DIR="${LANBOT_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
COMPOSE_PROFILES="${LANBOT_COMPOSE_PROFILES:-all}"
HTTP_PORT="${LANBOT_HTTP_PORT:-5300}"

log() {
  printf '[ai-lanbot] %s\n' "$*"
}

die() {
  printf '[ai-lanbot] ERROR: %s\n' "$*" >&2
  exit 1
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

  if command -v git >/dev/null 2>&1; then
    log "Trying git clone from GitHub."
    if run_with_timeout 90s git clone --depth 1 --branch "$REPO_BRANCH" "$repo_url" "$INSTALL_DIR"; then
      return 0
    fi
    log "git clone failed. Falling back to archive download."
  fi

  install_from_archive
}

write_env() {
  local env_file="${INSTALL_DIR}/docker/.env"
  local docker_image_prefix
  docker_image_prefix="$(resolve_docker_image_prefix)"
  if [ ! -f "$env_file" ]; then
    cat > "$env_file" <<EOF
LANGBOT_HTTP_PORT=${HTTP_PORT}
LANGBOT_BOX_ROOT=${INSTALL_DIR}/docker/data/box
LANBOT_DOCKER_IMAGE_PREFIX=${docker_image_prefix}
EOF
  elif grep -q '^LANBOT_DOCKER_IMAGE_PREFIX=' "$env_file"; then
    sed -i "s|^LANBOT_DOCKER_IMAGE_PREFIX=.*|LANBOT_DOCKER_IMAGE_PREFIX=${docker_image_prefix}|" "$env_file"
  else
    printf '\nLANBOT_DOCKER_IMAGE_PREFIX=%s\n' "$docker_image_prefix" >> "$env_file"
  fi
}

start_services() {
  local compose
  compose="$(compose_cmd)"
  cd "${INSTALL_DIR}/docker"
  log "Building and starting services. This can take several minutes on the first run."
  $compose -f docker-compose.yaml -f docker-compose.local-build.yaml --profile "$COMPOSE_PROFILES" up -d --build
}

main() {
  [ "$(uname -s)" = "Linux" ] || die "This script supports Linux servers only."
  need_cmd curl
  need_cmd tar

  if [ ! -d "${INSTALL_DIR}/docker" ]; then
    check_port
  fi
  ensure_docker_ready
  fetch_source
  write_env
  start_services

  log "Deployment completed."
  log "Open: http://127.0.0.1:${HTTP_PORT}"
  log "If this is a remote server, open: http://<server-ip>:${HTTP_PORT}"
  log "View logs: cd ${INSTALL_DIR}/docker && $(compose_cmd) logs -f langbot"
}

main "$@"
