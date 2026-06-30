#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo ".env を作成しました。"
else
  echo ".env は既にあります。"
fi

echo
echo "X_BEARER_TOKEN と X_USER_ID または X_USERNAME を設定してください。"
echo "設定ファイルを開きます。"
open -e ".env"

echo
read -r -p "設定が終わったら、このウィンドウはEnterキーで閉じてください..."
