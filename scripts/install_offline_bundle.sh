#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_DIR="$(cd "$PACKAGE_DIR/.." && pwd)"
IMAGES_DIR="$BUNDLE_DIR/images"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not installed"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required but not installed"
  exit 1
fi

if [ ! -d "$IMAGES_DIR" ]; then
  echo "image directory not found: $IMAGES_DIR"
  echo "请解压完整离线包（需与 package 同级存在 images/），并在 package 目录下执行：bash scripts/install.sh"
  exit 1
fi

if [ ! -f "$PACKAGE_DIR/docker-compose.yml" ]; then
  echo "docker-compose.yml not found in: $PACKAGE_DIR"
  echo "请勿在源码仓库根目录直接运行本脚本；应使用离线包内的 package/scripts/install.sh"
  exit 1
fi

echo "[1/4] Loading offline images"
for image_tar in \
  "$IMAGES_DIR/mysql-8.4.tar" \
  "$IMAGES_DIR/ddi-web-local.tar" \
  "$IMAGES_DIR/ddi-pdns-local.tar" \
  "$IMAGES_DIR/ddi-kea-local.tar"
do
  if [ ! -f "$image_tar" ]; then
    echo "missing image archive: $image_tar"
    exit 1
  fi
  docker load -i "$image_tar"
done

echo "[2/4] Preparing env file"
cd "$PACKAGE_DIR"
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp ".env.example" ".env"
fi

echo "[3/4] Starting containers"
docker compose up -d

echo "[4/4] Deployment started"
docker compose ps
