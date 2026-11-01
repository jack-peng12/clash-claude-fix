#!/usr/bin/env bash
# Build the USB/offline install package: dist/supplier-agent-<version>/ (+ .zip)
# Run on any machine with Docker (Linux/macOS/WSL). Windows targets need Docker Desktop (x86_64).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import app; print(app.__version__)")
OUT="dist/supplier-agent-${VERSION}"
rm -rf "$OUT" && mkdir -p "$OUT/images"
docker build --platform linux/amd64 -t supplier-agent:latest .
docker save supplier-agent:latest -o "$OUT/images/supplier-agent.tar"
cp docker-compose.yml .env.example "$OUT/"
cp deploy/windows/*.bat "$OUT/"
cp docs/INSTALL_WINDOWS.md docs/USER_GUIDE.md "$OUT/" 2>/dev/null || true
for f in "$OUT"/*.bat; do sed -i 's/\r\?$/\r/' "$f"; done
(cd dist && rm -f "supplier-agent-${VERSION}.zip" && zip -qr "supplier-agent-${VERSION}.zip" "supplier-agent-${VERSION}")
echo "package: dist/supplier-agent-${VERSION}.zip"
