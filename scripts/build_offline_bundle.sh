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

echo "[2/7] Building local images"
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
cp -r "$ROOT_DIR/docker" "$PACKAGE_DIR/"
cp "$ROOT_DIR/scripts/install_offline_bundle.sh" "$PACKAGE_DIR/scripts/install.sh"

echo "[5/7] Writing bundle readme"
cat > "$PACKAGE_DIR/README-OFFLINE.md" <<'EOF'
# DDI Offline Bundle

## Contents

- `docker-compose.yml`: offline deployment compose file
- `.env.example`: environment variable template
- `docker/`: MySQL init scripts, PowerDNS runtime files, Kea config files
- `scripts/install.sh`: offline image loading and startup script
- `../images/*.tar`: Docker image archives

## Offline installation

1. Copy this whole bundle directory to the target server.
2. Ensure Docker Engine and Docker Compose plugin are already installed.
3. Enter the package directory:

```bash
cd package
cp .env.example .env
bash scripts/install.sh
```

4. Access the system:

- `http://<server-ip>:8000/`
- default admin: `admin / admin123456`

## Notes

- Images are architecture-specific. Build and install on the same CPU architecture.
- `scripts/install.sh` loads all local tar images before starting containers.
- PowerDNS and Kea still expose DNS and DHCP service ports on the host.
EOF

echo "[6/7] Packing tarball"
tar -C "$OUTPUT_DIR" -czf "$OUTPUT_DIR/${BUNDLE_NAME}.tar.gz" images package

echo "[7/7] Done"
echo "Bundle directory: $OUTPUT_DIR"
echo "Bundle tarball:   $OUTPUT_DIR/${BUNDLE_NAME}.tar.gz"
