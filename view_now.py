#!/usr/bin/env python3
import html
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import tracker


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "current.html"


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def format_dt(value: str) -> str:
    if not value:
        return ""
    return parse_dt(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def account_url(username: str) -> str:
    return f"https://x.com/{username}" if username else ""


def render_account_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="5" class="empty">該当なし</td></tr>'

    rendered = []
    for row in rows:
        username = str(row.get("username", ""))
        name = str(row.get("name", ""))
        metrics = row.get("public_metrics", {}) or {}
        followers_count = metrics.get("followers_count", "")
        following_count = metrics.get("following_count", "")
        url = account_url(username)
        username_html = html.escape(f"@{username}") if username else ""
        if url:
            username_html = f'<a href="{html.escape(url)}">{username_html}</a>'
        rendered.append(
            "<tr>"
            f"<td>{username_html}</td>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(str(row.get('id', '')))}</td>"
            f"<td>{html.escape(str(followers_count))}</td>"
            f"<td>{html.escape(str(following_count))}</td>"
            "</tr>"
        )
    return "\n".join(rendered)


def render_html(
    *,
    fetched_at: str,
    previous_fetched_at: str,
    compare_label: str,
    current_count: int,
    previous_count: int,
    removed: list[dict[str, Any]],
) -> str:
    delta = current_count - previous_count
    delta_text = f"{delta:+d}"
    delta_class = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Follower Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #667085;
      --line: #d8dee4;
      --blue: #0969da;
      --green: #1a7f37;
      --red: #cf222e;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-end;
      margin-bottom: 20px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .time {{
      color: var(--muted);
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{
      padding: 16px;
    }}
    .label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .value {{
      font-size: 30px;
      font-weight: 700;
    }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}
    .neutral {{ color: var(--muted); }}
    section {{
      margin-top: 16px;
      overflow: hidden;
    }}
    h2 {{
      margin: 0;
      padding: 14px 16px;
      font-size: 18px;
      border-bottom: 1px solid var(--line);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
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
      font-weight: 600;
      background: #f9fafb;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 600;
    }}
    .empty {{
      color: var(--muted);
      text-align: center;
      padding: 22px;
    }}
    @media (max-width: 760px) {{
      header {{
        display: block;
      }}
      .grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .value {{
        font-size: 26px;
      }}
      th:nth-child(3), td:nth-child(3) {{
        display: none;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>X Follower Tracker</h1>
        <div class="time">現時点: {html.escape(format_dt(fetched_at))}</div>
        <div class="time">比較元: {html.escape(format_dt(previous_fetched_at))}（{html.escape(compare_label)}）</div>
      </div>
    </header>

    <div class="grid">
      <div class="metric">
        <div class="label">現在</div>
        <div class="value">{current_count}</div>
      </div>
      <div class="metric">
        <div class="label">前回比</div>
        <div class="value {delta_class}">{delta_text}</div>
      </div>
      <div class="metric">
        <div class="label">減った人</div>
        <div class="value negative">{len(removed)}</div>
      </div>
    </div>

    <section>
      <h2>減った人</h2>
      <table>
        <thead><tr><th>アカウント</th><th>名前</th><th>ID</th><th>フォロワー</th><th>フォロー</th></tr></thead>
        <tbody>
          {render_account_rows(removed)}
        </tbody>
      </table>
    </section>

  </main>
</body>
</html>
"""


def main() -> int:
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

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(
        render_html(
            fetched_at=fetched_at,
            previous_fetched_at=str(previous_snapshot.get("fetched_at", "")),
            compare_label="前日0時以降で最初の保存データ",
            current_count=len(current),
            previous_count=len(previous),
            removed=removed,
        ),
        encoding="utf-8",
    )

    print(f"current_followers: {len(current)}")
    print(f"removed_followers: {len(removed)}")
    print(f"report: {REPORT_PATH}")

    subprocess.run(["open", str(REPORT_PATH)], check=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except tracker.TrackerError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
