"""Schema helpers — catch COLUMNS / DataFrame drift early."""
from __future__ import annotations

from typing import Iterable, Sequence


def assert_unique_columns(columns: Sequence[str], *, name: str = "COLUMNS") -> None:
    """Raise ValueError if `columns` contains duplicates."""
    seen: set[str] = set()
    dupes: list[str] = []
    for col in columns:
        if col in seen:
            dupes.append(col)
        seen.add(col)
    if dupes:
        raise ValueError(f"{name} has duplicate entries: {sorted(set(dupes))}")


def missing_from_schema(row_keys: Iterable[str], columns: Sequence[str]) -> list[str]:
    """Keys present in a row dict but absent from the schema (would be dropped)."""
    colset = set(columns)
    return sorted(k for k in row_keys if k not in colset)
