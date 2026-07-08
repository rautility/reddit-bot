"""Schedule parsing and formatting helpers shared by control-plane surfaces."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta

from bot.control.errors import CliError

WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
WEEKDAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def parse_rrule_text(rrule_text: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for raw_line in (rrule_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("DTSTART"):
            _, value = line.split(":", 1)
            parts["DTSTART"] = value
            continue
        if line.startswith("RRULE:"):
            line = line.removeprefix("RRULE:")
        for token in line.split(";"):
            if "=" in token:
                key, value = token.split("=", 1)
                parts[key.upper()] = value
    return parts


def parse_dtstart(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def next_run_after(
    rrule_text: str,
    after: datetime,
    previous_runs: int = 0,
) -> datetime | None:
    parts = parse_rrule_text(rrule_text)
    freq = parts.get("FREQ", "").upper()
    count = int(parts["COUNT"]) if parts.get("COUNT", "").isdigit() else None
    if count is not None and previous_runs >= count:
        return None

    dtstart = parse_dtstart(parts.get("DTSTART", "")) or after
    hour = int(parts.get("BYHOUR", dtstart.hour))
    minute = int(parts.get("BYMINUTE", dtstart.minute))
    second = int(parts.get("BYSECOND", dtstart.second))

    if freq == "DAILY":
        candidate = after.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return max(candidate, dtstart)

    if freq == "WEEKLY":
        bydays = parts.get("BYDAY")
        weekdays = [WEEKDAY_INDEX[day] for day in bydays.split(",") if day in WEEKDAY_INDEX] if bydays else [dtstart.weekday()]
        candidates = []
        base_date = after.date()
        for offset in range(0, 8):
            day = base_date + timedelta(days=offset)
            if day.weekday() not in weekdays:
                continue
            candidate = datetime.combine(day, datetime.min.time()).replace(
                hour=hour,
                minute=minute,
                second=second,
            )
            if candidate > after and candidate >= dtstart:
                candidates.append(candidate)
        return min(candidates) if candidates else None

    raise ValueError(f"Unsupported schedule frequency: {freq or '<missing>'}")


def slugify(value: str, *, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return (slug or "reddit-task")[:max_length].strip("-")


def parse_time(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise CliError("Time must use HH:MM format, for example 09:30.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise CliError("Time must be a valid 24-hour HH:MM value.")
    return hour, minute


def parse_at(value: str) -> datetime:
    normalized = value.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CliError("Use an ISO datetime for --at, for example 2026-07-06T09:00:00.") from exc


def normalize_weekdays(value: str) -> str:
    days = [day.strip().upper() for day in value.split(",") if day.strip()]
    invalid = [day for day in days if day not in WEEKDAYS]
    if invalid:
        raise CliError(f"Invalid weekday(s): {', '.join(invalid)}. Use MO,TU,WE,TH,FR,SA,SU.")
    if not days:
        raise CliError("--weekly requires at least one weekday.")
    return ",".join(days)


def schedule_rule(args: argparse.Namespace) -> tuple[str, str]:
    supplied = [
        bool(args.rrule),
        bool(args.at),
        bool(args.daily_at),
        bool(args.weekly),
    ]
    if sum(supplied) != 1:
        raise CliError("Choose exactly one schedule option: --rrule, --at, --daily-at, or --weekly.")

    if args.rrule:
        return args.rrule, args.next_run_at or ""

    if args.at:
        at = parse_at(args.at)
        dtstart = at.strftime("%Y%m%dT%H%M%S")
        return f"DTSTART:{dtstart}\nRRULE:FREQ=DAILY;COUNT=1", at.isoformat()

    if args.daily_at:
        hour, minute = parse_time(args.daily_at)
        return f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}", args.next_run_at or ""

    hour, minute = parse_time(args.time)
    weekdays = normalize_weekdays(args.weekly)
    return f"FREQ=WEEKLY;BYDAY={weekdays};BYHOUR={hour};BYMINUTE={minute}", args.next_run_at or ""
