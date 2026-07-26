#!/usr/bin/env python3
"""Run lint, dead-code, and duplication scanners.

Usage:
    python -m scripts.quality           # full suite (exit non-zero on findings)
    python -m scripts.quality --fast    # ruff + vulture only (no jscpd)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, optional: bool = False) -> int:
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=ROOT, check=False)
        return proc.returncode
    except FileNotFoundError:
        if optional:
            print(f"(skip) not installed: {cmd[0]}", flush=True)
            return 0
        print(f"ERROR: command not found: {cmd[0]}", file=sys.stderr, flush=True)
        return 127


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip jscpd duplication scan (no Node required)",
    )
    args = parser.parse_args()
    failed = 0

    # Lint / unused imports / bugbear
    code = _run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "collector",
            "config",
            "pipeline",
            "scripts",
            "tests",
            "run.py",
        ]
    )
    failed |= code

    # Format drift (report only; does not rewrite)
    code = _run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "collector",
            "config",
            "pipeline",
            "scripts",
            "tests",
            "run.py",
        ]
    )
    if code != 0:
        print("hint: run `ruff format collector config pipeline scripts tests run.py` to fix")
    failed |= code

    # Dead / unused code
    code = _run(
        [
            sys.executable,
            "-m",
            "vulture",
            "collector",
            "config",
            "pipeline",
            "scripts",
            "run.py",
            "--min-confidence",
            "80",
            "--exclude",
            "collector/_retired,.venv",
        ]
    )
    failed |= code

    # Duplication (Node / npx)
    if not args.fast:
        npx = shutil.which("npx")
        if npx:
            report_dir = ROOT / "reports" / "jscpd"
            report_dir.mkdir(parents=True, exist_ok=True)
            code = _run(
                [
                    npx,
                    "--yes",
                    "jscpd@4.0.5",
                    "--config",
                    str(ROOT / "jscpd.json"),
                    "--output",
                    str(report_dir),
                    str(ROOT),
                ],
                optional=False,
            )
            # jscpd exits 1 when threshold exceeded — treat as failure
            failed |= code
        else:
            print("\n>>> jscpd skipped (npx not on PATH). Install Node or use --fast.")

    print("\n=== quality summary ===")
    print("PASS" if failed == 0 else "FAIL — see findings above")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
