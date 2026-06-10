"""Render the 1200x675 summary card (X reply spec, 16:9) from report.json.

Every number on the card is read from the recorded report.json of a real
run; _require() raises if any expected stat is missing, so the image
cannot be generated from hardcoded or partial data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
INK = (14, 14, 16)        # #0E0E10
TILE = (26, 26, 30)
CREAM = (253, 241, 233)   # #FDF1E9
ORANGE = (236, 99, 65)    # #EC6341
GREEN = (38, 145, 91)
RED = (179, 38, 30)
GRAY = (148, 142, 136)

_FONT_DIR = os.environ.get("MONEYSHOT_FONT_DIR", "/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(Path(_FONT_DIR) / name), size)


def _require(report: dict, *path):
    node = report
    for key in path:
        if not isinstance(node, dict) or key not in node or node[key] is None:
            raise ValueError(f"report.json missing required stat: {'.'.join(map(str, path))}")
        node = node[key]
    return node


def footer_text(report: dict) -> str:
    """Attribution line built from report.json meta, never a literal.
    run_preflight.py records cluster_version (parsed from a decision
    reason string) and run_date (the run's date) into meta; _require
    raises if either is missing, so a stale or hand-edited footer
    cannot ship."""
    cluster = _require(report, "meta", "cluster_version")
    run_date = _require(report, "meta", "run_date")
    return f"live run vs workweave/router {cluster} cluster artifact, {run_date}"


def render(report_path: str | Path, out_path: str | Path) -> Path:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    verdict = _require(report, "verdict")
    n = _require(report, "headline", "prompts_routed")
    frontier = _require(report, "headline", "frontier_share_pct")
    cost_pct = _require(report, "headline", "cost_delta_pct_vs_requested")
    median_ms = _require(report, "headline", "median_decision_ms")
    review_count = _require(report, "headline", "review_count")
    examples = report["headline"].get("review_examples") or []
    easy_n = _require(report, "headline", "easy_on_frontier")

    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    mono_b = _font("DejaVuSansMono-Bold.ttf", 42)
    mono = _font("DejaVuSansMono.ttf", 19)
    mono_sm = _font("DejaVuSansMono.ttf", 15)
    sans_xl = _font("DejaVuSans-Bold.ttf", 52)
    sans = _font("DejaVuSans.ttf", 19)

    pad = 56
    d.text((pad, 44), "router-preflight", font=mono_b, fill=CREAM)
    d.text((pad, 100), "preflight gate for Weave Router adoption", font=mono, fill=ORANGE)

    badge_color = {"PASS": GREEN, "REVIEW": ORANGE, "FAIL": RED}[verdict]
    badge_text = f" {verdict} "
    bw = d.textlength(badge_text, font=mono_b) + 36
    d.rounded_rectangle((W - pad - bw, 44, W - pad, 104), radius=8, fill=badge_color)
    d.text((W - pad - bw + 18, 50), badge_text, font=mono_b, fill=CREAM)

    tiles = [
        (f"{n}", "prompts routed live"),
        (f"{frontier:.0f}%", "frontier share"),
        (f"{cost_pct:+.0f}%", "est cost vs requested"),
        (f"{median_ms:.0f}ms", "median decision"),
    ]
    tile_w, tile_h, gap, ty = 258, 158, 18, 158
    for i, (value, label) in enumerate(tiles):
        x = pad + i * (tile_w + gap)
        d.rounded_rectangle((x, ty, x + tile_w, ty + tile_h), radius=10, fill=TILE)
        d.rectangle((x, ty, x + tile_w, ty + 5), fill=ORANGE)
        d.text((x + 22, ty + 36), value, font=sans_xl, fill=CREAM)
        d.text((x + 22, ty + 112), label.upper(), font=mono_sm, fill=ORANGE)

    sy = 356
    d.rounded_rectangle((pad, sy, W - pad, sy + 168), radius=10, fill=TILE)
    d.rectangle((pad, sy, pad + 6, sy + 168), fill=ORANGE)
    d.text((pad + 28, sy + 18), f"REVIEW FLAGS: {review_count}", font=mono, fill=ORANGE)
    if examples:
        for j, ex in enumerate(examples[:2]):
            line = f"{ex['id']}  fired [{', '.join(ex['rules'][:3])}]  but landed on {ex['model']}"
            d.text((pad + 28, sy + 58 + j * 34), line[:88], font=sans, fill=CREAM)
    else:
        d.text((pad + 28, sy + 58),
               "0 risk-flagged prompts landed on budget-tier models.", font=sans, fill=CREAM)
        d.text((pad + 28, sy + 92),
               f"Flip side: {easy_n} easy prompts (short factoids) were routed to frontier models.",
               font=sans, fill=CREAM)
        d.text((pad + 28, sy + 126),
               f"The {_require(report, 'meta', 'cluster_version')} artifact ships quality-first. Budget for the knob.",
               font=sans, fill=GRAY)

    d.line((pad, 580, W - pad, 580), fill=(60, 58, 56), width=2)
    d.text((pad, 598), footer_text(report), font=mono_sm, fill=GRAY)
    d.text((pad, 624), "github.com/CodedVibesX/router-preflight", font=mono_sm, fill=ORANGE)

    out = Path(out_path)
    img.save(out, "PNG")
    return out


if __name__ == "__main__":
    import sys
    report = sys.argv[1] if len(sys.argv) > 1 else "output/report.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "output/moneyshot.png"
    path = render(report, out)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
