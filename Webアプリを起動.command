#!/bin/bash
set -e

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
KEY="$(/usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"

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

echo "X Follower Tracker Webアプリを起動します。"
echo

if [ -n "$LAN_IP" ]; then
  echo "スマホが同じWi-Fiにいる場合、このURLをブラウザで開いてください:"
  echo "http://$LAN_IP:$PORT/?key=$KEY"
else
  echo "MacのWi-Fi IPアドレスを自動取得できませんでした。"
  echo "システム設定 > Wi-Fi > 詳細 でIPアドレスを確認し、次の形式で開いてください:"
  echo "http://MacのIPアドレス:$PORT/?key=$KEY"
fi

echo
echo "Macではこちらを開きます:"
echo "http://localhost:$PORT/?key=$KEY"
echo
echo "終了するには、このウィンドウで control + C を押してください。"
echo

open "http://localhost:$PORT/?key=$KEY" 2>/dev/null || true
/usr/bin/python3 web_app.py --host 0.0.0.0 --port "$PORT" --key "$KEY" --private-mode
