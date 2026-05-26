#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# build_codegraph.sh
# 在 CI 环境 (GitHub Actions) 中运行 cgc index 并打包分发 bundle。
#
# 用法: ./scripts/build_codegraph.sh
#
# 环境变量:
#   GITHUB_SHA         - Git commit SHA (CI 自动)
#   GITHUB_WORKSPACE   - 仓库根路径 (CI 自动)
#   GITHUB_REPOSITORY  - 仓库名 (CI 自动)
#   CGC_BIN            - cgc 可执行文件路径 (默认 "cgc")
# ============================================================

: "${CGC_BIN:=cgc}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"

REPO_ROOT="${GITHUB_WORKSPACE}"
BUILD_DIR="$(mktemp -d)"
CGC_DB_PARENT="${BUILD_DIR}/.codegraphcontext"
CGC_DB_PATH="${CGC_DB_PARENT}/kuzudb"
MANIFEST="${BUILD_DIR}/manifest.json"
BUNDLE_NAME="codegraph-${GITHUB_SHA}.tar.gz"
BUNDLE_PATH="${REPO_ROOT}/${BUNDLE_NAME}"
CGCIGNORE="${REPO_ROOT}/.cgcignore"

cleanup() { rm -rf "${BUILD_DIR}"; }
trap cleanup EXIT

echo "=== CodeGraphContext Build ==="
echo "Commit:    ${GITHUB_SHA}"
echo "Repo:      ${REPO_ROOT}"
echo "Build dir: ${BUILD_DIR}"

# --------------------------------------------------
# 1. 确保 .cgcignore 存在
# --------------------------------------------------
if [ ! -f "${CGCIGNORE}" ]; then
  echo "[ERROR] .cgcignore not found at ${CGCIGNORE}"
  echo "Create .cgcignore in the repo root before building."
  exit 1
fi
echo "Ignore file: ${CGCIGNORE} ($(wc -l < "${CGCIGNORE}") lines)"

# --------------------------------------------------
# 2. 创建构建目录 (kuzudb 需要父目录存在但 db-path 本身不存在)
# --------------------------------------------------
mkdir -p "${CGC_DB_PARENT}"

# --------------------------------------------------
# 3. 运行 cgc index
# --------------------------------------------------
echo ""
echo "--- Running cgc index ---"

# cgc 0.4.11 实测:
#   --db kuzudb  全局 flag，指定数据库后端
#   --db-path    全局 flag，指定库路径 (kuzudb 要求该路径不存在，由它自己创建)
#   .cgcignore   在 repo 根目录自动被发现
"${CGC_BIN}" \
  --db kuzudb \
  --db-path "${CGC_DB_PATH}" \
  index "${REPO_ROOT}"

# 确认数据库已生成
if [ ! -d "${CGC_DB_PATH}" ]; then
  echo "[ERROR] cgc index did not produce database at ${CGC_DB_PATH}"
  exit 1
fi

echo "Index complete. DB size: $(du -sh "${CGC_DB_PATH}" | cut -f1)"

# --------------------------------------------------
# 4. 写入 manifest.json
# --------------------------------------------------
# cgc version 输出到 stderr 且 exit code 不为 0
CGC_VERSION="$("${CGC_BIN}" version 2>&1 || true)"
CGC_VERSION="${CGC_VERSION##* }"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BUILD_HOST="$(hostname 2>/dev/null || echo "github-actions")"

cat > "${MANIFEST}" <<EOF
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
EOF

echo ""
echo "=== manifest.json ==="
cat "${MANIFEST}"

# --------------------------------------------------
# 5. 打包 bundle
# --------------------------------------------------
echo ""
echo "--- Creating bundle: ${BUNDLE_NAME} ---"

cp "${CGCIGNORE}" "${BUILD_DIR}/.cgcignore"

tar -czf "${BUNDLE_PATH}" \
  -C "${BUILD_DIR}" \
  .codegraphcontext \
  manifest.json \
  .cgcignore

BUNDLE_SHA256="$(sha256sum "${BUNDLE_PATH}" | awk '{print $1}')"
BUNDLE_SIZE="$(du -sh "${BUNDLE_PATH}" | cut -f1)"

echo ""
echo "=== Build Complete ==="
echo "Bundle:  ${BUNDLE_PATH}"
echo "Size:    ${BUNDLE_SIZE}"
echo "SHA256:  ${BUNDLE_SHA256}"

# GitHub Actions output
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  { echo "bundle_path=${BUNDLE_PATH}"; echo "bundle_name=${BUNDLE_NAME}"; echo "bundle_sha256=${BUNDLE_SHA256}"; } >> "${GITHUB_OUTPUT}"
fi
