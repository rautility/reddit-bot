"""Queue submit, list, retry, recover, and worker orchestration helpers."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import socket
import time
from dataclasses import asdict
from typing import Any

from bot.control.common import load_config, open_db, print_json
from bot.control.profiles import (
    DEFAULT_DEBUG_ADDRESS,
    resolve_profile_identity,
)
from bot.control.schedules import next_run_after, parse_dt
from bot.database import BotDatabase
from bot.reporting import setup_structured_logger
from bot.utils.clock import utc_now
from bot.utils.credentials import Account
from bot.utils.input_parser import ActionEntry, parse_links_file
from bot.utils.validators import is_post_url, is_share_url, validate_reddit_url

CANONICAL_POST_ACTIONS = {"upvote", "downvote", "comment", "save", "hide", "award"}


def action_entry_from_payload(payload_json: str) -> ActionEntry:
    payload = json.loads(payload_json)
    allowed = {
        "link",
        "action",
        "comment",
        "title",
        "subreddit",
        "body",
        "flair",
        "recipient",
        "message",
    }
    return ActionEntry(**{key: payload.get(key) for key in allowed if key in payload})


def validate_canonical_post_actions(entries: list[ActionEntry]) -> list[dict[str, Any]]:
    errors = []
    for index, entry in enumerate(entries, start=1):
        action = (entry.action or "").strip().lower()
        if action not in CANONICAL_POST_ACTIONS:
            continue
        link = (entry.link or "").strip()
        if not validate_reddit_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": "Post action requires a valid reddit.com URL.",
                }
            )
            continue
        if is_share_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": (
                        "Reddit share links must be resolved before scheduling. "
                        "Use the canonical /r/<subreddit>/comments/<post_id>/... URL."
                    ),
                }
            )
            continue
        if not is_post_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": (
                        "Post action requires a canonical Reddit post URL matching "
                        "/r/<subreddit>/comments/<post_id>/..."
                    ),
                }
            )
    return errors


def parse_agent_links_file(path: str) -> tuple[list[ActionEntry], list[dict[str, Any]]]:
    entries = parse_links_file(path)
    return entries, validate_canonical_post_actions(entries)


def summary_payload(summary: Any) -> dict[str, Any]:
    return {
        "total": summary.total,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
        "results": [asdict(result) for result in summary.results],
    }


def run_queue_worker(args: argparse.Namespace) -> dict[str, Any]:
    from main import run_account

    config = load_config(args)
    worker_id = args.worker_id or f"{socket.gethostname()}:{os.getpid()}"
    logger = setup_structured_logger(
        "reddit-bot.agentctl",
        level=logging.INFO,
        log_dir=config.log_dir,
        log_file=config.log_file,
        console=args.verbose,
        file_level=logging.INFO,
    )
    processed = 0

    while args.max_jobs == 0 or processed < args.max_jobs:
        db = BotDatabase(config.db_path)
        job: dict[str, Any] | None = None
        lease_acquired = False
        lease_resource = config.chrome_debugging_address or config.chrome_user_data_dir or DEFAULT_DEBUG_ADDRESS
        try:
            job = db.lease_next_job(worker_id, lease_seconds=args.lease_seconds)
            if job is None:
                if args.once:
                    return {"workerId": worker_id, "processed": processed, "idle": True}
                time.sleep(args.idle_sleep)
                continue

            job_payload = json.loads(job["payload_json"])
            agent_profile = job_payload.get("_agent_profile") or {}
            lease_resource = agent_profile.get("debugAddress") or agent_profile.get("profilePath") or lease_resource
            lease_acquired, lease_message = db.acquire_lease(
                "chrome_profile",
                lease_resource,
                worker_id,
                ttl_seconds=args.lease_seconds,
                metadata={"jobId": job["id"]},
            )
            if not lease_acquired:
                db.release_queue_job(job["id"], lease_message)
                continue

            entry = action_entry_from_payload(job["payload_json"])
            run_config = copy.deepcopy(config)
            run_config.screenshot_on_failure = True
            if agent_profile.get("debugAddress"):
                run_config.use_existing_chrome = True
                run_config.chrome_debugging_address = agent_profile["debugAddress"]
                run_config.chrome_extension_healer_enabled = True
                run_config.parallel_accounts = 1
            elif agent_profile.get("profilePath"):
                run_config.use_existing_chrome = True
                run_config.chrome_user_data_dir = agent_profile["profilePath"]
                run_config.parallel_accounts = 1

            summary = run_account(
                Account(username=job["account"], password=""),
                [entry],
                run_config,
                logger,
            )
            result_payload = summary_payload(summary)
            success = summary.failed == 0
            db.complete_queue_job(
                job["id"],
                success=success,
                result=result_payload,
                error=None if success else "One or more action results failed.",
            )
            processed += 1
        except Exception as exc:
            if job is not None:
                db.release_queue_job(job["id"], str(exc))
            logger.exception("Agent queue worker failed while processing a job")
            if args.once:
                raise
        finally:
            if lease_acquired:
                db.release_lease("chrome_profile", lease_resource, worker_id)
            db.close()

    return {"workerId": worker_id, "processed": processed, "idle": False}


def command_queue_submit(args: argparse.Namespace) -> int:
    entries, link_errors = parse_agent_links_file(args.links)
    if link_errors:
        print_json(
            {
                "submitted": 0,
                "ok": False,
                "error": "Links file contains unsupported Reddit URL formats.",
                "linkErrors": link_errors,
            }
        )
        return 2

    db = open_db(args)
    try:
        identity = resolve_profile_identity(
            db,
            account_label=args.account_label,
            profile_name=args.profile_name,
            reddit_user=args.reddit_user,
        )
        jobs = []
        for entry in entries:
            payload = asdict(entry)
            payload["_agent_profile"] = {
                "profileName": identity["profileName"],
                "profilePath": identity["profilePath"],
                "debugAddress": identity["debugAddress"],
                "redditUsername": identity["redditUsername"],
            }
            jobs.append(
                db.enqueue_action(
                    identity["accountLabel"],
                    entry.action,
                    payload,
                    link=entry.link,
                    priority=args.priority,
                    scheduled_for=args.scheduled_for,
                    max_attempts=args.max_attempts,
                )
            )
        payload = {
            "submitted": len(jobs),
            "resolvedIdentity": identity,
            "jobs": jobs,
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_queue_list(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        payload = {
            "queueCounts": db.get_queue_counts(),
            "jobs": db.list_queue_jobs(
                status=args.status,
                account=getattr(args, "account", "") or None,
                limit=args.limit,
            ),
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_queue_recover_stale(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        recovered = db.recover_stale_queue_jobs(now_iso=args.now or None)
        payload = {
            "recovered": len(recovered),
            "jobs": recovered,
            "queueCounts": db.get_queue_counts(),
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_queue_retry(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        if args.id is not None:
            retried = [db.retry_queue_job(args.id)]
        else:
            retried = db.retry_failed_jobs(account=args.account or None)
        payload = {
            "retried": retried,
            "count": sum(1 for item in retried if item.get("retried")),
            "queueCounts": db.get_queue_counts(),
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_queue_worker(args: argparse.Namespace) -> int:
    print_json(run_queue_worker(args))
    return 0


def run_due_schedules(args: argparse.Namespace) -> dict[str, Any]:
    """Lease due schedules, enqueue their links, optionally run the queue worker."""
    worker_id = args.worker_id or f"{socket.gethostname()}:{os.getpid()}"
    now = parse_dt(args.now) if args.now else utc_now()
    db = open_db(args)
    processed = []
    recovered_stale = []
    try:
        recovered_stale = db.recover_stale_queue_jobs(now_iso=now.isoformat())
        schedules = db.lease_due_schedules(
            worker_id,
            now_iso=now.isoformat(),
            lease_seconds=args.lease_seconds,
            limit=args.limit,
            schedule_id=getattr(args, "id", "") or None,
        )
        for schedule in schedules:
            metadata = json.loads(schedule["metadata_json"] or "{}")
            links_path = metadata.get("linksPath") or metadata.get("actionFile")
            submitted_jobs = []
            try:
                if not links_path:
                    raise ValueError("Schedule metadata must include linksPath.")
                if not schedule["account"]:
                    raise ValueError("Schedule must resolve to an account before execution.")
                entries, link_errors = parse_agent_links_file(links_path)
                if link_errors:
                    raise ValueError(
                        "Links file contains unsupported Reddit URL formats: "
                        + json.dumps(link_errors, sort_keys=True)
                    )
                for entry in entries:
                    payload = asdict(entry)
                    payload["_agent_profile"] = {
                        "profileName": schedule["profile"],
                        "profilePath": metadata.get("profilePath", ""),
                        "debugAddress": metadata.get("debugAddress", ""),
                        "redditUsername": metadata.get("redditUsername", ""),
                    }
                    submitted_jobs.append(
                        db.enqueue_action(
                            schedule["account"],
                            entry.action,
                            payload,
                            link=entry.link,
                            priority=args.priority,
                            scheduled_for=now.isoformat(),
                        )
                    )
                previous_runs = 1 if schedule.get("last_run_at") else 0
                next_run = next_run_after(
                    schedule["rrule"] or "",
                    now,
                    previous_runs=previous_runs + 1,
                )
                db.complete_schedule_run(
                    schedule["id"],
                    next_run_at=next_run.isoformat() if next_run else None,
                    last_run_at=now.isoformat(),
                    deactivate=next_run is None,
                )
                processed.append(
                    {
                        "id": schedule["id"],
                        "submitted": len(submitted_jobs),
                        "jobIds": [job["id"] for job in submitted_jobs],
                        "jobStatuses": [{"id": job["id"], "status": job["status"]} for job in submitted_jobs],
                        "queuedJobIds": [job["id"] for job in submitted_jobs if job.get("status") == "queued"],
                        "nextRunAt": next_run.isoformat() if next_run else None,
                    }
                )
            except Exception as exc:
                error = str(exc)
                db.complete_schedule_run(
                    schedule["id"],
                    next_run_at=schedule["next_run_at"],
                    last_run_at=None,
                    error=error,
                )
                processed.append({"id": schedule["id"], "submitted": 0, "error": error})
    finally:
        db.close()

    worker_payload = None
    runnable_job_ids = [job_id for item in processed for job_id in item.get("queuedJobIds", [])]
    total_submitted = sum(item.get("submitted", 0) for item in processed)
    if args.run_worker and runnable_job_ids:
        worker_args = argparse.Namespace(
            config=args.config,
            db_path=args.db_path,
            worker_id=worker_id,
            lease_seconds=args.lease_seconds,
            max_jobs=len(runnable_job_ids),
            once=True,
            idle_sleep=0,
            verbose=args.verbose,
        )
        worker_payload = run_queue_worker(worker_args)
        worker_payload["requestedMaxJobs"] = len(runnable_job_ids)

    diagnostics = []
    if total_submitted and not runnable_job_ids:
        diagnostics.append(
            {
                "code": "no_runnable_jobs",
                "message": (
                    "Due schedules resolved only to active non-queued jobs. "
                    "They may already be running because of deduplication."
                ),
            }
        )

    return {
        "workerId": worker_id,
        "dueSchedules": len(processed),
        "processed": processed,
        "recoveredStaleJobs": recovered_stale,
        "runnableJobIds": runnable_job_ids,
        "worker": worker_payload,
        "diagnostics": diagnostics,
    }


def command_schedules_run_due(args: argparse.Namespace) -> int:
    print_json(run_due_schedules(args))
    return 0
