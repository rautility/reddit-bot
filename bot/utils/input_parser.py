"""Input file parsing — supports pipe-delimited, CSV, and JSON formats."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionEntry:
    link: str
    action: str
    comment: Optional[str] = None

    # Extended fields for new action types
    title: Optional[str] = None
    subreddit: Optional[str] = None
    body: Optional[str] = None
    flair: Optional[str] = None
    recipient: Optional[str] = None
    message: Optional[str] = None


VALID_ACTIONS = {
    "upvote", "downvote", "comment", "join", "leave",
    "save", "hide", "award",
    "post_text", "post_link", "post_image", "crosspost",
    "dm",
    "follow", "unfollow",
    "update_bio",
    "human_search",
    "search_upvote",
}


def parse_links_file(path: str) -> list[ActionEntry]:
    """Parse a links/actions file.

    Supports:
      - Pipe-delimited: url|action|comment
      - CSV with headers: link,action,comment,...
      - JSON: [{"link": "...", "action": "...", ...}]
    """
    with open(path, "r") as f:
        content = f.read().strip()

    if not content:
        return []

    # JSON format
    if content.startswith("["):
        data = json.loads(content)
        return [ActionEntry(**entry) for entry in data]

    lines = [line.strip() for line in content.splitlines() if line.strip()]

    # CSV format
    if "," in lines[0] and "|" not in lines[0]:
        entries = []
        reader = csv.DictReader(lines)
        for row in reader:
            entries.append(ActionEntry(
                link=row.get("link", ""),
                action=row.get("action", ""),
                comment=row.get("comment"),
                title=row.get("title"),
                subreddit=row.get("subreddit"),
                body=row.get("body"),
                flair=row.get("flair"),
                recipient=row.get("recipient"),
                message=row.get("message"),
            ))
        return entries

    # Pipe-delimited format (default)
    entries = []
    for line in lines:
        parts = line.split("|")
        entry = ActionEntry(link=parts[0], action=parts[1] if len(parts) > 1 else "")
        if len(parts) > 2:
            entry.comment = parts[2]
        if len(parts) > 3:
            entry.title = parts[3]
        if len(parts) > 4:
            entry.body = parts[4]
        entries.append(entry)

    return entries
