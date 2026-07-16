"""Local executor service (LaunchAgent / PID-loop) ensure, stop, and status."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bot.control.common import REPO_ROOT, print_json

EXECUTOR_DIR = REPO_ROOT / ".agent-executor"
EXECUTOR_PID_PATH = EXECUTOR_DIR / "executor.pid"
EXECUTOR_LOG_PATH = EXECUTOR_DIR / "executor.log"
EXECUTOR_LABEL = "com.raul.reddit-bot.agentctl-scheduler"


def agentctl_script_path() -> Path:
    return REPO_ROOT / "scripts" / "agentctl.py"


def launch_agents_dir() -> Path:
    override = os.environ.get("REDDIT_BOT_LAUNCH_AGENTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "LaunchAgents"


def launch_agent_path() -> Path:
    return launch_agents_dir() / f"{EXECUTOR_LABEL}.plist"


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_file_status() -> dict[str, Any]:
    pid = None
    if EXECUTOR_PID_PATH.exists():
        raw_pid = EXECUTOR_PID_PATH.read_text(encoding="utf-8").strip()
        if raw_pid:
            try:
                pid = int(raw_pid)
            except ValueError:
                pid = None
    running = pid_is_running(pid) if pid is not None else False
    return {
        "running": running,
        "pid": pid,
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
    }


def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def agentctl_base_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(agentctl_script_path())]
    if args.config:
        command.extend(["--config", args.config])
    if args.db_path:
        command.extend(["--db-path", args.db_path])
    return command


def launch_agent_program_arguments(args: argparse.Namespace) -> list[str]:
    command = agentctl_base_command(args)
    command.extend(
        [
            "schedules",
            "run-due",
            "--run-worker",
        ]
    )
    return command


def launch_agent_plist(args: argparse.Namespace) -> dict[str, Any]:
    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": EXECUTOR_LABEL,
        "ProgramArguments": launch_agent_program_arguments(args),
        "WorkingDirectory": str(REPO_ROOT),
        "StartInterval": int(getattr(args, "start_interval", 60)),
        "RunAtLoad": True,
        "StandardOutPath": str(EXECUTOR_LOG_PATH),
        "StandardErrorPath": str(EXECUTOR_LOG_PATH),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }


def write_launch_agent(args: argparse.Namespace) -> Path:
    plist_path = launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as file_obj:
        plistlib.dump(launch_agent_plist(args), file_obj, sort_keys=False)
    return plist_path


def launchctl_print() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", "print", f"{launchctl_domain()}/{EXECUTOR_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )


def launchd_status() -> dict[str, Any]:
    if platform.system() != "Darwin":
        status = pid_file_status()
        return {
            "method": "pid-loop",
            "available": False,
            "running": status["running"],
            "pid": status["pid"],
            "label": EXECUTOR_LABEL,
            "plistPath": str(launch_agent_path()),
            "pidPath": status["pidPath"],
            "logPath": status["logPath"],
            "error": "launchd executor is only available on macOS.",
        }
    result = launchctl_print()
    return {
        "method": "launchd",
        "available": True,
        "running": result.returncode == 0,
        "label": EXECUTOR_LABEL,
        "plistPath": str(launch_agent_path()),
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
        "launchctlReturnCode": result.returncode,
    }


def executor_status() -> dict[str, Any]:
    return launchd_status()


def ensure_pid_loop(args: argparse.Namespace) -> dict[str, Any]:
    status = pid_file_status()
    if status["running"]:
        return {"ensured": True, "started": False, "method": "pid-loop", **status}

    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    log_file = EXECUTOR_LOG_PATH.open("ab")
    command = agentctl_base_command(args)
    command.extend(
        [
            "executor",
            "run",
            "--interval",
            str(getattr(args, "executor_interval", 15.0)),
            "--run-worker",
        ]
    )
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    EXECUTOR_PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "ensured": True,
        "started": True,
        "method": "pid-loop",
        "running": True,
        "pid": process.pid,
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
    }


def ensure_executor_service(args: argparse.Namespace) -> dict[str, Any]:
    if platform.system() != "Darwin":
        if getattr(args, "allow_pid_fallback", False):
            return ensure_pid_loop(args)
        return {
            "ensured": False,
            **executor_status(),
        }

    plist_path = write_launch_agent(args)
    domain = launchctl_domain()
    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode not in (0, 5):
        return {
            "ensured": False,
            **executor_status(),
            "error": (bootstrap.stderr or bootstrap.stdout).strip(),
        }
    kickstart = subprocess.run(
        ["launchctl", "kickstart", "-k", f"{domain}/{EXECUTOR_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    status = executor_status()
    return {
        "ensured": kickstart.returncode == 0 or status["running"],
        **status,
        "plistWritten": str(plist_path),
        "bootstrapReturnCode": bootstrap.returncode,
        "kickstartReturnCode": kickstart.returncode,
        "error": None
        if kickstart.returncode == 0 or status["running"]
        else (kickstart.stderr or kickstart.stdout).strip(),
    }


def command_executor_ensure(args: argparse.Namespace) -> int:
    print_json(ensure_executor_service(args))
    return 0


def command_executor_status(args: argparse.Namespace) -> int:
    print_json(executor_status())
    return 0


def command_executor_stop(args: argparse.Namespace) -> int:
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["launchctl", "bootout", launchctl_domain(), str(launch_agent_path())],
            capture_output=True,
            text=True,
            check=False,
        )
        if EXECUTOR_PID_PATH.exists():
            EXECUTOR_PID_PATH.unlink()
        print_json(
            {
                "stopped": result.returncode == 0,
                **executor_status(),
                "bootoutReturnCode": result.returncode,
                "error": None if result.returncode == 0 else (result.stderr or result.stdout).strip(),
            }
        )
        return 0

    status = pid_file_status()
    stopped = False
    if status["running"] and status["pid"] is not None:
        os.kill(status["pid"], signal.SIGTERM)
        stopped = True
    if EXECUTOR_PID_PATH.exists():
        EXECUTOR_PID_PATH.unlink()
    print_json({"stopped": stopped, **executor_status()})
    return 0


def command_executor_run(args: argparse.Namespace, *, run_due_schedules) -> int:
    """Run the executor loop; ``run_due_schedules`` injected to avoid circular imports."""
    worker_id = args.worker_id or f"executor:{socket.gethostname()}:{os.getpid()}"
    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    EXECUTOR_PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    iterations = 0
    try:
        while True:
            run_args = argparse.Namespace(
                config=args.config,
                db_path=args.db_path,
                worker_id=worker_id,
                now="",
                lease_seconds=args.lease_seconds,
                limit=args.limit,
                priority=args.priority,
                run_worker=args.run_worker,
                verbose=args.verbose,
            )
            payload = run_due_schedules(run_args)
            payload["executor"] = {
                "pid": os.getpid(),
                "iteration": iterations + 1,
                "interval": args.interval,
            }
            print(json.dumps(payload, sort_keys=True), flush=True)
            iterations += 1
            if args.max_iterations and iterations >= args.max_iterations:
                break
            time.sleep(args.interval)
    finally:
        status = executor_status()
        if status["pid"] == os.getpid() and EXECUTOR_PID_PATH.exists():
            EXECUTOR_PID_PATH.unlink()
    return 0
