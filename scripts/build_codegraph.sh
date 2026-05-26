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

cleanup() { rm -rf "${BUILD_DIR}"; }
trap cleanup EXIT

echo "=== CodeGraphContext Build ==="
echo "Commit: ${GITHUB_SHA}"
echo "Repo:   ${REPO_ROOT}"
echo "Ignore: ${CGCIGNORE} ($(wc -l < "${CGCIGNORE}") lines)"

# --- Set kuzudb as default database ---
echo ""
echo "--- Configuring kuzudb ---"
"${CGC_BIN}" config set DEFAULT_DATABASE kuzudb

# --- Set per-repo mode ---
echo ""
echo "--- Setting per-repo mode ---"
"${CGC_BIN}" context mode per-repo

# --- Index ---
echo ""
echo "--- Running cgc index ---"
"${CGC_BIN}" index "${REPO_ROOT}"

# Find the actual database under .codegraphcontext/
CGC_DB_DIR=""
for candidate in "${REPO_ROOT}/.codegraphcontext/kuzudb" "${REPO_ROOT}/.codegraphcontext/db/kuzudb"; do
  if [ -d "${candidate}" ]; then CGC_DB_DIR="${candidate}"; break; fi
done

if [ -z "${CGC_DB_DIR}" ]; then
  echo "[ERROR] cgc index did not produce a kuzudb under .codegraphcontext/"
  echo "Contents of .codegraphcontext:"
  find "${REPO_ROOT}/.codegraphcontext" -maxdepth 3 -type d 2>/dev/null || echo "(empty)"
  exit 1
fi

echo "Index complete. DB at: ${CGC_DB_DIR} ($(du -sh "${CGC_DB_DIR}" | cut -f1))"

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

tar -czf "${BUNDLE_PATH}" -C "${REPO_ROOT}" .codegraphcontext .cgcignore

cp "${MANIFEST}" "${BUILD_DIR}/manifest_for_bundle.json"
gunzip < "${BUNDLE_PATH}" > "${BUNDLE_PATH%.gz}"
tar -rf "${BUNDLE_PATH%.gz}" -C "${BUILD_DIR}" manifest.json
gzip -c "${BUNDLE_PATH%.gz}" > "${BUNDLE_PATH}"
rm -f "${BUNDLE_PATH%.gz}"

echo ""
echo "=== Build Complete ==="
echo "Bundle: ${BUNDLE_PATH}"
echo "Size:   $(du -sh "${BUNDLE_PATH}" | cut -f1)"
echo "SHA256: $(sha256sum "${BUNDLE_PATH}" | awk '{print $1}')"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  { echo "bundle_path=${BUNDLE_PATH}"; echo "bundle_name=${BUNDLE_NAME}"; } >> "${GITHUB_OUTPUT}"
fi

# Clean repo
rm -rf "${REPO_ROOT}/.codegraphcontext"