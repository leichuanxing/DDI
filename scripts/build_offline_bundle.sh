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

if [ -f "$ROOT_DIR/version.conf" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ROOT_DIR/version.conf"
  set +a
fi
export DDI_VERSION="${ddi_version:-0.0.0}"

echo "[2/7] Building local images (DDI_VERSION=$DDI_VERSION)"
cd "$ROOT_DIR"
docker compose build ddi-web ddi-pdns ddi-kea
docker pull mysql:8.4

echo "[3/7] Saving images"
docker save -o "$IMAGES_DIR/ddi-web-local.tar" ddi-web:local
docker save -o "$IMAGES_DIR/ddi-pdns-local.tar" ddi-pdns:local
docker save -o "$IMAGES_DIR/ddi-kea-local.tar" ddi-kea:local
docker save -o "$IMAGES_DIR/mysql-8.4.tar" mysql:8.4

echo "[4/7] Copying runtime files"
mkdir -p "$PACKAGE_DIR/docker" "$PACKAGE_DIR/scripts"
cp "$ROOT_DIR/docker-compose.offline.yml" "$PACKAGE_DIR/docker-compose.yml"
cp "$ROOT_DIR/.env.offline.example" "$PACKAGE_DIR/.env.example"
cp "$ROOT_DIR/version.conf" "$PACKAGE_DIR/version.conf"
cp -r "$ROOT_DIR/docker" "$PACKAGE_DIR/"
cp "$ROOT_DIR/scripts/install_offline_bundle.sh" "$PACKAGE_DIR/scripts/install.sh"

echo "[5/7] Writing bundle readme"
cat > "$PACKAGE_DIR/README-OFFLINE.md" <<'EOF'
# DDI 离线安装包说明

## 目录结构

与 `images` 同级应有顶层目录（默认名为 `offline_bundle`），其下包含：

- `package/docker-compose.yml`：离线部署 Compose
- `package/.env.example`：环境变量模板
- `package/version.conf`：发布版本号（`ddi_version`，构建镜像时已写入标签，运行时会注入 Web）
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
EOF

echo "[6/7] Packing tarball"
ARCH_TOP="$(basename "$OUTPUT_DIR")"
ARCH_PARENT="$(dirname "$OUTPUT_DIR")"
tar -czf "$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz" \
  -C "$ARCH_PARENT" \
  "$ARCH_TOP/images" "$ARCH_TOP/package"

echo "[7/7] Done"
echo "Bundle directory: $OUTPUT_DIR"
echo "Bundle tarball:   $OUTPUT_DIR/${BUNDLE_NAME}.tar.gz"
