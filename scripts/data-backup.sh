#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_INSTALL_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
INSTALL_DIR=""
BACKUP_DIR=""
BACKUP_KEEP="${LANBOT_BACKUP_KEEP:-5}"
SERVICES_STOPPED="false"
AUTO_RESTART_SERVICES="true"
RUNNING_SERVICES=()
COMPOSE_COMMAND=()
TEMP_PATHS=()
LAST_BACKUP=""
INCOMPLETE_ARCHIVE=""
ORIGINAL_DATA_MOVED="false"
ORIGINAL_DATA_ROOT=""
FAILED_DATA_ROOT=""

log() {
  printf '[ai-lanbot-backup] %s\n' "$*"
}

die() {
  printf '[ai-lanbot-backup] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  data-backup.sh create [install-dir]
  data-backup.sh restore <archive.tar.gz> [install-dir]

Creates or restores a stopped-service snapshot of docker/data. Backups default
to a sibling directory named <install-dir>-backups.
EOF
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

initialize_paths() {
  local requested_install_dir="${1:-$DEFAULT_INSTALL_DIR}"
  local requested_backup_dir backup_dir_created="false"

  [ -d "$requested_install_dir" ] || die "Install directory does not exist."
  INSTALL_DIR="$(cd -- "$requested_install_dir" && pwd -P)"
  if [ ! -f "${INSTALL_DIR}/pyproject.toml" ] \
    || [ ! -f "${INSTALL_DIR}/docker/docker-compose.yaml" ] \
    || [ ! -f "${INSTALL_DIR}/scripts/data-backup.sh" ]; then
    die "Install directory is not a managed ai-lanbot deployment."
  fi
  [ -d "${INSTALL_DIR}/docker/data" ] || die "Deployment data directory does not exist."
  [ -f "${INSTALL_DIR}/docker/.env" ] || die "Deployment environment file does not exist."

  case "$BACKUP_KEEP" in
    ''|*[!0-9]*) die "LANBOT_BACKUP_KEEP must be an integer between 1 and 100." ;;
  esac
  if [ "$BACKUP_KEEP" -lt 1 ] || [ "$BACKUP_KEEP" -gt 100 ]; then
    die "LANBOT_BACKUP_KEEP must be an integer between 1 and 100."
  fi

  requested_backup_dir="${LANBOT_BACKUP_DIR:-${INSTALL_DIR}-backups}"
  case "$requested_backup_dir" in
    /*) ;;
    *) die "LANBOT_BACKUP_DIR must be an absolute path." ;;
  esac
  [ "$requested_backup_dir" != "/" ] || die "LANBOT_BACKUP_DIR cannot be the filesystem root."
  if [ ! -d "$requested_backup_dir" ]; then
    mkdir -p "$requested_backup_dir"
    backup_dir_created="true"
  fi
  BACKUP_DIR="$(cd -- "$requested_backup_dir" && pwd -P)"
  [ "$BACKUP_DIR" != "/" ] || die "LANBOT_BACKUP_DIR cannot resolve to the filesystem root."
  case "${BACKUP_DIR}/" in
    "${INSTALL_DIR}/"*) die "Backup directory must be outside the managed install directory." ;;
  esac
  [ "$backup_dir_created" = "false" ] || chmod 700 "$BACKUP_DIR"
}

acquire_backup_lock() {
  need_cmd flock
  if ! exec 8>"${INSTALL_DIR}.deploy.lock"; then
    die "Could not open the deployment lock file."
  fi
  chmod 600 "${INSTALL_DIR}.deploy.lock"
  flock -n 8 || die "A deployment, update, backup, or restore is already running."
}

resolve_compose_command() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_COMMAND=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_COMMAND=(docker-compose)
  else
    die "Docker Compose is unavailable."
  fi
}

capture_running_services() {
  local output service
  cd "${INSTALL_DIR}/docker"
  if ! output="$("${COMPOSE_COMMAND[@]}" --profile all ps --services --filter status=running)"; then
    die "Could not inspect running Docker Compose services."
  fi
  RUNNING_SERVICES=()
  while IFS= read -r service; do
    [ -n "$service" ] && RUNNING_SERVICES+=("$service")
  done <<< "$output"
}

stop_running_services() {
  [ "${#RUNNING_SERVICES[@]}" -gt 0 ] || return 0
  cd "${INSTALL_DIR}/docker"
  log "Stopping running services for a consistent local-data snapshot."
  SERVICES_STOPPED="true"
  "${COMPOSE_COMMAND[@]}" --profile all stop "${RUNNING_SERVICES[@]}"
}

restart_running_services() {
  [ "$SERVICES_STOPPED" = "true" ] || return 0
  [ "$AUTO_RESTART_SERVICES" = "true" ] || return 1
  [ -d "${INSTALL_DIR}/docker/data" ] || return 1
  if [ "${#RUNNING_SERVICES[@]}" -eq 0 ]; then
    SERVICES_STOPPED="false"
    return 0
  fi
  cd "${INSTALL_DIR}/docker"
  log "Restarting services."
  if "${COMPOSE_COMMAND[@]}" --profile all start "${RUNNING_SERVICES[@]}"; then
    SERVICES_STOPPED="false"
    return 0
  fi
  return 1
}

service_was_running() {
  local expected="$1"
  local service
  for service in "${RUNNING_SERVICES[@]}"; do
    [ "$service" = "$expected" ] && return 0
  done
  return 1
}

read_env_key() {
  local key="$1"
  sed -n "s/^${key}=//p" "${INSTALL_DIR}/docker/.env" | tail -n 1
}

wait_for_http() {
  local http_port health_url attempt
  service_was_running "langbot" || return 0
  http_port="$(read_env_key "LANGBOT_HTTP_PORT")"
  http_port="${http_port:-5300}"
  health_url="http://127.0.0.1:${http_port}/api/v1/system/info"
  for ((attempt = 0; attempt < 60; attempt++)); do
    if curl -fsS --connect-timeout 2 --max-time 5 "$health_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

ensure_backup_capacity() {
  local required_kib available_kib
  required_kib="$(du -sk "${INSTALL_DIR}/docker/data" | awk '{print $1}')"
  available_kib="$(df -Pk "$BACKUP_DIR" | awk 'NR == 2 {print $4}')"
  case "$required_kib:$available_kib" in
    *[!0-9:]*) die "Could not determine backup disk capacity." ;;
  esac
  if [ "$available_kib" -lt $((required_kib + 65536)) ]; then
    die "Backup directory does not have enough free space for a conservative snapshot."
  fi
}

ensure_local_data_is_archive_safe() {
  local unsafe_path
  unsafe_path="$(find "${INSTALL_DIR}/docker/data" ! -type d ! -type f ! -type l -print -quit)"
  [ -z "$unsafe_path" ] \
    || die "Local data contains an unsupported special file: ${unsafe_path}"
}

ensure_restore_capacity() {
  local archive_path="$1"
  local current_kib archive_bytes archive_kib available_kib
  current_kib="$(du -sk "${INSTALL_DIR}/docker/data" | awk '{print $1}')"
  archive_bytes="$(gzip -cd -- "$archive_path" | wc -c | awk '{print $1}')"
  available_kib="$(df -Pk "${INSTALL_DIR}/docker" | awk 'NR == 2 {print $4}')"
  case "$current_kib:$archive_bytes:$available_kib" in
    *[!0-9:]*) die "Could not determine restore disk capacity." ;;
  esac
  archive_kib=$(((archive_bytes + 1023) / 1024))
  if [ "$available_kib" -lt $((current_kib + archive_kib + 65536)) ]; then
    die "Install filesystem does not have enough free space to stage and safeguard the restore."
  fi
}

track_temp_path() {
  TEMP_PATHS+=("$1")
}

untrack_temp_path() {
  local expected="$1"
  local remaining=()
  local path
  for path in "${TEMP_PATHS[@]}"; do
    [ "$path" = "$expected" ] || remaining+=("$path")
  done
  TEMP_PATHS=("${remaining[@]}")
}

cleanup() {
  local exit_code="$?"
  local path
  trap - EXIT
  if [ "$ORIGINAL_DATA_MOVED" = "true" ]; then
    log "Recovering pre-restore data after an interrupted or failed restore."
    if ! rollback_restored_data; then
      AUTO_RESTART_SERVICES="false"
      exit_code=1
      printf '[ai-lanbot-backup] ERROR: Automatic data recovery failed; preserved safeguards under %s and %s.\n' \
        "$ORIGINAL_DATA_ROOT" "$FAILED_DATA_ROOT" >&2
    fi
  fi
  if [ "$SERVICES_STOPPED" = "true" ] && [ "$AUTO_RESTART_SERVICES" = "true" ]; then
    restart_running_services || exit_code=1
  fi
  if [ -n "$INCOMPLETE_ARCHIVE" ]; then
    rm -f -- "$INCOMPLETE_ARCHIVE" "${INCOMPLETE_ARCHIVE}.sha256"
  fi
  for path in "${TEMP_PATHS[@]}"; do
    case "$path" in
      "${BACKUP_DIR}/."*|"${INSTALL_DIR}/docker/.restore-"*) rm -rf -- "$path" ;;
    esac
  done
  exit "$exit_code"
}

backup_revision() {
  local revision
  revision="$(read_env_key "LANBOT_BUILD_REVISION")"
  if [[ "$revision" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s' "${revision,,}"
  else
    printf 'unknown'
  fi
}

is_backup_archive_name() {
  local archive_name="$1"
  [[ "$archive_name" =~ ^ai-lanbot-[0-9]{8}T[0-9]{6}Z-[0-9]{6}-([0-9a-f]{12}|unknown)\.tar\.gz$ ]]
}

prune_backups() {
  local preserve_archive="${1:-}"
  local candidates=()
  local archives=()
  local allowed_count remove_count removed=0 archive
  shopt -s nullglob
  candidates=("${BACKUP_DIR}"/ai-lanbot-*.tar.gz)
  shopt -u nullglob
  for archive in "${candidates[@]}"; do
    is_backup_archive_name "$(basename -- "$archive")" && archives+=("$archive")
  done

  allowed_count="$BACKUP_KEEP"
  for archive in "${archives[@]}"; do
    if [ -n "$preserve_archive" ] && [ "$archive" = "$preserve_archive" ]; then
      allowed_count=$((allowed_count + 1))
      break
    fi
  done
  remove_count=$((${#archives[@]} - allowed_count))
  [ "$remove_count" -gt 0 ] || return 0
  for archive in "${archives[@]}"; do
    [ "$removed" -lt "$remove_count" ] || break
    [ -n "$preserve_archive" ] && [ "$archive" = "$preserve_archive" ] && continue
    rm -f -- "$archive" "${archive}.sha256"
    removed=$((removed + 1))
  done
}

create_archive() {
  local preserve_archive="${1:-}"
  local timestamp revision short_revision sequence archive_name archive_path temporary_archive counter=0 existing_counter
  local manifest_dir manifest_file temporary_checksum
  local existing_slots=()
  timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
  revision="$(backup_revision)"
  short_revision="${revision:0:12}"
  shopt -s nullglob
  existing_slots=(
    "${BACKUP_DIR}/ai-lanbot-${timestamp}-"*.tar.gz
    "${BACKUP_DIR}/ai-lanbot-${timestamp}-"*.tar.gz.sha256
  )
  shopt -u nullglob
  for archive_path in "${existing_slots[@]}"; do
    if [[ "$(basename -- "$archive_path")" =~ ^ai-lanbot-${timestamp}-([0-9]{6})- ]]; then
      existing_counter=$((10#${BASH_REMATCH[1]} + 1))
      [ "$existing_counter" -le "$counter" ] || counter="$existing_counter"
    fi
  done
  [ "$counter" -le 999999 ] || die "Could not allocate a unique backup archive name."
  printf -v sequence '%06d' "$counter"
  archive_name="ai-lanbot-${timestamp}-${sequence}-${short_revision}.tar.gz"
  archive_path="${BACKUP_DIR}/${archive_name}"
  temporary_archive="${BACKUP_DIR}/.${archive_name}.tmp"
  manifest_dir="$(mktemp -d "${BACKUP_DIR}/.manifest.XXXXXX")"
  manifest_file="${manifest_dir}/backup-manifest.env"
  temporary_checksum="${BACKUP_DIR}/.${archive_name}.sha256.tmp"
  track_temp_path "$temporary_archive"
  track_temp_path "$manifest_dir"
  track_temp_path "$temporary_checksum"

  printf 'FORMAT_VERSION=1\nCREATED_AT=%s\nSOURCE_REVISION=%s\n' \
    "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$revision" > "$manifest_file"
  chmod 600 "$manifest_file"
  tar --hard-dereference -czf "$temporary_archive" \
    -C "$INSTALL_DIR" docker/data docker/.env \
    -C "$manifest_dir" backup-manifest.env
  chmod 600 "$temporary_archive"
  printf '%s  %s\n' "$(sha256sum "$temporary_archive" | awk '{print $1}')" "$archive_name" \
    > "$temporary_checksum"
  chmod 600 "$temporary_checksum"
  INCOMPLETE_ARCHIVE="$archive_path"
  mv "$temporary_archive" "$archive_path"
  untrack_temp_path "$temporary_archive"
  mv "$temporary_checksum" "${archive_path}.sha256"
  untrack_temp_path "$temporary_checksum"
  INCOMPLETE_ARCHIVE=""
  rm -rf "$manifest_dir"
  untrack_temp_path "$manifest_dir"
  prune_backups "$preserve_archive"
  LAST_BACKUP="$archive_path"
}

normalize_archive_path() {
  local requested="$1"
  local parent base
  parent="$(dirname -- "$requested")"
  base="$(basename -- "$requested")"
  [ -d "$parent" ] || die "Backup archive directory does not exist."
  printf '%s/%s' "$(cd -- "$parent" && pwd -P)" "$base"
}

verify_archive() {
  local archive_path="$1"
  local archive_name checksum_file expected_hash actual_hash referenced_name
  local member_listing verbose_listing member normalized_member verbose_line member_type symlink_member index
  local found_data="false" found_environment="false" found_manifest="false"
  local members=() verbose_members=() symlink_members=()
  archive_name="$(basename -- "$archive_path")"
  checksum_file="${archive_path}.sha256"
  is_backup_archive_name "$archive_name" || die "Backup archive name is invalid."
  [ -f "$archive_path" ] || die "Backup archive does not exist."
  [ -f "$checksum_file" ] || die "Backup checksum file does not exist."
  read -r expected_hash referenced_name < "$checksum_file"
  [[ "$expected_hash" =~ ^[0-9a-fA-F]{64}$ ]] || die "Backup checksum is invalid."
  [ "$referenced_name" = "$archive_name" ] || die "Backup checksum references a different archive."
  actual_hash="$(sha256sum "$archive_path" | awk '{print $1}')"
  [ "${expected_hash,,}" = "${actual_hash,,}" ] || die "Backup checksum verification failed."

  if ! member_listing="$(tar -tzf "$archive_path")"; then
    die "Backup archive member listing is invalid."
  fi
  if ! verbose_listing="$(tar -tvzf "$archive_path")"; then
    die "Backup archive metadata is invalid."
  fi
  mapfile -t members <<< "$member_listing"
  mapfile -t verbose_members <<< "$verbose_listing"
  [ "${#members[@]}" -eq "${#verbose_members[@]}" ] \
    || die "Backup archive member metadata is inconsistent."

  for ((index = 0; index < ${#members[@]}; index++)); do
    member="${members[$index]}"
    verbose_line="${verbose_members[$index]}"
    member_type="${verbose_line:0:1}"
    normalized_member="${member%/}"
    [ -n "$normalized_member" ] || continue
    case "$member_type" in
      -|d) ;;
      l) symlink_members+=("$normalized_member") ;;
      *) die "Backup archive contains a hard link or unsupported file type." ;;
    esac
    [ "${normalized_member#/}" = "$normalized_member" ] || die "Backup archive contains an absolute path."
    case "/${normalized_member}/" in
      *"/../"*) die "Backup archive contains a parent-directory path." ;;
    esac
    case "$normalized_member" in
      docker|docker/data|docker/data/*|docker/.env|backup-manifest.env) ;;
      *) die "Backup archive contains an unexpected path." ;;
    esac
    [ "$normalized_member" = "docker/data" ] && [ "$member_type" = "d" ] && found_data="true"
    [ "$normalized_member" = "docker/.env" ] && [ "$member_type" = "-" ] && found_environment="true"
    [ "$normalized_member" = "backup-manifest.env" ] && [ "$member_type" = "-" ] && found_manifest="true"
  done
  for symlink_member in "${symlink_members[@]}"; do
    for member in "${members[@]}"; do
      normalized_member="${member%/}"
      case "$normalized_member" in
        "${symlink_member}/"*) die "Backup archive contains a member nested beneath a symbolic link." ;;
      esac
    done
  done
  if [ "$found_data" != "true" ] \
    || [ "$found_environment" != "true" ] \
    || [ "$found_manifest" != "true" ]; then
    die "Backup archive is missing required entries."
  fi
}

database_backend() {
  local config_file="$1"
  [ -f "$config_file" ] || return 0
  awk '
    /^database:[[:space:]]*$/ { in_database = 1; next }
    in_database && /^[^[:space:]#]/ { exit }
    in_database && /^[[:space:]]+use:/ {
      sub(/^[[:space:]]+use:[[:space:]]*/, "")
      sub(/[[:space:]]+#.*$/, "")
      print
      exit
    }
  ' "$config_file" | tr -d "\"' \t\r"
}

activate_restored_data() {
  local staged_data="$1"
  local current_root="$2"
  local current_data="${INSTALL_DIR}/docker/data"
  mv "$current_data" "${current_root}/data" || return 1
  ORIGINAL_DATA_MOVED="true"
  if ! mv "$staged_data" "$current_data"; then
    if mv "${current_root}/data" "$current_data"; then
      ORIGINAL_DATA_MOVED="false"
    fi
    return 1
  fi
}

rollback_restored_data() {
  local current_data="${INSTALL_DIR}/docker/data"
  [ "$ORIGINAL_DATA_MOVED" = "true" ] || return 0
  [ -n "$ORIGINAL_DATA_ROOT" ] && [ -d "${ORIGINAL_DATA_ROOT}/data" ] || return 1

  stop_running_services || return 1
  if [ -z "$FAILED_DATA_ROOT" ]; then
    FAILED_DATA_ROOT="$(mktemp -d "${INSTALL_DIR}/docker/.restore-failed.XXXXXX")"
  fi
  if [ -d "$current_data" ]; then
    [ ! -e "${FAILED_DATA_ROOT}/data" ] || return 1
    mv "$current_data" "${FAILED_DATA_ROOT}/data" || return 1
  fi
  if mv "${ORIGINAL_DATA_ROOT}/data" "$current_data"; then
    ORIGINAL_DATA_MOVED="false"
    rm -rf -- "$ORIGINAL_DATA_ROOT" "$FAILED_DATA_ROOT"
    ORIGINAL_DATA_ROOT=""
    FAILED_DATA_ROOT=""
    return 0
  fi
  if [ ! -e "$current_data" ] && [ -d "${FAILED_DATA_ROOT}/data" ]; then
    mv "${FAILED_DATA_ROOT}/data" "$current_data" || true
  fi
  return 1
}

run_create() {
  ensure_local_data_is_archive_safe
  ensure_backup_capacity
  capture_running_services
  stop_running_services
  create_archive
  restart_running_services || die "Backup was created, but services could not be restarted."
  wait_for_http || die "Backup was created, but LangBot did not recover after restart."
  log "Backup created: ${LAST_BACKUP}"
}

run_restore() {
  local requested_archive="$1"
  local archive_path stage_root current_root backend
  archive_path="$(normalize_archive_path "$requested_archive")"
  verify_archive "$archive_path"
  ensure_local_data_is_archive_safe
  ensure_backup_capacity
  ensure_restore_capacity "$archive_path"

  stage_root="$(mktemp -d "${INSTALL_DIR}/docker/.restore-stage.XXXXXX")"
  track_temp_path "$stage_root"
  tar -xzf "$archive_path" --no-same-owner -C "$stage_root"
  if [ ! -d "${stage_root}/docker/data" ] || [ -L "${stage_root}/docker/data" ]; then
    die "Staged backup data is missing or unsafe."
  fi
  if [ ! -f "${stage_root}/backup-manifest.env" ] || [ -L "${stage_root}/backup-manifest.env" ]; then
    die "Staged backup manifest is missing or unsafe."
  fi
  grep -qx 'FORMAT_VERSION=1' "${stage_root}/backup-manifest.env" \
    || die "Backup manifest format is unsupported."
  backend="$(database_backend "${stage_root}/docker/data/config.yaml")"
  backend="${backend:-sqlite}"
  if [ "$backend" != "sqlite" ] && [ "${LANBOT_ALLOW_EXTERNAL_RESTORE:-false}" != "true" ]; then
    die "Backup references an external database; restore it with native database tools first."
  fi

  capture_running_services
  stop_running_services
  create_archive "$archive_path"
  log "Pre-restore safety backup created: ${LAST_BACKUP}"
  current_root="$(mktemp -d "${INSTALL_DIR}/docker/.restore-current.XXXXXX")"
  ORIGINAL_DATA_ROOT="$current_root"
  if ! activate_restored_data "${stage_root}/docker/data" "$current_root"; then
    if [ "$ORIGINAL_DATA_MOVED" = "false" ]; then
      rm -rf -- "$current_root"
      ORIGINAL_DATA_ROOT=""
    fi
    die "Restored data could not be activated; automatic recovery was attempted."
  fi

  if restart_running_services && wait_for_http; then
    ORIGINAL_DATA_MOVED="false"
    rm -rf -- "$current_root" "$stage_root"
    ORIGINAL_DATA_ROOT=""
    untrack_temp_path "$stage_root"
    log "Backup restored successfully: ${archive_path}"
    return 0
  fi

  if ! rollback_restored_data; then
    AUTO_RESTART_SERVICES="false"
    die "Restore health check failed and current data could not be recovered automatically."
  fi
  if ! restart_running_services || ! wait_for_http; then
    die "Restore failed; current data was recovered but services require manual attention."
  fi
  rm -rf -- "$stage_root"
  untrack_temp_path "$stage_root"
  die "Restore failed its health check; the pre-restore data was restored."
}

main() {
  local command="${1:-}"
  local archive_path=""
  local requested_install_dir=""

  case "$command" in
    create)
      requested_install_dir="${2:-$DEFAULT_INSTALL_DIR}"
      [ "$#" -le 2 ] || die "Too many arguments for create."
      ;;
    restore)
      archive_path="${2:-}"
      [ -n "$archive_path" ] || die "restore requires an archive path."
      requested_install_dir="${3:-$DEFAULT_INSTALL_DIR}"
      [ "$#" -le 3 ] || die "Too many arguments for restore."
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac

  [ "$(uname -s)" = "Linux" ] || die "This script supports Linux servers only."
  need_cmd awk
  need_cmd curl
  need_cmd df
  need_cmd docker
  need_cmd du
  need_cmd find
  need_cmd gzip
  need_cmd sha256sum
  need_cmd tar
  need_cmd wc
  initialize_paths "$requested_install_dir"
  acquire_backup_lock
  resolve_compose_command
  trap cleanup EXIT

  if [ "$command" = "create" ]; then
    run_create
  else
    run_restore "$archive_path"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
