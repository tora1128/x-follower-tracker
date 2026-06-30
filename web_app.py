#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import tracker
import view_now


ROOT = Path(__file__).resolve().parent


def format_dt(value: str) -> str:
    if not value:
        return "-"
    return view_now.format_dt(value)


def load_latest_snapshot() -> dict[str, Any] | None:
    return tracker.load_previous_snapshot()


def compare_with_previous_midnight() -> dict[str, Any]:
    tracker.load_env(ROOT / ".env")
    bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not bearer_token:
        raise tracker.TrackerError("Set X_BEARER_TOKEN in .env")

    previous_snapshot = tracker.load_snapshot_from_previous_midnight()
    if previous_snapshot is None:
        raise tracker.TrackerError("No history snapshot. Run tracker.py once first.")

    user_id = tracker.resolve_user_id(bearer_token)
    fetched_at = tracker.utc_now_iso()
    followers = tracker.fetch_followers(bearer_token, user_id, None)

    previous = tracker.follower_map(previous_snapshot)
    current = {item["id"]: item for item in followers if item.get("id")}
    removed = [previous[item_id] for item_id in sorted(previous.keys() - current.keys())]

    return {
        "target_user_id": user_id,
        "fetched_at": fetched_at,
        "previous_fetched_at": str(previous_snapshot.get("fetched_at", "")),
        "current_count": len(current),
        "previous_count": len(previous),
        "removed": removed,
        "followers": followers,
    }


def save_current_snapshot() -> dict[str, Any]:
    tracker.load_env(ROOT / ".env")
    bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not bearer_token:
        raise tracker.TrackerError("Set X_BEARER_TOKEN in .env")

    user_id = tracker.resolve_user_id(bearer_token)
    previous_snapshot = tracker.load_previous_snapshot()
    previous = tracker.follower_map(previous_snapshot)

    fetched_at = tracker.utc_now_iso()
    followers = tracker.fetch_followers(bearer_token, user_id, None)
    current = {item["id"]: item for item in followers if item.get("id")}
    removed = [previous[item_id] for item_id in sorted(previous.keys() - current.keys())]

    snapshot = {
        "target_user_id": user_id,
        "fetched_at": fetched_at,
        "count": len(followers),
        "followers": followers,
    }
    snapshot_path = tracker.write_snapshot(snapshot)

    removed_path = None
    if previous_snapshot is not None:
        report_stamp = fetched_at.replace(":", "").replace("+", "Z")
        removed_path = tracker.REPORTS_DIR / f"removed_{report_stamp}.csv"
        tracker.write_csv(removed_path, removed)

    return {
        "fetched_at": fetched_at,
        "current_count": len(current),
        "removed_count": len(removed),
        "snapshot_path": str(snapshot_path),
        "removed_path": str(removed_path) if removed_path else "",
    }


def render_message(kind: str, message: str) -> str:
    if not message:
        return ""
    title = "エラー" if kind == "error" else "完了"
    return f"""
      <section class="notice {html.escape(kind)}">
        <strong>{title}</strong>
        <p>{html.escape(message)}</p>
      </section>
    """


def render_result(result: dict[str, Any] | None) -> str:
    if result is None:
        latest = load_latest_snapshot()
        latest_text = "保存データなし"
        count_text = "-"
        if latest:
            latest_text = format_dt(str(latest.get("fetched_at", "")))
            count_text = str(latest.get("count", "-"))
        return f"""
          <section class="empty-state">
            <h2>確認待ち</h2>
            <p>「最新確認」を押すと、スマホから現在のフォロワー状況を確認できます。</p>
            <div class="summary single">
              <div><span>最新保存</span><strong>{html.escape(latest_text)}</strong></div>
              <div><span>保存人数</span><strong>{html.escape(count_text)}</strong></div>
            </div>
          </section>
        """

    delta = result["current_count"] - result["previous_count"]
    delta_class = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
    removed_rows = view_now.render_account_rows(result["removed"])

    return f"""
      <section class="summary">
        <div><span>現在</span><strong>{result["current_count"]}</strong></div>
        <div><span>前回比</span><strong class="{delta_class}">{delta:+d}</strong></div>
        <div><span>減った人</span><strong class="negative">{len(result["removed"])}</strong></div>
      </section>
      <section class="meta">
        <div>現時点: {html.escape(format_dt(result["fetched_at"]))}</div>
        <div>比較元: {html.escape(format_dt(result["previous_fetched_at"]))}</div>
      </section>
      <section class="table-section">
        <h2>減った人</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>アカウント</th><th>名前</th><th>ID</th><th>フォロワー</th><th>フォロー</th></tr></thead>
            <tbody>{removed_rows}</tbody>
          </table>
        </div>
      </section>
    """


def render_page(
    *,
    key: str,
    result: dict[str, Any] | None = None,
    error: str = "",
    status: str = "",
) -> str:
    key_param = urlencode({"key": key})
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Follower Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #6b7280;
      --line: #d8dee4;
      --accent: #0969da;
      --green: #1a7f37;
      --red: #cf222e;
      --shadow: 0 1px 2px rgba(31, 35, 40, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{
      width: min(1040px, 100%);
      margin: 0 auto;
      padding: 22px 14px 44px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 16px;
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    button {{
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      padding: 0 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      box-shadow: var(--shadow);
    }}
    button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      margin-top: 12px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0;
      overflow: hidden;
    }}
    .summary.single {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: none;
    }}
    .summary div {{
      padding: 16px;
      border-right: 1px solid var(--line);
    }}
    .summary div:last-child {{ border-right: 0; }}
    .summary span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .summary strong {{
      display: block;
      font-size: 30px;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}
    .neutral {{ color: var(--muted); }}
    .meta, .notice, .empty-state {{
      padding: 16px;
      color: var(--muted);
      font-size: 14px;
    }}
    .notice strong, .empty-state h2 {{
      display: block;
      margin: 0 0 6px;
      color: var(--text);
      font-size: 18px;
    }}
    .notice p, .empty-state p {{ margin: 0; }}
    .notice.error {{
      border-color: #ffd1d5;
      background: #fff7f7;
      color: var(--red);
    }}
    .table-section {{
      overflow: hidden;
    }}
    h2 {{
      margin: 0;
      padding: 14px 16px;
      font-size: 18px;
      border-bottom: 1px solid var(--line);
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      min-width: 680px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
      background: #fafafa;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
    }}
    .empty {{
      color: var(--muted);
      text-align: center;
      padding: 22px;
    }}
    @media (max-width: 700px) {{
      header {{
        display: block;
      }}
      .actions {{
        justify-content: stretch;
        margin-top: 14px;
      }}
      button {{
        flex: 1 1 140px;
      }}
      .summary div {{
        padding: 12px 10px;
      }}
      .summary strong {{
        font-size: 24px;
      }}
      main {{
        padding-left: 10px;
        padding-right: 10px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>X Follower Tracker</h1>
        <div class="subtitle">スマホから最新確認できます</div>
      </div>
      <div class="actions">
        <form method="post" action="/refresh?{key_param}">
          <button class="primary" type="submit">最新確認</button>
        </form>
        <form method="post" action="/save?{key_param}">
          <button type="submit">正式保存</button>
        </form>
      </div>
    </header>
    {render_message("error", error)}
    {render_message("status", status)}
    {render_result(result)}
  </main>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    app_key = ""
    last_result: dict[str, Any] | None = None
    last_status = ""
    last_error = ""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def key_is_valid(self) -> bool:
        query = parse_qs(urlparse(self.path).query)
        return query.get("key", [""])[0] == self.app_key

    def redirect_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?{urlencode({'key': self.app_key})}")
        self.end_headers()

    def send_html(self, status: HTTPStatus = HTTPStatus.OK) -> None:
        page = render_page(
            key=self.app_key,
            result=self.last_result,
            error=self.last_error,
            status=self.last_status,
        )
        encoded = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def require_key(self) -> bool:
        if self.key_is_valid():
            return True
        self.last_error = "URLのアクセスキーが違います。起動ウィンドウに表示されたURLを開いてください。"
        self.last_status = ""
        self.send_html(HTTPStatus.FORBIDDEN)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            encoded = b"ok\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        if parsed.path == "/":
            if not self.require_key():
                return
            self.send_html()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.require_key():
            return

        parsed = urlparse(self.path)
        self.last_error = ""
        self.last_status = ""

        try:
            if parsed.path == "/refresh":
                self.last_result = compare_with_previous_midnight()
                self.last_status = "最新確認が完了しました。"
            elif parsed.path == "/save":
                saved = save_current_snapshot()
                self.last_status = (
                    f"正式保存しました。現在 {saved['current_count']} 人、"
                    f"減った人 {saved['removed_count']} 人。"
                )
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        except tracker.TrackerError as error:
            self.last_error = str(error)
        except Exception as error:
            self.last_error = f"Unexpected error: {error}"

        self.redirect_home()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the X Follower Tracker web app.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--key", default=os.getenv("WEB_APP_KEY", ""))
    args = parser.parse_args()

    AppHandler.app_key = args.key or secrets.token_urlsafe(12)
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)

    print(f"server: http://{args.host}:{args.port}/?key={AppHandler.app_key}")
    print("Press control + C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
