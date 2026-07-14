#!/usr/bin/env bash
set -Eeuo pipefail

REPO_SLUG="csbsgyl/ai-lanbot"
REPO_BRANCH="main"
GITHUB_ACCELERATOR="https://github.xiaohangyun.org"
INSTALL_DIR="${1:-/opt/ai-lanbot}"
UPDATE_DIR="${INSTALL_DIR}/docker/data/update"
STATUS_FILE="${UPDATE_DIR}/status.json"
LOG_FILE="${UPDATE_DIR}/update.log"
DEPLOY_SCRIPT=""
TARGET_REVISION=""
CURRENT_REVISION=""

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

write_status() {
  local state="$1"
  local message="$2"
  local timestamp tmp_file
  timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  tmp_file="${STATUS_FILE}.tmp"
  printf '{"state":"%s","message":"%s","current_revision":"%s","target_revision":"%s","updated_at":"%s"}\n' \
    "$state" "$message" "$CURRENT_REVISION" "$TARGET_REVISION" "$timestamp" > "$tmp_file"
  mv "$tmp_file" "$STATUS_FILE"
  chmod 644 "$STATUS_FILE"
}

fetch_target_revision() {
  local api_url atom_url revision url
  atom_url="https://github.com/${REPO_SLUG}/commits/${REPO_BRANCH}.atom"
  for url in "$atom_url" "${GITHUB_ACCELERATOR}/${atom_url}"; do
    if revision="$(fetch_revision_url "$url" 'application/atom+xml')"; then
      printf '%s' "$revision"
      return 0
    fi
  done

  api_url="https://api.github.com/repos/${REPO_SLUG}/commits/${REPO_BRANCH}"
  for url in "$api_url" "${GITHUB_ACCELERATOR}/${api_url}"; do
    if revision="$(fetch_revision_url "$url" 'application/vnd.github.sha')"; then
      printf '%s' "$revision"
      return 0
    fi
  done

  return 1
}

download_deploy_script() {
  local direct_url accel_url
  direct_url="https://raw.githubusercontent.com/${REPO_SLUG}/${TARGET_REVISION}/scripts/one-click-deploy.sh"
  accel_url="${GITHUB_ACCELERATOR}/${direct_url}"
  DEPLOY_SCRIPT="$(mktemp)"

  if ! curl -fL --retry 3 --connect-timeout 10 --max-time 120 -o "$DEPLOY_SCRIPT" "$direct_url"; then
    curl -fL --retry 3 --connect-timeout 10 --max-time 120 -o "$DEPLOY_SCRIPT" "$accel_url"
  fi
}

read_env_key() {
  local key="$1"
  local env_file="${INSTALL_DIR}/docker/.env"
  [ -f "$env_file" ] || return 0
  sed -n "s/^${key}=//p" "$env_file" | tail -n 1
}

export_deployment_setting() {
  local source_key="$1"
  local target_key="$2"
  local value
  value="$(read_env_key "$source_key")"
  [ -n "$value" ] && export "${target_key}=${value}"
}

load_deployment_settings() {
  local box_enabled
  export_deployment_setting "COMPOSE_PROJECT_NAME" "LANBOT_COMPOSE_PROJECT_NAME"
  export_deployment_setting "LANGBOT_HTTP_PORT" "LANBOT_HTTP_PORT"
  export_deployment_setting "LANBOT_CONTAINER_NAME" "LANBOT_CONTAINER_NAME"
  export_deployment_setting "LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME" "LANBOT_PLUGIN_RUNTIME_CONTAINER_NAME"
  export_deployment_setting "LANBOT_BOX_CONTAINER_NAME" "LANBOT_BOX_CONTAINER_NAME"
  export_deployment_setting "LANBOT_PLUGIN_DEBUG_PORT" "LANBOT_PLUGIN_DEBUG_PORT"
  export_deployment_setting "LANBOT_REVERSE_PORT_MAPPING" "LANBOT_REVERSE_PORT_MAPPING"
  export_deployment_setting "LANBOT_SOURCE_MODE" "LANBOT_SOURCE_MODE"

  box_enabled="$(read_env_key "LANBOT_BOX_ENABLED")"
  if [ "$box_enabled" = "true" ]; then
    export LANBOT_COMPOSE_PROFILES="all"
  else
    export LANBOT_COMPOSE_PROFILES=""
  fi
}

on_error() {
  local exit_code="$1"
  trap - ERR
  write_status "failed" "update_failed"
  exit "$exit_code"
}

umask 077
mkdir -p "$UPDATE_DIR"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"
if [ "$(wc -c < "$LOG_FILE")" -gt 1048576 ]; then
  tail -n 500 "$LOG_FILE" > "${LOG_FILE}.tmp"
  mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi
exec >> "$LOG_FILE" 2>&1

trap 'on_error $?' ERR
trap '[ -z "$DEPLOY_SCRIPT" ] || rm -f "$DEPLOY_SCRIPT"' EXIT

printf '[ai-lanbot-update] %s Starting managed update.\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
if [ -f "${INSTALL_DIR}/docker/.env" ]; then
  CURRENT_REVISION="$(sed -n 's/^LANBOT_BUILD_REVISION=//p' "${INSTALL_DIR}/docker/.env" | tail -n 1)"
fi
is_valid_revision "$CURRENT_REVISION" || CURRENT_REVISION=""

write_status "checking" "checking_repository"
TARGET_REVISION="$(fetch_target_revision)"
is_valid_revision "$TARGET_REVISION"

if [ "$CURRENT_REVISION" = "$TARGET_REVISION" ]; then
  write_status "success" "already_current"
  printf '[ai-lanbot-update] Already running revision %s.\n' "$TARGET_REVISION"
  exit 0
fi

write_status "deploying" "installing_update"
download_deploy_script
load_deployment_settings

LANBOT_TARGET_REVISION="$TARGET_REVISION" \
LANBOT_IMAGE_WAIT_SECONDS="${LANBOT_IMAGE_WAIT_SECONDS:-1800}" \
LANBOT_ALLOW_BUILD_FALLBACK="false" \
LANBOT_INSTALL_DIR="$INSTALL_DIR" \
bash "$DEPLOY_SCRIPT"

CURRENT_REVISION="$TARGET_REVISION"
write_status "success" "update_complete"
printf '[ai-lanbot-update] %s Update completed at revision %s.\n' \
  "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$TARGET_REVISION"
