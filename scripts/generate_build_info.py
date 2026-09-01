"""Generate immutable build metadata for inclusion in a package artifact."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "novariusirc" / "_build_info.json"


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        # Minimal build images intentionally do not need Git.  Callers can
        # still pass the revision explicitly with --commit.
        return None
    commit = result.stdout.strip().lower()
    return commit if result.returncode == 0 else None


def utc_build_time() -> str:
    source_date_epoch = os.getenv("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        timestamp = datetime.fromtimestamp(int(source_date_epoch), tz=UTC)
    else:
        timestamp = datetime.now(tz=UTC)
    return timestamp.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="Git commit to embed; defaults to HEAD")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    commit = (args.commit or git_commit() or "").strip().lower()
    payload = {
        "schema": 1,
        "commit": commit or None,
        "built_at": utc_build_time(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
