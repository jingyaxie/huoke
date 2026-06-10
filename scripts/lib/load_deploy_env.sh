#!/usr/bin/env bash
# 加载本地部署凭据（.env.deploy.local，已被 *.local 忽略）

if [[ -n "${HUOKE_DEPLOY_ENV_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
HUOKE_DEPLOY_ENV_LOADED=1

_deploy_env_repo_root() {
  local here="${BASH_SOURCE[0]}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/../.." && pwd
}

DEPLOY_ENV_ROOT="${DEPLOY_ENV_ROOT:-$(_deploy_env_repo_root)}"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$DEPLOY_ENV_ROOT/.env.deploy.local}"

if [[ -f "$DEPLOY_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DEPLOY_ENV_FILE"
  set +a
fi

export PROD_SSH_HOST="${PROD_SSH_HOST:-39.105.130.85}"
export PROD_SSH_USER="${PROD_SSH_USER:-root}"
export PROD_HOST="${PROD_HOST:-${PROD_SSH_USER}@${PROD_SSH_HOST}}"
export PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
export PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"

_ssh_opts() {
  echo "-o" "StrictHostKeyChecking=accept-new"
  if [[ -n "${PROD_SSH_KEY:-}" ]]; then
    echo "-i" "$PROD_SSH_KEY"
  fi
}

prod_rsync_ssh() {
  local cmd="ssh -o StrictHostKeyChecking=accept-new"
  if [[ -n "${PROD_SSH_KEY:-}" ]]; then
    cmd="$cmd -i $PROD_SSH_KEY"
  fi
  echo "$cmd"
}

prod_rsync() {
  local src="${1:?}"
  local dest="${PROD_HOST}:${PROD_ROOT}/"
  local rsync_ssh
  rsync_ssh="$(prod_rsync_ssh)"
  prod_ssh "command -v rsync >/dev/null 2>&1 || (dnf install -y rsync 2>/dev/null || yum install -y rsync)"
  prod_ssh "mkdir -p '$PROD_ROOT'"
  rsync -az --delete \
    -e "$rsync_ssh" \
    --exclude '.git/' \
    --exclude '._*' \
    --exclude '**/.DS_Store' \
    --exclude '.venv/' \
    --exclude 'backend/.venv/' \
    --exclude '.env.deploy.local' \
    --exclude 'frontend/node_modules/' \
    --exclude 'frontend/dist/' \
    --exclude 'mysql/data/' \
    --exclude 'storage/' \
    --exclude 'reports/' \
    --exclude 'scripts/.deploy-state' \
    --exclude 'docker/ssh/*.pem' \
    "$src" "$dest"
}

prod_ssh() {
  local host="${PROD_HOST}"
  # shellcheck disable=SC2207
  local ssh_common=( $(_ssh_opts) )
  if [[ -n "${PROD_SSH_KEY:-}" ]]; then
    ssh "${ssh_common[@]}" "$host" "$@"
  elif [[ -n "${PROD_SSH_PASSWORD:-}" ]]; then
    if ! command -v sshpass >/dev/null 2>&1; then
      echo "prod_ssh: 需要 sshpass（brew install hudochenkov/sshpass/sshpass）" >&2
      return 1
    fi
    export SSHPASS="$PROD_SSH_PASSWORD"
    sshpass -e ssh \
      "${ssh_common[@]}" \
      -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no \
      "$host" "$@"
  else
    ssh "${ssh_common[@]}" "$host" "$@"
  fi
}

prod_scp() {
  # shellcheck disable=SC2207
  local scp_common=( $(_ssh_opts) )
  if [[ -n "${PROD_SSH_KEY:-}" ]]; then
    scp "${scp_common[@]}" "$@"
  elif [[ -n "${PROD_SSH_PASSWORD:-}" ]]; then
    if ! command -v sshpass >/dev/null 2>&1; then
      echo "prod_scp: 需要 sshpass（brew install hudochenkov/sshpass/sshpass）" >&2
      return 1
    fi
    export SSHPASS="$PROD_SSH_PASSWORD"
    sshpass -e scp \
      "${scp_common[@]}" \
      -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no \
      "$@"
  else
    scp "${scp_common[@]}" "$@"
  fi
}

