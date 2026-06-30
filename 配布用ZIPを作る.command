#!/bin/bash
set -e

cd "$(dirname "$0")"
./build_distribution.sh

echo
echo "dist フォルダに配布用ZIPを作成しました。"
read -r -p "Enterキーで閉じます..."
