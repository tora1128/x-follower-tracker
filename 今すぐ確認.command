#!/bin/bash
set -e

cd "$(dirname "$0")"
/usr/bin/python3 view_now.py

echo
echo "完了しました。ブラウザで reports/current.html を開きました。"
echo "このウィンドウは閉じて大丈夫です。"
read -r -p "Enterキーで閉じます..."
