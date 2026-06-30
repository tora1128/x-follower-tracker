#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.x.com/2"
ROOT = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.getenv("XFT_STORAGE_DIR", ROOT))
DATA_DIR = STORAGE_DIR / "data"
REPORTS_DIR = STORAGE_DIR / "reports"
LATEST_SNAPSHOT = DATA_DIR / "followers_latest.json"


class TrackerError(Exception):
    pass


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request_json(path: str, params: dict[str, str], bearer_token: str) -> dict[str, Any]:
    query = urlencode(params)
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    request = Request(url, headers={"Authorization": f"Bearer {bearer_token}"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise TrackerError(f"X API error {error.code}: {body}") from error
    except URLError as error:
        raise TrackerError(f"Network error: {error.reason}") from error


def resolve_user_id(bearer_token: str) -> str:
    explicit_id = os.getenv("X_USER_ID", "").strip()
    if explicit_id:
        return explicit_id

    username = os.getenv("X_USERNAME", "").strip().lstrip("@")
    if not username:
        raise TrackerError("Set X_USER_ID or X_USERNAME in .env")

    payload = request_json(
        f"/users/by/username/{username}",
        {"user.fields": "id,username,name"},
        bearer_token,
    )
    data = payload.get("data")
    if not data or not data.get("id"):
        raise TrackerError(f"Could not resolve username: {username}")
    return data["id"]


def fetch_followers(bearer_token: str, user_id: str, limit: Optional[int]) -> list[dict[str, Any]]:
    followers: list[dict[str, Any]] = []
    pagination_token = ""

    while True:
        params = {
            "max_results": "1000",
            "user.fields": "id,username,name,verified,public_metrics,created_at",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        payload = request_json(f"/users/{user_id}/followers", params, bearer_token)
        followers.extend(payload.get("data", []))

        if limit is not None and len(followers) >= limit:
            return followers[:limit]

        meta = payload.get("meta", {})
        pagination_token = meta.get("next_token", "")
        if not pagination_token:
            return followers

        time.sleep(1)


def load_previous_snapshot() -> Optional[dict[str, Any]]:
    if not LATEST_SNAPSHOT.exists():
        return None
    return json.loads(LATEST_SNAPSHOT.read_text(encoding="utf-8"))


def parse_snapshot_dt(snapshot: dict[str, Any]) -> Optional[datetime]:
    fetched_at = str(snapshot.get("fetched_at", ""))
    if not fetched_at:
        return None
    return datetime.fromisoformat(fetched_at)


def load_history_snapshots() -> list[dict[str, Any]]:
    snapshots = []
    for path in sorted(DATA_DIR.glob("followers_*.json")):
        if path.name == LATEST_SNAPSHOT.name:
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["_snapshot_path"] = str(path)
        snapshots.append(snapshot)
    return snapshots


def load_snapshot_from_previous_midnight() -> Optional[dict[str, Any]]:
    snapshots = load_history_snapshots()
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


def follower_map(snapshot: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not snapshot:
        return {}
    return {item["id"]: item for item in snapshot.get("followers", []) if item.get("id")}


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    timestamp = snapshot["fetched_at"].replace(":", "").replace("+", "Z")
    history_path = DATA_DIR / f"followers_{timestamp}.json"
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)

    history_path.write_text(serialized + "\n", encoding="utf-8")
    LATEST_SNAPSHOT.write_text(serialized + "\n", encoding="utf-8")
    return history_path


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Track X followers and report changes.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and compare without saving.")
    parser.add_argument("--limit", type=int, help="Fetch only the first N followers for testing.")
    args = parser.parse_args()

    load_env(ROOT / ".env")

    bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not bearer_token:
        raise TrackerError("Set X_BEARER_TOKEN in .env")

    user_id = resolve_user_id(bearer_token)
    previous_snapshot = load_previous_snapshot()
    previous = follower_map(previous_snapshot)

    fetched_at = utc_now_iso()
    followers = fetch_followers(bearer_token, user_id, args.limit)
    current = {item["id"]: item for item in followers if item.get("id")}

    removed = [previous[item_id] for item_id in sorted(previous.keys() - current.keys())]
    snapshot = {
        "target_user_id": user_id,
        "fetched_at": fetched_at,
        "count": len(followers),
        "followers": followers,
    }

    print(f"target_user_id: {user_id}")
    print(f"fetched_at: {fetched_at}")
    print(f"current_followers: {len(current)}")

    if previous_snapshot is None:
        print("previous_snapshot: none")
        print("removed_followers: skipped on first run")
    else:
        print(f"previous_fetched_at: {previous_snapshot.get('fetched_at', '')}")
        print(f"removed_followers: {len(removed)}")

    if args.dry_run:
        print("dry_run: no files written")
        return 0

    snapshot_path = write_snapshot(snapshot)
    print(f"snapshot_saved: {snapshot_path}")

    if previous_snapshot is not None:
        report_stamp = fetched_at.replace(":", "").replace("+", "Z")
        removed_path = REPORTS_DIR / f"removed_{report_stamp}.csv"
        write_csv(removed_path, removed)
        print(f"removed_report: {removed_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrackerError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
