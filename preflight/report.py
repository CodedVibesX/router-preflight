"""Report rendering: terminal text, report.json, report.html.

report.json is the single source of numbers. The HTML report and the
moneyshot image both read from it; nothing downstream recomputes or
hardcodes a stat. That keeps every published number traceable to one
recorded run.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from . import pricing
from .checks import Finding


def _finding_evidence(findings: list[dict], check: str) -> dict:
    for f in findings:
        if f["check"] == check:
            return f.get("evidence", {}) or {}
    return {}


def _fmt(value, spec: str = "", suffix: str = "") -> str:
    """None-safe number formatting. A run that dies at RP-001 has no
    latency or cost stats; the report must still render so the FAIL
    verdict (and exit code 2) reaches the caller."""
    if value is None:
        return "n/a"
    return f"{value:{spec}}{suffix}"


def build_report(meta: dict, decisions: list[dict], findings: list[Finding],
                 verdict: str, probe: list[dict]) -> dict:
    fdicts = [f.to_dict() for f in findings]
    tier = _finding_evidence(fdicts, "RP-004")
    lat = _finding_evidence(fdicts, "RP-003")
    cost = _finding_evidence(fdicts, "RP-007")
    savings = _finding_evidence(fdicts, "RP-006")
    reviews = [f for f in fdicts if f["check"] == "RP-005"]
    review_examples = [
        {"id": r["evidence"]["id"], "model": r["evidence"]["model"],
         "rules": [fl["rule"] for fl in r["evidence"]["flags"]]}
        for r in reviews[:2]
    ]
    return {
        "tool": "router-preflight",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": meta,
        "verdict": verdict,
        "headline": {
            "prompts_routed": len(decisions),
            "frontier_share_pct": tier.get("overall_pct", {}).get("frontier"),
            "cost_delta_pct_vs_requested": cost.get("delta_pct"),
            "routed_usd": cost.get("routed_usd"),
            "baseline_usd": cost.get("baseline_usd"),
            "median_decision_ms": lat.get("p50_ms"),
            "p95_decision_ms": lat.get("p95_ms"),
            "review_count": len(reviews),
            "review_examples": review_examples,
            "easy_on_frontier": savings.get("count"),
            "easy_savings_usd": savings.get("projected_savings_usd"),
            "determinism": _finding_evidence(fdicts, "RP-008"),
        },
        "findings": fdicts,
        "pricing": pricing.pricing_table(),
        "decisions": decisions,
        "probe": probe,
    }


def render_terminal(report: dict) -> str:
    h = report["headline"]
    lines = []
    bar = "=" * 72
    lines.append(bar)
    lines.append(f"  router-preflight  |  verdict: {report['verdict']}")
    lines.append(f"  {report['meta'].get('base_url', '?')}  corpus={report['meta'].get('corpus')}  "
                 f"n={h['prompts_routed']}")
    lines.append(bar)
    lines.append(f"  frontier share : {_fmt(h['frontier_share_pct'], '', '%')}")
    lines.append(f"  cost vs asked  : {_fmt(h['cost_delta_pct_vs_requested'], '+.1f', '%')} "
                 f"(${_fmt(h['routed_usd'], '.4f')} routed vs ${_fmt(h['baseline_usd'], '.4f')} baseline, ESTIMATE)")
    lines.append(f"  decision speed : p50 {_fmt(h['median_decision_ms'], '.0f', 'ms')} / "
                 f"p95 {_fmt(h['p95_decision_ms'], '.0f', 'ms')}")
    lines.append(f"  review flags   : {h['review_count']}  |  easy-on-frontier: {_fmt(h['easy_on_frontier'])}")
    lines.append("-" * 72)
    for f in report["findings"]:
        lines.append(f"  [{f['severity']:6s}] {f['check']}  {f['title']}")
        lines.append(f"           {f['detail']}")
    lines.append("-" * 72)
    mix = _finding_evidence(report["findings"], "RP-004").get("per_bucket_pct", {})
    if mix:
        lines.append("  tier mix per bucket (frontier/mid/budget %):")
        for bucket, m in mix.items():
            lines.append(f"    {bucket:22s} {m.get('frontier', 0):5.1f} / {m.get('mid', 0):5.1f} / "
                         f"{m.get('budget', 0):5.1f}")
    lines.append(bar)
    return "\n".join(lines)


_CSS = """
:root { --orange:#EC6341; --cream:#FDF1E9; --ink:#0E0E10; }
* { box-sizing:border-box; margin:0; }
body { background:var(--cream); color:var(--ink);
       font-family:Georgia,'Times New Roman',serif; padding:48px 24px; }
.wrap { max-width:980px; margin:0 auto; }
.label { font-family:'SF Mono',Menlo,Consolas,monospace; font-size:12px;
         letter-spacing:.12em; text-transform:uppercase; color:var(--orange); }
h1 { font-size:42px; font-weight:600; margin:6px 0 2px; }
.sub { font-size:17px; color:#52525b; margin-bottom:28px; }
.verdict { display:inline-block; font-family:Menlo,Consolas,monospace; font-size:15px;
           padding:6px 18px; border-radius:4px; color:var(--cream); margin-bottom:28px; }
.v-PASS { background:#1a7f4e; } .v-REVIEW { background:var(--orange); } .v-FAIL { background:#b3261e; }
.grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:34px; }
.tile { background:var(--ink); color:var(--cream); border-radius:6px; padding:18px 16px; }
.tile .n { font-size:30px; font-family:Menlo,Consolas,monospace; }
.tile .t { font-family:Menlo,Consolas,monospace; font-size:11px; letter-spacing:.08em;
           text-transform:uppercase; color:var(--orange); margin-top:6px; }
table { width:100%; border-collapse:collapse; margin:10px 0 30px; font-size:14px; }
th { font-family:Menlo,Consolas,monospace; font-size:11px; letter-spacing:.08em;
     text-transform:uppercase; text-align:left; color:#52525b;
     border-bottom:2px solid var(--ink); padding:8px 10px; }
td { padding:8px 10px; border-bottom:1px solid #e4d5c8; vertical-align:top; }
td.mono, .mono { font-family:Menlo,Consolas,monospace; font-size:13px; }
.sev { font-family:Menlo,Consolas,monospace; font-size:12px; padding:2px 8px; border-radius:3px; }
.s-PASS { background:#d7eadf; color:#1a7f4e; } .s-INFO { background:#e8e2dc; }
.s-WARN { background:#f6d9a8; } .s-REVIEW { background:#fbd1c4; color:#a33415; }
.s-FAIL { background:#b3261e; color:#fff; }
.foot { font-size:13px; color:#52525b; border-top:2px solid var(--ink); padding-top:14px; }
"""


def render_html(report: dict) -> str:
    h = report["headline"]
    meta = report["meta"]
    e = html.escape
    tiles = [
        (f"{h['prompts_routed']}", "prompts routed live"),
        (_fmt(h['frontier_share_pct'], '', '%'), "frontier share"),
        (_fmt(h['cost_delta_pct_vs_requested'], '+.1f', '%'), "est. cost vs requested"),
        (_fmt(h['median_decision_ms'], '.0f', 'ms'), "median decision"),
    ]
    tile_html = "".join(f'<div class="tile"><div class="n">{e(n)}</div><div class="t">{e(t)}</div></div>'
                        for n, t in tiles)
    rows = "".join(
        f'<tr><td class="mono">{e(f["check"])}</td>'
        f'<td><span class="sev s-{e(f["severity"])}">{e(f["severity"])}</span></td>'
        f'<td><strong>{e(f["title"])}</strong><br>{e(f["detail"])}</td></tr>'
        for f in report["findings"])
    mix = _finding_evidence(report["findings"], "RP-004").get("per_bucket_pct", {})
    mix_rows = "".join(
        f'<tr><td class="mono">{e(b)}</td><td class="mono">{m.get("frontier", 0)}%</td>'
        f'<td class="mono">{m.get("mid", 0)}%</td><td class="mono">{m.get("budget", 0)}%</td></tr>'
        for b, m in mix.items())

    def fmt_price(v) -> str:
        return "UNKNOWN" if v is None else f"${v}"

    price_rows = "".join(
        f'<tr><td class="mono">{e(p["model"])}</td><td class="mono">{e(p["tier"])}</td>'
        f'<td class="mono">{fmt_price(p["usd_per_mtok_in"])} / {fmt_price(p["usd_per_mtok_out"])}</td>'
        f'<td class="mono">{e(p["source"])} ({e(p["seen"])})</td></tr>'
        for p in report["pricing"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>router-preflight report</title><style>{_CSS}</style></head>
<body><div class="wrap">
<div class="label">router-preflight // live decision audit</div>
<h1>Is this router safe to point my coding agent at?</h1>
<div class="sub">Replayed {h['prompts_routed']} curated coding-agent prompts through
POST /v1/route on {e(str(meta.get('base_url')))} (workweave/router, cluster {e(str(meta.get('cluster_version')))}),
{e(str(meta.get('run_date')))}. Decisions only; no LLM was called.</div>
<span class="verdict v-{e(report['verdict'])}">verdict: {e(report['verdict'])}</span>
<div class="grid">{tile_html}</div>
<div class="label">findings</div>
<table><tr><th>check</th><th>severity</th><th>finding</th></tr>{rows}</table>
<div class="label">tier mix per bucket</div>
<table><tr><th>bucket</th><th>frontier</th><th>mid</th><th>budget</th></tr>{mix_rows}</table>
<div class="label">pricing basis (public list prices)</div>
<table><tr><th>model</th><th>tier</th><th>$/Mtok in / out</th><th>source (seen)</th></tr>{price_rows}</table>
<div class="foot">All dollar figures are estimates: list prices x len/4 token counts, output capped at
max_tokens. The corpus is curated synthetic data, not customer traffic. expected_tier labels are the
auditor's prior, not ground truth. Single-box latency. Generated {e(report['generated_utc'])}.</div>
</div></body></html>"""


def write_outputs(report: dict, out_dir) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
