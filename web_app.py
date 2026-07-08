#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hmac
import hashlib
import html
import json
import os
import secrets
from datetime import datetime, time as datetime_time, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import tracker
import view_now


ROOT = Path(__file__).resolve().parent
STORAGE_ROOT = Path(os.getenv("XFT_STORAGE_DIR", str(tracker.STORAGE_DIR)))


def public_mode_enabled() -> bool:
    value = os.getenv("PUBLIC_MODE", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def site_password() -> str:
    return os.getenv("SITE_PASSWORD", "").strip()


def auth_secret() -> str:
    return os.getenv("AUTH_SECRET", site_password() or "x-follower-tracker-local-secret")


def format_dt(value: str) -> str:
    if not value:
        return "-"
    return view_now.format_dt(value)


def workspace_dir(workspace_key: str) -> Path:
    workspace_key = workspace_key.strip()
    if len(workspace_key) < 6:
        raise tracker.TrackerError("合言葉は6文字以上で入力してください。")
    digest = hashlib.sha256(workspace_key.encode("utf-8")).hexdigest()[:32]
    return STORAGE_ROOT / "workspaces" / digest


def data_dir_for(workspace: Path) -> Path:
    return workspace / "data"


def reports_dir_for(workspace: Path) -> Path:
    return workspace / "reports"


def latest_snapshot_path_for(workspace: Path) -> Path:
    return data_dir_for(workspace) / "followers_latest.json"


def load_previous_snapshot_for(workspace: Path) -> dict[str, Any] | None:
    path = latest_snapshot_path_for(workspace)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_snapshot_dt(snapshot: dict[str, Any]) -> datetime | None:
    fetched_at = str(snapshot.get("fetched_at", ""))
    if not fetched_at:
        return None
    return datetime.fromisoformat(fetched_at)


def load_history_snapshots_for(workspace: Path) -> list[dict[str, Any]]:
    snapshots = []
    for path in sorted(data_dir_for(workspace).glob("followers_*.json")):
        if path.name == latest_snapshot_path_for(workspace).name:
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["_snapshot_path"] = str(path)
        snapshots.append(snapshot)
    return snapshots


def load_snapshot_from_previous_midnight_for(workspace: Path) -> dict[str, Any] | None:
    snapshots = load_history_snapshots_for(workspace)
    if not snapshots:
        return None

    now_local = datetime.now().astimezone()
    previous_day = now_local.date() - timedelta(days=1)
    target = datetime.combine(previous_day, datetime_time.min, tzinfo=now_local.tzinfo)

    candidates = []
    for snapshot in snapshots:
        fetched_at = parse_snapshot_dt(snapshot)
        if fetched_at is None:
            continue
        fetched_at_local = fetched_at.astimezone(target.tzinfo)
        if fetched_at_local.date() == previous_day and fetched_at_local >= target:
            candidates.append(snapshot)

    if not candidates:
        return None

    def fetched_at_local(snapshot: dict[str, Any]) -> datetime:
        fetched_at = parse_snapshot_dt(snapshot) or target
        return fetched_at.astimezone(target.tzinfo)

    return min(candidates, key=fetched_at_local)


def load_compare_snapshot_for(workspace: Path) -> dict[str, Any] | None:
    return load_snapshot_from_previous_midnight_for(workspace) or load_previous_snapshot_for(workspace)


def write_snapshot_for(workspace: Path, snapshot: dict[str, Any]) -> Path:
    data_dir_for(workspace).mkdir(parents=True, exist_ok=True)
    reports_dir_for(workspace).mkdir(parents=True, exist_ok=True)

    timestamp = snapshot["fetched_at"].replace(":", "").replace("+", "Z")
    history_path = data_dir_for(workspace) / f"followers_{timestamp}.json"
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)

    history_path.write_text(serialized + "\n", encoding="utf-8")
    latest_snapshot_path_for(workspace).write_text(serialized + "\n", encoding="utf-8")
    return history_path


def write_csv_for(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "id",
        "username",
        "name",
        "verified",
        "followers_count",
        "following_count",
        "tweet_count",
        "listed_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            metrics = row.get("public_metrics", {}) or {}
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "username": row.get("username", ""),
                    "name": row.get("name", ""),
                    "verified": row.get("verified", ""),
                    "followers_count": metrics.get("followers_count", ""),
                    "following_count": metrics.get("following_count", ""),
                    "tweet_count": metrics.get("tweet_count", ""),
                    "listed_count": metrics.get("listed_count", ""),
                }
            )


def resolve_user_id_from_inputs(bearer_token: str, user_id: str, username: str) -> str:
    user_id = user_id.strip()
    if user_id:
        return user_id

    username = username.strip().lstrip("@")
    if not username:
        raise tracker.TrackerError("Xユーザー名を入力してください。")

    payload = tracker.request_json(
        f"/users/by/username/{username}",
        {"user.fields": "id,username,name"},
        bearer_token,
    )
    data = payload.get("data")
    if not data or not data.get("id"):
        raise tracker.TrackerError(f"ユーザー名を確認できませんでした: {username}")
    return str(data["id"])


def public_inputs(form: dict[str, list[str]]) -> dict[str, str]:
    return {
        "workspace_key": form.get("workspace_key", [""])[0].strip(),
        "bearer_token": form.get("bearer_token", [""])[0].strip(),
        "user_id": form.get("user_id", [""])[0].strip(),
        "username": form.get("username", [""])[0].strip().lstrip("@"),
    }


def fetch_current_from_inputs(values: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    bearer_token = values["bearer_token"]
    if not bearer_token:
        raise tracker.TrackerError("X API Bearer Tokenを入力してください。")
    user_id = resolve_user_id_from_inputs(bearer_token, values["user_id"], values["username"])
    followers = tracker.fetch_followers(bearer_token, user_id, None)
    return user_id, followers


def compare_public(values: dict[str, str]) -> dict[str, Any]:
    workspace = workspace_dir(values["workspace_key"])
    previous_snapshot = load_compare_snapshot_for(workspace)
    if previous_snapshot is None:
        raise tracker.TrackerError("比較元がありません。最初に「正式保存」を1回押してください。")

    user_id, followers = fetch_current_from_inputs(values)
    fetched_at = tracker.utc_now_iso()

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


def save_public(values: dict[str, str]) -> dict[str, Any]:
    workspace = workspace_dir(values["workspace_key"])
    previous_snapshot = load_previous_snapshot_for(workspace)
    previous = tracker.follower_map(previous_snapshot)

    user_id, followers = fetch_current_from_inputs(values)
    fetched_at = tracker.utc_now_iso()
    current = {item["id"]: item for item in followers if item.get("id")}
    removed = [previous[item_id] for item_id in sorted(previous.keys() - current.keys())]

    snapshot = {
        "target_user_id": user_id,
        "target_username": values["username"],
        "fetched_at": fetched_at,
        "count": len(followers),
        "followers": followers,
    }
    snapshot_path = write_snapshot_for(workspace, snapshot)

    removed_path = ""
    if previous_snapshot is not None:
        report_stamp = fetched_at.replace(":", "").replace("+", "Z")
        csv_path = reports_dir_for(workspace) / f"removed_{report_stamp}.csv"
        write_csv_for(csv_path, removed)
        removed_path = str(csv_path)

    return {
        "fetched_at": fetched_at,
        "current_count": len(current),
        "removed_count": len(removed),
        "snapshot_path": str(snapshot_path),
        "removed_path": removed_path,
    }


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


def render_result(result: dict[str, Any] | None, latest: dict[str, Any] | None = None) -> str:
    if result is None:
        latest_text = "保存データなし"
        count_text = "-"
        if latest:
            latest_text = format_dt(str(latest.get("fetched_at", "")))
            count_text = str(latest.get("count", "-"))
        return f"""
          <section class="empty-state">
            <h2>確認待ち</h2>
            <p>最初に「正式保存」を押して、次回から「最新確認」で減った人を確認します。</p>
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


def styles() -> str:
    return """
    :root {
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
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    main {
      width: min(1040px, 100%);
      margin: 0 auto;
      padding: 22px 14px 44px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 16px;
    }
    h1 {
      margin: 0 0 4px;
      font-size: 24px;
      letter-spacing: 0;
    }
    h2 {
      margin: 0;
      padding: 14px 16px;
      font-size: 18px;
      border-bottom: 1px solid var(--line);
    }
    .subtitle, .hint {
      color: var(--muted);
      font-size: 14px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      margin-top: 12px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }
    input {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      font-weight: 400;
    }
    .full { grid-column: 1 / -1; }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .form-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 0 16px 16px;
    }
    button {
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
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0;
      overflow: hidden;
    }
    .summary.single {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: none;
    }
    .summary div {
      padding: 16px;
      border-right: 1px solid var(--line);
    }
    .summary div:last-child { border-right: 0; }
    .summary span {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }
    .summary strong {
      display: block;
      font-size: 30px;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }
    .positive { color: var(--green); }
    .negative { color: var(--red); }
    .neutral { color: var(--muted); }
    .meta, .notice, .empty-state {
      padding: 16px;
      color: var(--muted);
      font-size: 14px;
    }
    .notice strong, .empty-state h2 {
      display: block;
      margin: 0 0 6px;
      color: var(--text);
      font-size: 18px;
      padding: 0;
      border: 0;
    }
    .notice p, .empty-state p { margin: 0; }
    .notice.error {
      border-color: #ffd1d5;
      background: #fff7f7;
      color: var(--red);
    }
    .table-section { overflow: hidden; }
    .table-wrap {
      width: 100%;
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      min-width: 680px;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-weight: 700;
      background: #fafafa;
    }
    tr:last-child td { border-bottom: 0; }
    a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
    }
    .empty {
      color: var(--muted);
      text-align: center;
      padding: 22px;
    }
    @media (max-width: 700px) {
      header { display: block; }
      .actions {
        justify-content: stretch;
        margin-top: 14px;
      }
      button { flex: 1 1 140px; }
      .form-grid { grid-template-columns: 1fr; }
      .summary div { padding: 12px 10px; }
      .summary strong { font-size: 24px; }
      main {
        padding-left: 10px;
        padding-right: 10px;
      }
    }
    """


def render_public_form(values: dict[str, str] | None = None) -> str:
    values = values or {}
    workspace_key = html.escape(values.get("workspace_key", ""))
    user_id = html.escape(values.get("user_id", ""))
    username = html.escape(values.get("username", ""))
    return f"""
      <section>
        <h2>設定</h2>
        <form method="post">
          <div class="form-grid">
            <label class="full">合言葉
              <input name="workspace_key" value="{workspace_key}" placeholder="例: my-secret-12345" autocomplete="off" required>
              <span class="hint">同じ合言葉を使うと、前回保存したデータと比較できます。</span>
            </label>
            <label class="full">X API Bearer Token
              <input name="bearer_token" type="password" placeholder="AAAAAAAA..." autocomplete="off" required>
              <span class="hint">トークンは保存しません。実行するたびに入力してください。</span>
            </label>
            <label>Xユーザー名
              <input name="username" value="{username}" placeholder="例: example_user">
            </label>
            <label>X_USER_ID
              <input name="user_id" value="{user_id}" placeholder="分からなければ空欄">
            </label>
          </div>
          <div class="form-actions">
            <button class="primary" type="submit" formaction="/public-save">正式保存</button>
            <button type="submit" formaction="/public-refresh">最新確認</button>
          </div>
        </form>
      </section>
    """


def render_public_page(
    *,
    result: dict[str, Any] | None = None,
    latest: dict[str, Any] | None = None,
    values: dict[str, str] | None = None,
    error: str = "",
    status: str = "",
) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Follower Tracker</title>
  <style>{styles()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>X Follower Tracker</h1>
        <div class="subtitle">スマホだけでフォロワー変化を確認できます</div>
      </div>
    </header>
    {render_message("error", error)}
    {render_message("status", status)}
    {render_public_form(values)}
    {render_result(result, latest)}
  </main>
</body>
</html>
"""


def render_login_page(error: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Follower Tracker</title>
  <style>{styles()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>X Follower Tracker</h1>
        <div class="subtitle">パスワードを入力してください</div>
      </div>
    </header>
    {render_message("error", error)}
    <section>
      <h2>ログイン</h2>
      <form method="post" action="/login">
        <div class="form-grid">
          <label class="full">サイトパスワード
            <input name="site_password" type="password" autocomplete="current-password" required>
          </label>
        </div>
        <div class="form-actions">
          <button class="primary" type="submit">開く</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>
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
  <style>{styles()}</style>
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
    {render_result(result, load_latest_snapshot())}
  </main>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    app_key = ""
    public_mode = False
    last_result: dict[str, Any] | None = None
    last_status = ""
    last_error = ""

    def cookie_value(self, name: str) -> str:
        raw_cookie = self.headers.get("Cookie", "")
        for part in raw_cookie.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            if key == name:
                return value
        return ""

    def auth_token(self) -> str:
        return hmac.new(auth_secret().encode("utf-8"), b"site-auth", hashlib.sha256).hexdigest()

    def site_auth_required(self) -> bool:
        return self.public_mode and bool(site_password())

    def site_is_authenticated(self) -> bool:
        if not self.site_auth_required():
            return True
        return hmac.compare_digest(self.cookie_value("xft_auth"), self.auth_token())

    def require_site_auth(self) -> bool:
        if self.site_is_authenticated():
            return True
        self.send_html(render_login_page(), HTTPStatus.UNAUTHORIZED)
        return False

    def log_message(self, format: str, *args: Any) -> None:
        return

    def key_is_valid(self) -> bool:
        query = parse_qs(urlparse(self.path).query)
        return query.get("key", [""])[0] == self.app_key

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(raw, keep_blank_values=True)

    def redirect_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?{urlencode({'key': self.app_key})}")
        self.end_headers()

    def send_html(self, page: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_legacy_html(self, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_html(
            render_page(
                key=self.app_key,
                result=self.last_result,
                error=self.last_error,
                status=self.last_status,
            ),
            status,
        )

    def require_key(self) -> bool:
        if self.key_is_valid():
            return True
        self.last_error = "URLのアクセスキーが違います。起動ウィンドウに表示されたURLを開いてください。"
        self.last_status = ""
        self.send_legacy_html(HTTPStatus.FORBIDDEN)
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
        if parsed.path == "/login":
            self.send_html(render_login_page())
            return
        if parsed.path == "/" and self.public_mode:
            if not self.require_site_auth():
                return
            self.send_html(render_public_page())
            return
        if parsed.path == "/":
            if not self.require_key():
                return
            self.send_legacy_html()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if self.public_mode and parsed.path == "/login":
            form = self.read_form()
            attempted_password = form.get("site_password", [""])[0]
            if site_password() and hmac.compare_digest(attempted_password, site_password()):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"xft_auth={self.auth_token()}; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=2592000")
                self.end_headers()
                return
            self.send_html(render_login_page("パスワードが違います。"), HTTPStatus.UNAUTHORIZED)
            return

        if self.public_mode and parsed.path in {"/public-refresh", "/public-save"}:
            if not self.require_site_auth():
                return
            form = self.read_form()
            values = public_inputs(form)
            result = None
            latest = None
            error = ""
            status = ""

            try:
                workspace = workspace_dir(values["workspace_key"])
                latest = load_previous_snapshot_for(workspace)
                if parsed.path == "/public-refresh":
                    result = compare_public(values)
                    status = "最新確認が完了しました。"
                else:
                    saved = save_public(values)
                    latest = load_previous_snapshot_for(workspace)
                    status = f"正式保存しました。現在 {saved['current_count']} 人です。"
            except tracker.TrackerError as err:
                error = str(err)
            except Exception as err:
                error = f"Unexpected error: {err}"

            safe_values = {
                "workspace_key": values["workspace_key"],
                "user_id": values["user_id"],
                "username": values["username"],
            }
            self.send_html(
                render_public_page(
                    result=result,
                    latest=latest,
                    values=safe_values,
                    error=error,
                    status=status,
                )
            )
            return

        if not self.require_key():
            return

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
    parser.add_argument("--public-mode", action="store_true", default=public_mode_enabled())
    parser.add_argument("--private-mode", action="store_false", dest="public_mode")
    args = parser.parse_args()

    AppHandler.public_mode = args.public_mode
    AppHandler.app_key = args.key or secrets.token_urlsafe(12)
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)

    if args.public_mode:
        print(f"server: http://{args.host}:{args.port}/")
    else:
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
