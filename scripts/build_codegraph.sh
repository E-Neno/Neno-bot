#!/usr/bin/env bash
set -euo pipefail

: "${CGC_BIN:=cgc}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"

REPO_ROOT="${GITHUB_WORKSPACE}"
BUILD_DIR="$(mktemp -d)"
MANIFEST="${BUILD_DIR}/manifest.json"
BUNDLE_NAME="codegraph-${GITHUB_SHA}.tar.gz"
BUNDLE_PATH="${REPO_ROOT}/${BUNDLE_NAME}"
CGCIGNORE="${REPO_ROOT}/.cgcignore"
CGC_DB_FILE="${BUILD_DIR}/.codegraphcontext/kuzudb"
CGC_DB_OUTPUT="${BUILD_DIR}/.codegraphcontext/codegraph.kuzu"

cleanup() { rm -rf "${BUILD_DIR}"; }
trap cleanup EXIT

echo "=== CodeGraphContext Build ==="
echo "Commit: ${GITHUB_SHA}"
echo "Repo:   ${REPO_ROOT}"
echo "Ignore: ${CGCIGNORE} ($(wc -l < "${CGCIGNORE}") lines)"

# --- Config kuzudb ---
echo ""
echo "--- Config: set DEFAULT_DATABASE to kuzudb ---"
"${CGC_BIN}" config set DEFAULT_DATABASE kuzudb

# --- Index ---
echo ""
echo "--- Running cgc index ---"
"${CGC_BIN}" --db kuzudb --db-path "${CGC_DB_FILE}" index "${REPO_ROOT}"

if [ ! -f "${CGC_DB_FILE}" ]; then
  echo "[ERROR] No kuzudb file at ${CGC_DB_FILE}"
  ls -la "${BUILD_DIR}/.codegraphcontext/" 2>/dev/null || echo "(empty)"
  exit 1
fi

# Rename to codegraph.kuzu
mv "${CGC_DB_FILE}" "${CGC_DB_OUTPUT}"
echo "Index complete. DB file: $(du -sh "${CGC_DB_OUTPUT}" | cut -f1)"

# --- manifest.json ---
CGC_VERSION="$("${CGC_BIN}" version 2>&1 || true)"
CGC_VERSION="${CGC_VERSION##* }"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BUILD_HOST="$(hostname 2>/dev/null || echo "github-actions")"

cat > "${MANIFEST}" <<MANEOF
{
  "version": "1.0.0",
  "commit": "${GITHUB_SHA}",
  "build_time": "${BUILD_TIME}",
  "build_host": "${BUILD_HOST}",
  "cgc_version": "${CGC_VERSION}",
  "db_engine": "kuzudb",
  "db_type": "file",
  "db_file": "codegraph.kuzu",
  "repo": "${GITHUB_REPOSITORY:-unknown}",
  "bundle": "${BUNDLE_NAME}"
}
MANEOF

echo ""
echo "=== manifest.json ==="
cat "${MANIFEST}"

# --- Bundle ---
echo ""
echo "--- Creating bundle: ${BUNDLE_NAME} ---"

tar -czf "${BUNDLE_PATH}" -C "${BUILD_DIR}" .codegraphcontext
cp "${MANIFEST}" "${BUILD_DIR}/manifest_bundle.json"
gunzip < "${BUNDLE_PATH}" > "${BUNDLE_PATH%.gz}"
tar -rf "${BUNDLE_PATH%.gz}" -C "${BUILD_DIR}" manifest.json
cp "${CGCIGNORE}" "${BUILD_DIR}/.cgcignore"
tar -rf "${BUNDLE_PATH%.gz}" -C "${BUILD_DIR}" .cgcignore
gzip -c "${BUNDLE_PATH%.gz}" > "${BUNDLE_PATH}"
rm -f "${BUNDLE_PATH%.gz}"

echo ""
echo "=== Build Complete ==="
echo "Bundle: ${BUNDLE_PATH}"
echo "Size:   $(du -sh "${BUNDLE_PATH}" | cut -f1)"
echo "SHA256: $(sha256sum "${BUNDLE_PATH}" | awk '{print $1}')"

# List bundle contents for verification
echo ""
echo "--- Bundle contents ---"
tar -tzf "${BUNDLE_PATH}"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  { echo "bundle_path=${BUNDLE_PATH}"; echo "bundle_name=${BUNDLE_NAME}"; } >> "${GITHUB_OUTPUT}"
fi