"""Architecture / schema contracts (Track 2)."""
from __future__ import annotations

import pytest

from collector.derived.stock_analysis import COLUMNS as SA_COLUMNS
from collector.schema import assert_unique_columns, missing_from_schema
from pipeline.registry import COLLECTORS, DERIVED


def test_stock_analysis_columns_unique():
    assert_unique_columns(SA_COLUMNS, name="stock_analysis.COLUMNS")


def test_missing_from_schema_detects_dropped_keys():
    cols = ["a", "b"]
    assert missing_from_schema(["a", "b", "c"], cols) == ["c"]


def test_registry_labels_unique():
    labels = [s.label for s in COLLECTORS] + [s.label for s in DERIVED]
    assert len(labels) == len(set(labels))


def test_registry_kinds():
    assert all(s.kind == "collector" for s in COLLECTORS)
    assert all(s.kind == "derived" for s in DERIVED)


def test_assert_unique_columns_raises():
    with pytest.raises(ValueError, match="duplicate"):
        assert_unique_columns(["x", "y", "x"])
