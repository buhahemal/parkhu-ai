"""Parkhu Data Collector — CLI entrypoint.

Usage:
    python run.py
    PARKHU_MAX_SYMBOLS=5 python run.py
    PARKHU_RUN_DATE=2026-06-20 python run.py

Orchestration lives in ``pipeline.runner``; agent order in ``pipeline.registry``.
See ``docs/architecture.md`` for layers and coding standards.
"""

from __future__ import annotations

from pipeline.runner import main

if __name__ == "__main__":
    main()
