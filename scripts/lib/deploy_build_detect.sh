#!/usr/bin/env bash
# 判断本次发布是否需要重建 backend Docker 镜像（apt/pip/playwright 层）

deploy_repo_root() {
  local here="${BASH_SOURCE[0]}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/../.." && pwd
}

DEPLOY_STATE_FILE="${DEPLOY_STATE_FILE:-$(deploy_repo_root)/scripts/.deploy-state}"

# 改动这些路径时需要重建 backend 依赖层（apt/pip/playwright）
BASE_IMAGE_REBUILD_PATTERNS=(
  'backend/Dockerfile'
  'backend/requirements.txt'
  'backend/scripts/install-cjk-fonts.sh'
)

# 改动这些路径时需要重建 backend 镜像（含 entrypoint/fluxbox，通常随依赖层一起重建）
IMAGE_REBUILD_PATTERNS=(
  'backend/Dockerfile'
  'backend/Dockerfile.app'
  'backend/requirements.txt'
  'backend/scripts/docker-entrypoint.sh'
  'backend/scripts/install-cjk-fonts.sh'
  'backend/scripts/fluxbox/'
  'backend/app/core/antibot.py'
  'backend/app/services/font_bootstrap.py'
  'docker-compose.yml'
)

_deploy_state_get() {
  local key="$1"
  local line
  [[ -f "$DEPLOY_STATE_FILE" ]] || return 0
  line="$(grep -E "^${key}=" "$DEPLOY_STATE_FILE" 2>/dev/null | tail -1)" || return 0
  line="${line#*=}"
  line="${line#\'}"
  line="${line%\'}"
  line="${line#\"}"
  line="${line%\"}"
  echo "$line"
}

deploy_state_set() {
  local last_deploy_commit="${1:-}"
  local last_image_build_commit="${2:-}"
  mkdir -p "$(dirname "$DEPLOY_STATE_FILE")"
  cat >"$DEPLOY_STATE_FILE" <<EOF
# 由 deploy_backend_prod.sh 自动维护，勿手改
LAST_DEPLOY_COMMIT='$last_deploy_commit'
LAST_IMAGE_BUILD_COMMIT='$last_image_build_commit'
EOF
}

_deploy_changed_files_since() {
  local since="$1"
  local root
  root="$(deploy_repo_root)"
  cd "$root"

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "WARN: 非 git 仓库，无法自动判断，建议全量构建" >&2
    return 0
  fi

  if [[ -z "$since" ]]; then
    git diff --name-only HEAD 2>/dev/null || true
    git diff --name-only --cached 2>/dev/null || true
    return 0
  fi

  if ! git cat-file -e "${since}^{commit}" 2>/dev/null; then
    echo "WARN: 上次部署 commit 无效，将执行全量构建" >&2
    git diff --name-only HEAD 2>/dev/null || true
    return 0
  fi

  git diff --name-only "$since" HEAD 2>/dev/null || true
  git diff --name-only "$since" --cached 2>/dev/null || true
}

_file_triggers_base_rebuild() {
  local file="$1"
  local pattern
  for pattern in "${BASE_IMAGE_REBUILD_PATTERNS[@]}"; do
    if [[ "$file" == "$pattern" ]] || [[ "$file" == "$pattern"* ]]; then
      return 0
    fi
  done
  return 1
}

FRONTEND_IMAGE_REBUILD_PATTERNS=(
  'frontend/Dockerfile'
  'frontend/package.json'
  'frontend/package-lock.json'
  'frontend/nginx.conf'
)

FRONTEND_DIST_PATTERNS=(
  'frontend/src/'
  'frontend/public/'
  'frontend/index.html'
  'frontend/vite.config.js'
)

_file_triggers_frontend_image_rebuild() {
  local file="$1"
  local pattern
  for pattern in "${FRONTEND_IMAGE_REBUILD_PATTERNS[@]}"; do
    if [[ "$file" == "$pattern" ]] || [[ "$file" == "$pattern"* ]]; then
      return 0
    fi
  done
  return 1
}

_file_triggers_frontend_dist() {
  local file="$1"
  local pattern
  for pattern in "${FRONTEND_DIST_PATTERNS[@]}"; do
    if [[ "$file" == "$pattern" ]] || [[ "$file" == "$pattern"* ]]; then
      return 0
    fi
  done
  return 1
}

_deploy_scan_changes() {
  local since="$1"
  local changed=""
  local need_image=0
  local need_base=0
  local need_frontend_image=0
  local need_frontend_dist=0
  local -a image_triggers=()
  local -a base_triggers=()
  local -a frontend_image_triggers=()
  local -a frontend_dist_triggers=()

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    changed+="$line"$'\n'
    if _file_triggers_image_rebuild "$line"; then
      need_image=1
      image_triggers+=("$line")
    fi
    if _file_triggers_base_rebuild "$line"; then
      need_base=1
      base_triggers+=("$line")
    fi
    if _file_triggers_frontend_image_rebuild "$line"; then
      need_frontend_image=1
      frontend_image_triggers+=("$line")
    fi
    if _file_triggers_frontend_dist "$line"; then
      need_frontend_dist=1
      frontend_dist_triggers+=("$line")
    fi
  done < <(_deploy_changed_files_since "$since" | sort -u)

  DEPLOY_SCAN_CHANGED="$changed"
  DEPLOY_SCAN_NEED_IMAGE="$need_image"
  DEPLOY_SCAN_NEED_BASE="$need_base"
  DEPLOY_SCAN_NEED_FRONTEND_IMAGE="$need_frontend_image"
  DEPLOY_SCAN_NEED_FRONTEND_DIST="$need_frontend_dist"
  # bash 3.2 + set -u：空数组展开 "${arr[@]}" 会报 unbound variable
  DEPLOY_SCAN_IMAGE_TRIGGERS=()
  ((${#image_triggers[@]})) && DEPLOY_SCAN_IMAGE_TRIGGERS=("${image_triggers[@]}")
  DEPLOY_SCAN_BASE_TRIGGERS=()
  ((${#base_triggers[@]})) && DEPLOY_SCAN_BASE_TRIGGERS=("${base_triggers[@]}")
}

_file_triggers_image_rebuild() {
  local file="$1"
  local pattern
  for pattern in "${IMAGE_REBUILD_PATTERNS[@]}"; do
    if [[ "$file" == "$pattern" ]] || [[ "$file" == "$pattern"* ]]; then
      return 0
    fi
  done
  return 1
}

# 输出: 0|1 ，前端源码变更时需本地 npm build + rsync dist（不重建镜像）
deploy_needs_frontend_dist() {
  local mode="${1:-auto}"
  local last
  last="$(_deploy_state_get LAST_DEPLOY_COMMIT)"

  if [[ "$mode" == "fast" ]]; then
    _deploy_scan_changes "$last"
    echo "${DEPLOY_SCAN_NEED_FRONTEND_DIST:-0}"
    return
  fi
  if [[ "$mode" == "full" ]]; then
    echo 0
    return
  fi

  _deploy_scan_changes "$last"
  echo "${DEPLOY_SCAN_NEED_FRONTEND_DIST:-0}"
}

# 输出: 0|1 ，需重建 frontend_prod 镜像
deploy_needs_frontend_image() {
  local mode="${1:-auto}"
  local last
  last="$(_deploy_state_get LAST_DEPLOY_COMMIT)"

  if [[ "$mode" == "fast" ]]; then
    echo 0
    return
  fi
  if [[ "$mode" == "full" ]]; then
    echo 1
    return
  fi

  _deploy_scan_changes "$last"
  echo "${DEPLOY_SCAN_NEED_FRONTEND_IMAGE:-0}"
}

# 输出: need_build=0|1 ，并打印原因到 stderr
deploy_needs_image_build() {
  local mode="${1:-auto}"
  local last
  last="$(_deploy_state_get LAST_DEPLOY_COMMIT)"

  if [[ "$mode" == "fast" ]]; then
    echo "SKIP_BUILD=1（--fast 仅 rsync + 重启，不打包不上传）" >&2
    echo 0
    return
  fi
  if [[ "$mode" == "full" ]]; then
    echo "SKIP_BUILD=0（--full 全量构建镜像）" >&2
    echo 1
    return
  fi

  if [[ "${SKIP_BUILD:-}" == "1" ]]; then
    echo "SKIP_BUILD=1（环境变量）" >&2
    echo 0
    return
  fi
  if [[ "${SKIP_BUILD:-}" == "0" ]] && [[ -n "${SKIP_BUILD:-}" ]]; then
    echo "SKIP_BUILD=0（环境变量）" >&2
    echo 1
    return
  fi

  if [[ ! -f "$DEPLOY_STATE_FILE" ]]; then
    echo "首次部署或未记录状态 → 全量构建镜像" >&2
    echo 1
    return
  fi

  local changed
  local need=0
  local triggers=()
  _deploy_scan_changes "$last"
  changed="$DEPLOY_SCAN_CHANGED"
  need="$DEPLOY_SCAN_NEED_IMAGE"
  triggers=()
  ((${#DEPLOY_SCAN_IMAGE_TRIGGERS[@]})) && triggers=("${DEPLOY_SCAN_IMAGE_TRIGGERS[@]}")

  if [[ "$need" == "1" ]]; then
    echo "检测到镜像相关变更，将全量构建:" >&2
    printf '  - %s\n' "${triggers[@]}" >&2
    echo 1
    return
  fi

  if [[ -z "$changed" ]]; then
    echo "自上次部署无 git 变更 → 快速发布（跳过 build）" >&2
  else
    echo "仅业务代码/前端变更 → 快速发布（跳过 apt/pip/playwright）" >&2
  fi
  echo 0
}

# 输出: need_base=0|1 ，判断是否需要重建/上传 backend 依赖层
deploy_needs_base_rebuild() {
  local mode="${1:-auto}"
  local last
  last="$(_deploy_state_get LAST_DEPLOY_COMMIT)"

  if [[ "$mode" == "full" ]]; then
    echo "依赖层需重建（--full）" >&2
    echo 1
    return
  fi
  if [[ "$mode" == "fast" ]]; then
    echo "依赖层跳过（--fast / local-images 默认仅业务层）" >&2
    echo 0
    return
  fi

  if [[ ! -f "$DEPLOY_STATE_FILE" ]]; then
    echo "首次部署 → 需构建依赖层" >&2
    echo 1
    return
  fi

  local changed
  local need=0
  local triggers=()
  _deploy_scan_changes "$last"
  changed="$DEPLOY_SCAN_CHANGED"
  need="$DEPLOY_SCAN_NEED_BASE"
  triggers=()
  ((${#DEPLOY_SCAN_BASE_TRIGGERS[@]})) && triggers=("${DEPLOY_SCAN_BASE_TRIGGERS[@]}")

  if [[ "$need" == "1" ]]; then
    echo "检测到依赖层相关变更:" >&2
    printf '  - %s\n' "${triggers[@]}" >&2
    echo 1
    return
  fi

  echo "依赖层未变更 → 跳过 base 构建/上传" >&2
  echo 0
}

deploy_record_success() {
  local did_build="${1:-0}"
  local root head
  root="$(deploy_repo_root)"
  cd "$root"
  if ! git rev-parse HEAD >/dev/null 2>&1; then
    return 0
  fi
  head="$(git rev-parse HEAD)"
  local last_build
  last_build="$(_deploy_state_get LAST_IMAGE_BUILD_COMMIT)"
  if [[ "$did_build" == "1" ]]; then
    last_build="$head"
  fi
  deploy_state_set "$head" "$last_build"
}
