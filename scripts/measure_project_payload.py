"""Measure read_github_project payload size on a few boards.

Run once against main and once against the branch, then paste both tables
into the PR for issue #141:

  python scripts/measure_project_payload.py --base-url http://localhost:8000 \
      --bearer-token "$TOKEN" nebari-dev:7 nebari-dev:4

The filtered case uses a real Status column of each board, taken from
counts.by_status of the default read: the column whose name contains
--status (default "in progress", matched case-insensitively and ignoring
emoji, e.g. 'In progress 🏗'), else the first column. GitHub's filter ignores
case but not emoji, so a hard-coded status:"In Progress" would silently match
nothing on such a board and the row would measure an empty reply.
"""

from __future__ import annotations

import argparse
import json
import unicodedata

import httpx


def _plain(name: str) -> str:
    """Lower-case a column name and drop emoji/symbols, so 'In progress 🏗'
    compares equal to 'in progress'."""
    kept = (ch for ch in name if not unicodedata.category(ch).startswith("S"))
    return " ".join("".join(kept).lower().split())


def pick_status(columns: list[str], wanted: str) -> str | None:
    """The board's real column name to filter on: the first whose plain form
    contains `wanted`, else the first column at all."""
    target = _plain(wanted)
    for name in columns:
        if target and target in _plain(name):
            return name
    return columns[0] if columns else None


def measure(base_url: str, bearer_token: str, boards: list[str], status: str) -> None:
    headers = {"Authorization": f"Bearer {bearer_token}"}
    print("| board | case | bytes | ~tokens | items | matched | total_count | authoritative |")
    print("|---|---|---:|---:|---:|---:|---:|---|")
    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=60) as client:
        for spec in boards:
            try:
                owner, number = spec.split(":")
            except ValueError:
                raise SystemExit(f"expected owner:project_number, got {spec!r}") from None
            columns: list[str] = []
            cases: list[tuple[str, dict]] = [("default", {}), ("max_items=500", {"max_items": 500})]
            while cases:
                label, extra = cases.pop(0)
                r = client.post(
                    f"/v1/connectors/github/projects/{number}/read",
                    json={"owner": owner, **extra},
                )
                if r.status_code != 200:
                    print(f"| {spec} | {label} | error {r.status_code} | | | | | |")
                    continue
                body = r.json()
                size = len(json.dumps(body, separators=(",", ":")).encode())
                counts = body.get("counts") or {}
                # matched_count exists only on the branch; main reports the total.
                matched = body.get("matched_count", body["total_count"])
                print(
                    f"| {spec} | {label} | {size:,} | {size // 4:,} | {len(body['items'])} "
                    f"| {matched} | {body['total_count']} | {counts.get('authoritative')} |"
                )
                if label == "default":
                    columns = [c["name"] for c in counts.get("by_status", [])]
                    column = pick_status(columns, status)
                    if column is None:
                        print(f"| {spec} | query status | no Status columns reported | | | | | |")
                    else:
                        query = f"status:{json.dumps(column, ensure_ascii=False)}"
                        cases.append((f"query {query}", {"query": query}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Collab Hub API base URL")
    parser.add_argument("--bearer-token", required=True)
    parser.add_argument(
        "--status",
        default="in progress",
        help="Status column to filter on (case- and emoji-insensitive substring of a real column name)",
    )
    parser.add_argument("boards", nargs="+", help="owner:project_number, e.g. nebari-dev:7")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    measure(args.base_url, args.bearer_token, args.boards, args.status)
