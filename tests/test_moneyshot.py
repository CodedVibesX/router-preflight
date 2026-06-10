"""The card footer must be built from report.json meta, never a literal."""
import json
from pathlib import Path

import pytest

from preflight.moneyshot import footer_text

ROOT = Path(__file__).resolve().parents[1]


def test_footer_matches_committed_report_meta():
    report = json.loads((ROOT / "output" / "report.json").read_text(encoding="utf-8"))
    footer = footer_text(report)
    assert report["meta"]["cluster_version"] in footer
    assert report["meta"]["run_date"] in footer
    # A footer that ignores meta would still pass the check above by
    # coincidence, so move the meta and require the footer to follow.
    moved = footer_text({"meta": {"cluster_version": "v9.99", "run_date": "2031-01-01"}})
    assert "v9.99" in moved and "2031-01-01" in moved


def test_footer_refuses_report_without_meta_fields():
    with pytest.raises(ValueError, match="cluster_version"):
        footer_text({"meta": {"run_date": "2026-06-10"}})
