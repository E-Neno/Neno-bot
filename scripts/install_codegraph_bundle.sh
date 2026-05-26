#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# install_codegraph_bundle.sh
# 在服务器上原子安装 CodeGraphContext 索引 bundle。
# 服务器只做安装/替换，不运行 cgc index / watch / mcp / bundle import。
#
# 用法:
#   bash scripts/install_codegraph_bundle.sh <bundle.tar.gz>
#
# 环境变量:
#   CGC_REPO_ROOT      - 仓库根路径 (默认当前目录)
#   CGC_STRICT_CLEAN   - 工作区不干净时拒绝，0 跳过 (默认 0，见注释)
# ============================================================

BUNDLE_FILE="${1:-}"
REPO_ROOT="${CGC_REPO_ROOT:-$(pwd)}"
STRICT_CLEAN="${CGC_STRICT_CLEAN:-0}"

CGC_DIR="${REPO_ROOT}/.codegraphcontext"
CGC_PREV="${REPO_ROOT}/.codegraphcontext.prev"
MANIFEST_DST="${REPO_ROOT}/manifest.json"
CGCIGNORE_DST="${REPO_ROOT}/.cgcignore"

# --- 参数校验 ---
if [ -z "${BUNDLE_FILE}" ]; then
  echo "Usage: $0 <bundle.tar.gz>"
  exit 1
fi

if [ ! -f "${BUNDLE_FILE}" ]; then
  echo "[ERROR] Bundle file not found: ${BUNDLE_FILE}"
  exit 1
fi

echo "=== CodeGraphContext Bundle Installer ==="
echo "Bundle:     ${BUNDLE_FILE}"
echo "Repo root:  ${REPO_ROOT}"

# ==========================================================
# 1. 预检查
# ==========================================================
echo ""
echo "--- Step 1: Pre-flight checks ---"
cd "${REPO_ROOT}"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "[ERROR] Not a git repository: ${REPO_ROOT}"
  exit 1
fi

# 默认宽松模式：只检查 .codegraphcontext 目录自身不被 git 追踪修改
# 严格模式 (CGC_STRICT_CLEAN=1)：拒绝任何未提交变更
if [ "${STRICT_CLEAN}" = "1" ]; then
  DIRTY="$(git status --porcelain 2>/dev/null | grep -v '^. .codegraphcontext' || true)"
  if [ -n "${DIRTY}" ]; then
    echo "[ERROR] Workspace is not clean. Refusing to install."
    echo "Dirty files:"
    echo "${DIRTY}"
    echo ""
    echo "Commit or stash changes first, or set CGC_STRICT_CLEAN=0 to skip."
    exit 1
  fi
  echo "Workspace is clean."
else
  echo "Skipping strict clean check (CGC_STRICT_CLEAN=0)."
fi

# ==========================================================
# 2. 解压并读取 manifest
# ==========================================================
echo ""
echo "--- Step 2: Reading manifest from bundle ---"
TMP_DIR="$(mktemp -d)"
cleanup_tmp() { rm -rf "${TMP_DIR}"; }
trap cleanup_tmp EXIT

tar -xzf "${BUNDLE_FILE}" -C "${TMP_DIR}"

if [ ! -f "${TMP_DIR}/manifest.json" ]; then
  echo "[ERROR] Bundle does not contain manifest.json"
  exit 1
fi

# 用 python3 解析 JSON；若不可用则用 grep 兜底
if command -v python3 &>/dev/null; then
  BUNDLE_COMMIT="$(python3 -c "import json,sys; print(json.load(open('${TMP_DIR}/manifest.json'))['commit'])" 2>/dev/null || true)"
elif command -v python &>/dev/null; then
  BUNDLE_COMMIT="$(python -c "import json,sys; print(json.load(open('${TMP_DIR}/manifest.json'))['commit'])" 2>/dev/null || true)"
else
  BUNDLE_COMMIT="$(grep -o '"commit"[[:space:]]*:[[:space:]]*"[^"]*"' "${TMP_DIR}/manifest.json" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
fi

if [ -z "${BUNDLE_COMMIT}" ]; then
  echo "[ERROR] Could not read commit from manifest.json"
  exit 1
fi

echo "Bundle commit: ${BUNDLE_COMMIT}"

# ==========================================================
# 3. 校验 commit 一致
# ==========================================================
echo ""
echo "--- Step 3: Verifying commit match ---"
CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Current HEAD: ${CURRENT_COMMIT}"

if [ "${CURRENT_COMMIT}" != "${BUNDLE_COMMIT}" ]; then
  echo "[ERROR] Commit mismatch!"
  echo "  Current HEAD:  ${CURRENT_COMMIT}"
  echo "  Bundle commit: ${BUNDLE_COMMIT}"
  echo ""
  echo "Checkout the correct commit or use a matching bundle."
  exit 1
fi
echo "Commit verified OK."

# ==========================================================
# 4. 备份现有 .codegraphcontext
# ==========================================================
echo ""
echo "--- Step 4: Backup existing index ---"
ROLLBACK_NEEDED=false

if [ -d "${CGC_DIR}" ]; then
  echo "Existing .codegraphcontext found."

  if [ -d "${CGC_PREV}" ]; then
    echo "Removing previous backup: ${CGC_PREV}"
    rm -rf "${CGC_PREV}"
  fi

  mv "${CGC_DIR}" "${CGC_PREV}"
  ROLLBACK_NEEDED=true
  echo "Backed up to ${CGC_PREV}"
else
  echo "No existing .codegraphcontext (first install)."
fi

# ==========================================================
# 5. 回滚函数
# ==========================================================
rollback() {
  echo ""
  echo "[ROLLBACK] Restoring previous .codegraphcontext..."
  if [ -d "${CGC_DIR}" ]; then
    rm -rf "${CGC_DIR}"
  fi
  if [ -d "${CGC_PREV}" ]; then
    mv "${CGC_PREV}" "${CGC_DIR}"
    echo "[ROLLBACK] Restored from ${CGC_PREV}"
  else
    echo "[ROLLBACK] No backup to restore from."
  fi
}

# ==========================================================
# 6. 安装新索引 (纯文件操作，不调用 cgc)
# ==========================================================
echo ""
echo "--- Step 5: Installing new index ---"

if [ ! -d "${TMP_DIR}/.codegraphcontext" ]; then
  echo "[ERROR] Bundle does not contain .codegraphcontext directory"
  if [ "${ROLLBACK_NEEDED}" = true ]; then rollback; fi
  exit 1
fi

if ! cp -r "${TMP_DIR}/.codegraphcontext" "${CGC_DIR}" 2>/dev/null; then
  echo "[ERROR] Failed to copy new .codegraphcontext"
  if [ "${ROLLBACK_NEEDED}" = true ]; then rollback; fi
  exit 1
fi

cp "${TMP_DIR}/manifest.json" "${MANIFEST_DST}"
echo "Installed .codegraphcontext from bundle."

# 同时更新 .cgcignore（如果 bundle 中包含新版）
if [ -f "${TMP_DIR}/.cgcignore" ]; then
  cp "${TMP_DIR}/.cgcignore" "${CGCIGNORE_DST}"
fi

# ==========================================================
# 7. 验证安装
# ==========================================================
echo ""
echo "--- Step 6: Verifying installation ---"
FAIL=false

if [ ! -d "${CGC_DIR}" ]; then
  echo "[ERROR] Missing: ${CGC_DIR}"
  FAIL=true
fi

INDEX_SIZE="$(du -sk "${CGC_DIR}" 2>/dev/null | cut -f1 || echo 0)"
if [ "${INDEX_SIZE}" -lt 1 ]; then
  echo "[ERROR] Index size too small: ${INDEX_SIZE}KB"
  FAIL=true
fi

if [ "${FAIL}" = true ]; then
  echo "[ERROR] Verification failed!"
  if [ "${ROLLBACK_NEEDED}" = true ]; then rollback; fi
  exit 1
fi

echo "Verification passed. Index size: ${INDEX_SIZE}KB"

echo ""
echo "=== Install Complete ==="
echo "Bundle commit: ${BUNDLE_COMMIT}"
echo "Index path:    ${CGC_DIR}"
if [ "${ROLLBACK_NEEDED}" = true ]; then
  echo "Backup path:   ${CGC_PREV}"
fi
echo ""
echo "The server can use the updated .codegraphcontext without running cgc."
