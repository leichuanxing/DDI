#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT_DIR/offline_bundle}"
BUNDLE_NAME="${2:-ddi-offline-bundle}"
IMAGES_DIR="$OUTPUT_DIR/images"
PACKAGE_DIR="$OUTPUT_DIR/package"

echo "[1/7] Preparing folders"
rm -rf "$OUTPUT_DIR"
mkdir -p "$IMAGES_DIR" "$PACKAGE_DIR"

# 从仓库主目录 version.conf 读取 ddi_version，作为 Docker 构建参数（不写死 source，避免误执行非赋值行）
VERSION_FILE="$ROOT_DIR/version.conf"
if [ -f "$VERSION_FILE" ]; then
  DDI_VERSION="$(
    grep -E '^[[:space:]]*ddi_version[[:space:]]*=' "$VERSION_FILE" | head -n1 | cut -d= -f2- |
      sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
  )"
fi
DDI_VERSION="${DDI_VERSION:-0.0.0}"
if [ ! -f "$VERSION_FILE" ]; then
  echo "WARN: 未找到 $VERSION_FILE，离线构建使用 DDI_VERSION=$DDI_VERSION" >&2
elif ! grep -qE '^[[:space:]]*ddi_version[[:space:]]*=' "$VERSION_FILE"; then
  echo "WARN: $VERSION_FILE 中无 ddi_version= 行，离线构建使用 DDI_VERSION=$DDI_VERSION" >&2
fi
export DDI_VERSION

# 镜像 tag 仅允许小写、数字、._-（与 OCI 标签规则一致）
DDI_IMAGE_TAG="$(printf '%s' "$DDI_VERSION" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/_/g')"
DDI_IMAGE_TAG="${DDI_IMAGE_TAG:-0.0.0}"

echo "[2/7] Building local images（来自 version.conf 的 DDI_VERSION=$DDI_VERSION）"
cd "$ROOT_DIR"
docker compose build ddi-web ddi-pdns ddi-kea
docker pull mysql:8.4

echo "[3/7] Tagging images with ddi_version and saving（镜像 tag: ${DDI_IMAGE_TAG}）"
for svc in ddi-web ddi-pdns ddi-kea; do
  docker tag "${svc}:local" "${svc}:${DDI_IMAGE_TAG}"
done
# 每个 tar 内同时包含 :local 与 :<version>，compose 仍用 :local；ddi_version 与 DDI_VERSION 仍为原始值
docker save -o "$IMAGES_DIR/ddi-web-local.tar" ddi-web:local "ddi-web:${DDI_IMAGE_TAG}"
docker save -o "$IMAGES_DIR/ddi-pdns-local.tar" ddi-pdns:local "ddi-pdns:${DDI_IMAGE_TAG}"
docker save -o "$IMAGES_DIR/ddi-kea-local.tar" ddi-kea:local "ddi-kea:${DDI_IMAGE_TAG}"
docker save -o "$IMAGES_DIR/mysql-8.4.tar" mysql:8.4

echo "[4/7] Copying runtime files"
mkdir -p "$PACKAGE_DIR/docker" "$PACKAGE_DIR/scripts"
cp "$ROOT_DIR/docker-compose.offline.yml" "$PACKAGE_DIR/docker-compose.yml"
cp "$ROOT_DIR/.env.offline.example" "$PACKAGE_DIR/.env.example"
cp "$ROOT_DIR/version.conf" "$PACKAGE_DIR/version.conf"
cp -r "$ROOT_DIR/docker" "$PACKAGE_DIR/"
cp "$ROOT_DIR/scripts/install_offline_bundle.sh" "$PACKAGE_DIR/scripts/install.sh"

# 生成文件写入与 version.conf 一致的版本（供 .env 与展示）
{
  printf '\n# 与 package/version.conf 中 ddi_version 一致（离线包生成时自动写入）\n'
  printf 'DDI_VERSION=%s\n' "$DDI_VERSION"
} >>"$PACKAGE_DIR/.env.example"

printf '%s\n' "ddi_version=${DDI_VERSION}" >"$PACKAGE_DIR/BUNDLE_VERSION"
date -u +"%Y-%m-%dT%H:%MZ" >"$PACKAGE_DIR/BUNDLE_BUILT_AT" 2>/dev/null || date +"%Y-%m-%dT%H:%M%z" >"$PACKAGE_DIR/BUNDLE_BUILT_AT"

echo "[5/7] Writing bundle readme"
{
  printf '%s\n\n' "# DDI 离线安装包说明"
  printf '%s\n\n' "- **本包 ddi_version**：\`${DDI_VERSION}\`（与 \`package/version.conf\`、\`.env.example\` 中 \`DDI_VERSION\` 一致）"
  printf '%s\n\n' "- **镜像标签**：\`ddi-web:local\` 与 \`ddi-web:${DDI_IMAGE_TAG}\`（及 pdns、kea 同理）已打入同一 tar；构建参数 \`DDI_VERSION\` 为 \`${DDI_VERSION}\`，\`docker inspect\` 可见 \`org.opencontainers.image.version\`。"
  cat <<'PART2'
## 目录结构

与 `images` 同级应有顶层目录（默认名为 `offline_bundle`），其下包含：

- `package/docker-compose.yml`：离线部署 Compose
- `package/.env.example`：环境变量模板（已含 `DDI_VERSION`）
- `package/version.conf`：发布版本号（Web `env_file` 与侧栏展示）
- `package/BUNDLE_VERSION` / `package/BUNDLE_BUILT_AT`：打包版本与时间戳
- `package/docker/`：MySQL 初始化、PowerDNS / Kea 配置
- `package/scripts/install.sh`：加载镜像并启动容器
- `images/*.tar`：Docker 镜像归档

## 离线安装步骤

1. 将 `ddi-offline-bundle.tar.gz`（或整个 `offline_bundle` 目录）拷贝到目标机。
2. 目标机需已安装 Docker Engine 与 Docker Compose 插件。
3. 解压并进入 `package`（顶层目录名与打包时输出目录的最后一级相同，默认 `offline_bundle`）：

```bash
tar -xzf ddi-offline-bundle.tar.gz
cd offline_bundle/package
cp .env.example .env
bash scripts/install.sh
```

4. 访问：`http://<服务器IP>:8000/`（默认账号 `admin` / `admin123456`）。

## 说明

- 镜像与 CPU 架构相关，打包机与安装机架构需一致（如均为 x86_64）。
- `install.sh` 会从上一级的 `images/` 加载所有 tar 后再 `docker compose up`。
- DNS（53）与 DHCP（67/547）等端口仍会映射到宿主机。
PART2
} >"$PACKAGE_DIR/README-OFFLINE.md"

echo "[6/7] Packing tarball"
ARCH_TOP="$(basename "$OUTPUT_DIR")"
ARCH_PARENT="$(dirname "$OUTPUT_DIR")"
tar -czf "$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz" \
  -C "$ARCH_PARENT" \
  "$ARCH_TOP/images" "$ARCH_TOP/package"

echo "[7/7] Done"
echo "Bundle directory: $OUTPUT_DIR"
echo "Bundle tarball:   $OUTPUT_DIR/${BUNDLE_NAME}.tar.gz"
