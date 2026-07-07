"""Keep the Codex copy of the reddit-bot skill in sync with the canonical copy.

The skill is authored once under ``.claude/skills/reddit-bot`` and mirrored to
``.codex/skills/reddit-bot`` so both agent runtimes load identical content. The
test suite calls :func:`diff` so any drift fails CI; ``make sync-skill`` (or
``python scripts/sync_skills.py``) rewrites the mirror from the canonical copy.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = REPO_ROOT / ".claude" / "skills" / "reddit-bot"
MIRROR = REPO_ROOT / ".codex" / "skills" / "reddit-bot"


def _tree(root: Path) -> dict[str, bytes]:
    """Map every file under ``root`` to its bytes, keyed by relative path."""
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def diff(canonical: Path = CANONICAL, mirror: Path = MIRROR) -> list[str]:
    """Return human-readable descriptions of every file that differs."""
    src, dst = _tree(canonical), _tree(mirror)
    problems: list[str] = []
    for rel in sorted(set(src) | set(dst)):
        if rel not in dst:
            problems.append(f"missing in mirror: {rel}")
        elif rel not in src:
            problems.append(f"stale in mirror: {rel}")
        elif src[rel] != dst[rel]:
            problems.append(f"differs: {rel}")
    return problems


def sync(canonical: Path = CANONICAL, mirror: Path = MIRROR) -> list[str]:
    """Rewrite the mirror as an exact copy of the canonical skill."""
    if not canonical.exists():
        raise FileNotFoundError(f"Canonical skill not found: {canonical}")
    if mirror.exists():
        shutil.rmtree(mirror)
    shutil.copytree(canonical, mirror)
    return sorted(str(p.relative_to(mirror)) for p in mirror.rglob("*") if p.is_file())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-skills",
        description="Mirror the reddit-bot skill from .claude/skills to .codex/skills.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit non-zero instead of rewriting the mirror.",
    )
    args = parser.parse_args(argv)

    if args.check:
        problems = diff()
        if problems:
            print("reddit-bot skill copies differ (run `make sync-skill`):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("reddit-bot skill copies are in sync.")
        return 0

    files = sync()
    print(f"Synced {len(files)} file(s) to {MIRROR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
