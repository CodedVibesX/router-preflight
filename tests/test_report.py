"""Report rendering, including the aborted-run edge case that bit us:
a run that dies at RP-001 has zero decisions and no stats, and the
renderers still have to produce output so exit code 2 reaches CI."""
import json
from pathlib import Path

from preflight import checks
from preflight.report import build_report, render_html, render_terminal

ROOT = Path(__file__).resolve().parents[1]


def test_aborted_run_renders_without_stats():
    findings, verdict = checks.run_all([], [], health_ok=False, canary=None)
    assert verdict == "FAIL"
    report = build_report({"base_url": "http://localhost:9", "corpus": "x"}, [],
                          findings, verdict, [])
    text = render_terminal(report)
    assert "FAIL" in text and "n/a" in text
    html = render_html(report)
    assert "v-FAIL" in html


def test_committed_report_renders_and_numbers_match():
    report = json.loads((ROOT / "output" / "report.json").read_text(encoding="utf-8"))
    text = render_terminal(report)
    assert f"verdict: {report['verdict']}" in text
    html = render_html(report)
    # the four tile numbers in the HTML must come from headline values
    assert f"{report['headline']['prompts_routed']}" in html
    assert f"{report['headline']['frontier_share_pct']}%" in html
