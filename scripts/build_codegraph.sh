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
CGC_DB_DIR="${BUILD_DIR}/.codegraphcontext/kuzudb"
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
# 2. 创建构建目录
# --------------------------------------------------
mkdir -p "${CGC_DB_DIR}"

# --------------------------------------------------
# 3. 运行 cgc index (全局 --db + --db-path)
# --------------------------------------------------
echo ""
echo "--- Running cgc index ---"

# cgc 0.4.11 实测参数:
#   --db       全局 flag，指定数据库后端 (kuzudb)
#   --db-path  全局 flag，指定数据库路径
#   .cgcignore 在 repo 根目录自动被发现
"${CGC_BIN}" \
  --db kuzudb \
  --db-path "${CGC_DB_DIR}" \
  index "${REPO_ROOT}"

# 确认 kuzudb 文件已生成
if [ ! -f "${CGC_DB_DIR}/catalog.kz" ] && [ ! -d "${CGC_DB_DIR}" ]; then
  echo "[ERROR] cgc index did not produce database at ${CGC_DB_DIR}"
  exit 1
fi

echo "Index complete. DB size: $(du -sh "${CGC_DB_DIR}" | cut -f1)"

# --------------------------------------------------
# 4. 写入 manifest.json
# --------------------------------------------------
# cgc version 输出到 stderr 且 exit code 不为 0
CGC_VERSION="$("${CGC_BIN}" version 2>&1 || true)"
CGC_VERSION="${CGC_VERSION##* }"  # 提取 "CodeGraphContext 0.4.11" 中的版本号
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
# 5. 打包 bundle: .codegraphcontext/ + manifest.json + .cgcignore
# --------------------------------------------------
echo ""
echo "--- Creating bundle: ${BUNDLE_NAME} ---"

# 将 .cgcignore 复制到构建目录供打包
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
  echo "bundle_path=${BUNDLE_PATH}" >> "${GITHUB_OUTPUT}"
  echo "bundle_name=${BUNDLE_NAME}" >> "${GITHUB_OUTPUT}"
  echo "bundle_sha256=${BUNDLE_SHA256}" >> "${GITHUB_OUTPUT}"
fi
