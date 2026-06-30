#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="x-follower-tracker"
VERSION="${1:-$(date +%Y%m%d)}"
DIST_DIR="dist"
STAGING_DIR="$DIST_DIR/$APP_NAME"
ZIP_PATH="$DIST_DIR/${APP_NAME}-${VERSION}.zip"

rm -rf "$STAGING_DIR" "$ZIP_PATH"
mkdir -p "$STAGING_DIR"

cp README.md "$STAGING_DIR/"
cp tracker.py "$STAGING_DIR/"
cp view_now.py "$STAGING_DIR/"
cp web_app.py "$STAGING_DIR/"
cp .env.example "$STAGING_DIR/"
cp .env.cloud.example "$STAGING_DIR/"
cp Procfile "$STAGING_DIR/"
cp render.yaml "$STAGING_DIR/"
cp runtime.txt "$STAGING_DIR/"
cp Dockerfile "$STAGING_DIR/"
cp "スマホだけで使う配布手順.md" "$STAGING_DIR/"
cp "初期設定.command" "$STAGING_DIR/"
cp "今すぐ確認.command" "$STAGING_DIR/"
cp "スマホで見る.command" "$STAGING_DIR/"
cp "Webアプリを起動.command" "$STAGING_DIR/"
cp build_distribution.sh "$STAGING_DIR/"
cp "配布用ZIPを作る.command" "$STAGING_DIR/"

chmod +x "$STAGING_DIR/tracker.py" \
  "$STAGING_DIR/view_now.py" \
  "$STAGING_DIR/web_app.py" \
  "$STAGING_DIR/build_distribution.sh" \
  "$STAGING_DIR/初期設定.command" \
  "$STAGING_DIR/今すぐ確認.command" \
  "$STAGING_DIR/スマホで見る.command" \
  "$STAGING_DIR/Webアプリを起動.command" \
  "$STAGING_DIR/配布用ZIPを作る.command"

mkdir -p "$STAGING_DIR/data" "$STAGING_DIR/reports"

(cd "$DIST_DIR" && zip -qr "$(basename "$ZIP_PATH")" "$APP_NAME")

echo "created: $ZIP_PATH"
