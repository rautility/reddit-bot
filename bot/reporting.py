"""Reporting — execution summary, structured logging, and webhook notifications."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

from bot.actions.base import ActionResult  # noqa: F401 — re-exported


@dataclass
class ExecutionSummary:
    """Tracks and summarizes all actions across an execution run."""

    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    results: list[ActionResult] = field(default_factory=list)

    def add(self, result: ActionResult) -> None:
        self.results.append(result)

    def finalize(self) -> None:
        self.end_time = datetime.utcnow()

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def duration_seconds(self) -> float:
        if self.end_time is None:
            return (datetime.utcnow() - self.start_time).total_seconds()
        return (self.end_time - self.start_time).total_seconds()

    def print_table(self) -> str:
        """Generate an ASCII summary table."""
        lines = []
        lines.append("")
        lines.append("=" * 80)
        lines.append("EXECUTION SUMMARY")
        lines.append("=" * 80)
        lines.append(f"Duration: {self.duration_seconds:.1f}s | Total: {self.total} | "
                      f"Success: {self.succeeded} | Failed: {self.failed}")
        lines.append("-" * 80)
        lines.append(f"{'Status':<8} {'Action':<15} {'Link':<35} {'Message'}")
        lines.append("-" * 80)

        for r in self.results:
            status = "OK" if r.success else "FAIL"
            link_short = r.link[:33] + ".." if len(r.link) > 35 else r.link
            msg_short = r.message[:25] + ".." if len(r.message) > 27 else r.message
            lines.append(f"{status:<8} {r.action:<15} {link_short:<35} {msg_short}")

        lines.append("=" * 80)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "results": [
                {"action": r.action, "link": r.link, "success": r.success, "message": r.message}
                for r in self.results
            ],
        }


def setup_structured_logger(name: str, level: int = logging.INFO, json_output: bool = False) -> logging.Logger:
    """Set up a logger with optional JSON output."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    handler = logging.StreamHandler()

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        formatter = logging.Formatter(
            "\033[93m[%(levelname)s]\033[0m %(asctime)s \033[95m%(message)s\033[0m"
        )
        handler.setFormatter(formatter)

    # Avoid duplicate handlers on repeated calls
    if not logger.handlers:
        logger.addHandler(handler)

    return logger


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry)


def send_webhook(
    url: str,
    summary: ExecutionSummary,
    on_completion: bool = True,
    on_failure: bool = True,
) -> bool:
    """Send an execution summary to a webhook URL.

    Supports Discord, Slack, and generic JSON webhooks.
    """
    if not url:
        return False

    # Only send on failure if configured
    if not on_completion and summary.failed == 0:
        return False
    if not on_failure and summary.failed > 0 and summary.succeeded == 0:
        return False

    payload = _build_payload(url, summary)

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code < 400
    except requests.RequestException:
        return False


def _build_payload(url: str, summary: ExecutionSummary) -> dict:
    """Build webhook payload — auto-detects Discord/Slack format."""
    status = "completed" if summary.failed == 0 else "completed with errors"
    text = (
        f"Reddit Bot run {status}\n"
        f"Duration: {summary.duration_seconds:.0f}s | "
        f"Total: {summary.total} | Success: {summary.succeeded} | Failed: {summary.failed}"
    )

    # Discord format
    if "discord" in url:
        return {
            "embeds": [{
                "title": "Reddit Bot Execution Report",
                "description": text,
                "color": 0x00FF00 if summary.failed == 0 else 0xFF0000,
                "fields": [
                    {"name": "Total Actions", "value": str(summary.total), "inline": True},
                    {"name": "Succeeded", "value": str(summary.succeeded), "inline": True},
                    {"name": "Failed", "value": str(summary.failed), "inline": True},
                ],
            }]
        }

    # Slack format
    if "slack" in url:
        return {
            "text": f"*Reddit Bot Execution Report*\n{text}",
        }

    # Generic JSON
    return summary.to_dict()
