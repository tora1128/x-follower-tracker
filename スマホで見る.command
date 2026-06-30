#!/bin/bash
set -e

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
REPORT_PATH="reports/current.html"

get_lan_ip() {
  for iface in en0 en1 en2; do
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    if [ -n "$ip" ]; then
      echo "$ip"
      return 0
    fi
  done
  return 1
}

LAN_IP="$(get_lan_ip || true)"

echo "スマホ表示用サーバーを起動します。"
echo

if [ ! -f "$REPORT_PATH" ]; then
  echo "まだ $REPORT_PATH がありません。"
  echo "先に「今すぐ確認.command」を実行して、確認画面を作成してください。"
  echo
fi

if [ -n "$LAN_IP" ]; then
  echo "スマホが同じWi-Fiにいる場合、このURLをブラウザで開いてください:"
  echo "http://$LAN_IP:$PORT/$REPORT_PATH"
else
  echo "MacのWi-Fi IPアドレスを自動取得できませんでした。"
  echo "システム設定 > Wi-Fi > 詳細 でIPアドレスを確認し、次の形式で開いてください:"
  echo "http://MacのIPアドレス:$PORT/$REPORT_PATH"
fi

echo
echo "Macではこちらを開きます:"
echo "http://localhost:$PORT/$REPORT_PATH"
echo
echo "終了するには、このウィンドウで control + C を押してください。"
echo

open "http://localhost:$PORT/$REPORT_PATH" 2>/dev/null || true
/usr/bin/python3 -m http.server "$PORT" --bind 0.0.0.0
