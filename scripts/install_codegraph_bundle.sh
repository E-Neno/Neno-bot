#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# install_codegraph_bundle.sh
# 服务器端原子安装。纯文件操作，不调用 cgc。
# 最终结构: .codegraphcontext/{codegraph.kuzu, manifest.json, .cgcignore}
# ============================================================

BUNDLE_FILE="${1:-}"
REPO_ROOT="${CGC_REPO_ROOT:-$(pwd)}"
STRICT_CLEAN="${CGC_STRICT_CLEAN:-0}"

CGC_DIR="${REPO_ROOT}/.codegraphcontext"
CGC_PREV="${REPO_ROOT}/.codegraphcontext.prev"

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

# --- Step 1: Pre-flight ---
echo ""
echo "--- Step 1: Pre-flight checks ---"
cd "${REPO_ROOT}"
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "[ERROR] Not a git repository: ${REPO_ROOT}"
  exit 1
fi
if [ "${STRICT_CLEAN}" = "1" ]; then
  DIRTY="$(git status --porcelain 2>/dev/null | grep -v '^. .codegraphcontext' || true)"
  if [ -n "${DIRTY}" ]; then
    echo "[ERROR] Workspace is not clean. Refusing."
    echo "Dirty files:"; echo "${DIRTY}"
    echo "Commit/stash or set CGC_STRICT_CLEAN=0."
    exit 1
  fi
  echo "Workspace is clean."
else
  echo "Skipping strict clean check."
fi

# --- Step 2: Extract and read manifest ---
echo ""
echo "--- Step 2: Reading manifest ---"
TMP_DIR="$(mktemp -d)"
cleanup_tmp() { rm -rf "${TMP_DIR}"; }
trap cleanup_tmp EXIT

tar -xzf "${BUNDLE_FILE}" -C "${TMP_DIR}"

BUNDLE_MANIFEST="${TMP_DIR}/manifest.json"
if [ ! -f "${BUNDLE_MANIFEST}" ]; then
  BUNDLE_MANIFEST="${TMP_DIR}/.codegraphcontext/manifest.json"
fi
if [ ! -f "${BUNDLE_MANIFEST}" ]; then
  echo "[ERROR] Bundle does not contain manifest.json"
  exit 1
fi

BUNDLE_COMMIT=""
if command -v python3 &>/dev/null; then
  BUNDLE_COMMIT="$(python3 -c "import json,sys; print(json.load(open('${BUNDLE_MANIFEST}'))['commit'])" 2>/dev/null || true)"
elif command -v python &>/dev/null; then
  BUNDLE_COMMIT="$(python -c "import json,sys; print(json.load(open('${BUNDLE_MANIFEST}'))['commit'])" 2>/dev/null || true)"
else
  BUNDLE_COMMIT="$(grep -o '"commit"[[:space:]]*:[[:space:]]*"[^"]*"' "${BUNDLE_MANIFEST}" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
fi
if [ -z "${BUNDLE_COMMIT}" ]; then
  echo "[ERROR] Could not read commit from manifest.json"
  exit 1
fi
echo "Bundle commit: ${BUNDLE_COMMIT}"

# --- Step 3: Verify commit ---
echo ""
echo "--- Step 3: Verifying commit match ---"
CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Current HEAD: ${CURRENT_COMMIT}"
if [ "${CURRENT_COMMIT}" != "${BUNDLE_COMMIT}" ]; then
  echo "[ERROR] Commit mismatch!"
  echo "  Current HEAD:  ${CURRENT_COMMIT}"
  echo "  Bundle commit: ${BUNDLE_COMMIT}"
  exit 1
fi
echo "Commit verified OK."

# --- Step 4: Backup ---
echo ""
echo "--- Step 4: Backup existing index ---"
ROLLBACK_NEEDED=false
if [ -d "${CGC_DIR}" ]; then
  if [ -d "${CGC_PREV}" ]; then rm -rf "${CGC_PREV}"; fi
  mv "${CGC_DIR}" "${CGC_PREV}"
  ROLLBACK_NEEDED=true
  echo "Backed up to ${CGC_PREV}"
else
  echo "No existing .codegraphcontext (first install)."
fi

# --- Step 5: Rollback function ---
rollback() {
  echo ""; echo "[ROLLBACK] Restoring previous .codegraphcontext..."
  if [ -d "${CGC_DIR}" ]; then rm -rf "${CGC_DIR}"; fi
  if [ -d "${CGC_PREV}" ]; then mv "${CGC_PREV}" "${CGC_DIR}"; echo "[ROLLBACK] Restored."; else echo "[ROLLBACK] No backup."; fi
}

# --- Step 6: Install ---
echo ""
echo "--- Step 5: Installing new index ---"

SRC_CGC="${TMP_DIR}/.codegraphcontext"
if [ -d "${TMP_DIR}/.codegraphcontext" ]; then
  :
else
  mkdir -p "${TMP_DIR}/.codegraphcontext"
  if [ -f "${TMP_DIR}/codegraph.kuzu" ]; then mv "${TMP_DIR}/codegraph.kuzu" "${SRC_CGC}/"; fi
  if [ -f "${TMP_DIR}/manifest.json" ]; then cp "${TMP_DIR}/manifest.json" "${SRC_CGC}/"; fi
  if [ -f "${TMP_DIR}/.cgcignore" ]; then cp "${TMP_DIR}/.cgcignore" "${SRC_CGC}/"; fi
fi

if ! cp -r "${SRC_CGC}" "${CGC_DIR}" 2>/dev/null; then
  echo "[ERROR] Failed to copy .codegraphcontext"
  if [ "${ROLLBACK_NEEDED}" = true ]; then rollback; fi
  exit 1
fi
echo "Installed .codegraphcontext."

# --- Step 7: Verify ---
echo ""
echo "--- Step 6: Verifying installation ---"
FAIL=false
if [ ! -d "${CGC_DIR}" ]; then echo "[ERROR] Missing: ${CGC_DIR}"; FAIL=true; fi
if [ ! -f "${CGC_DIR}/codegraph.kuzu" ]; then echo "[ERROR] Missing: codegraph.kuzu"; FAIL=true; fi
INDEX_SIZE="$(du -sk "${CGC_DIR}" 2>/dev/null | cut -f1 || echo 0)"
if [ "${INDEX_SIZE}" -lt 1 ]; then echo "[ERROR] Index size too small: ${INDEX_SIZE}KB"; FAIL=true; fi
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
if [ "${ROLLBACK_NEEDED}" = true ]; then echo "Backup path:   ${CGC_PREV}"; fi
echo "Server can use .codegraphcontext without running cgc."