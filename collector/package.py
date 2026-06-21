"""Package daily output into shareable zip archives.

Creates two zips under output/ after each run:
  - output/<YYYY-MM-DD>.zip  — dated snapshot
  - output/latest.zip         — same contents, stable name for hand-off
Each archive contains the output/<date>/ folder and all files inside it.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from collector.utils import get_logger
from config import settings

log = get_logger("package")


def write_output_zips(date: str | None = None) -> dict[str, Path]:
    """Zip output/<date>/ into dated and latest archives. Returns their paths."""
    date = date or settings.run_date()
    out_dir = settings.daily_output_dir(date)
    if not out_dir.is_dir() or not any(out_dir.iterdir()):
        log.warning("no output to zip for %s", date)
        return {}

    root = settings.OUTPUT_DIR
    dated = Path(shutil.make_archive(str(root / date), "zip", root_dir=str(root), base_dir=date))
    latest = Path(shutil.make_archive(str(root / "latest"), "zip", root_dir=str(root), base_dir=date))

    log.info("wrote %s (%s bytes) and %s", dated.name, dated.stat().st_size, latest.name)
    return {"dated": dated, "latest": latest}
