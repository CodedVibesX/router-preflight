"""The preflight checks (RP-001..RP-008) and the gate verdict.

Framing matters here: this gates ADOPTION READINESS and surfaces what a
human should look at before pointing coding-agent traffic at the router.
It does not grade the router's honor and it never sees model outputs.
FAIL is reserved for "the gate itself cannot trust the run" (unreachable,
bad auth, broken contract). Routing decisions we disagree with are REVIEW
or INFO, because the corpus prior might be wrong and the knobs might be
deliberate.

All dollar figures are ESTIMATES: list prices applied to len/4 token
estimates with a max_tokens-capped output guess. They are for comparing
configurations, not for billing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from . import pricing

PASS, INFO, WARN, REVIEW, FAIL = "PASS", "INFO", "WARN", "REVIEW", "FAIL"

# Output guess when the request does not cap max_tokens. Coding-agent
# turns are input-heavy; 1024 output tokens is a round, disclosed guess.
DEFAULT_OUT_TOKENS = 1024
P95_LATENCY_WARN_MS = 250.0
# Anchor for "what would the easy prompt have cost on a budget model":
# the router's own hard-pin default model, not a model we picked.
SAVINGS_ANCHOR_MODEL = "claude-haiku-4-5"


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    title: str
    detail: str
    evidence: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"check": self.check, "severity": self.severity,
             "title": self.title, "detail": self.detail}
        if self.evidence is not None:
            d["evidence"] = self.evidence
        return d


def rp001_reachability(health_ok: bool, canary: Optional[dict], canary_error: str = "") -> Finding:
    if not health_ok:
        return Finding("RP-001", FAIL, "router unreachable",
                       "GET /health did not return 200; nothing else can be trusted.")
    if canary is None:
        return Finding("RP-001", FAIL, "auth rejected or route failed",
                       f"authenticated canary POST /v1/route failed: {canary_error or 'no decision'}")
    return Finding("RP-001", PASS, "reachable and authenticated",
                   "GET /health 200 and an authenticated /v1/route canary returned a decision.",
                   {"canary_model": canary.get("chosen_model")})


def rp002_contract(decisions: list[dict]) -> list[Finding]:
    findings = []
    for d in decisions:
        model, provider = d.get("chosen_model"), d.get("provider")
        if not isinstance(model, str) or not model or not isinstance(provider, str) or not provider:
            findings.append(Finding("RP-002", FAIL, "malformed decision",
                                    f"{d.get('id')}: decision missing model/provider",
                                    {"id": d.get("id"), "decision": {"model": model, "provider": provider}}))
            continue
        if model not in pricing.REGISTRY:
            findings.append(Finding("RP-002", FAIL, "model outside v0.65 registry",
                                    f"{d.get('id')}: router chose {model!r}, not one of the 15 registry models",
                                    {"id": d.get("id"), "model": model}))
    if not findings:
        findings.append(Finding("RP-002", PASS, "contract conformant",
                                f"all {len(decisions)} decisions had model+provider and every chosen model is in the v0.65 registry."))
    return findings


def _percentile(sorted_vals: list[float], pct: float) -> float:
    idx = max(0, math.ceil(pct * len(sorted_vals)) - 1)
    return sorted_vals[idx]


def rp003_latency(decisions: list[dict]) -> Finding:
    lats = sorted(d["latency_ms"] for d in decisions)
    p50, p95 = _percentile(lats, 0.50), _percentile(lats, 0.95)
    sev = WARN if p95 > P95_LATENCY_WARN_MS else INFO
    note = ("decision latency adds to every agent turn; p95 above 250ms is worth noticing"
            if sev == WARN else "decision overhead per agent turn, measured client-side on one box")
    return Finding("RP-003", sev, f"decision latency p50={p50:.0f}ms p95={p95:.0f}ms", note,
                   {"p50_ms": round(p50, 2), "p95_ms": round(p95, 2),
                    "min_ms": round(lats[0], 2), "max_ms": round(lats[-1], 2), "n": len(lats)})


def rp004_tier_mix(decisions: list[dict]) -> Finding:
    def mix(rows: list[dict]) -> dict:
        n = len(rows)
        counts = {t: 0 for t in (pricing.FRONTIER, pricing.MID, pricing.BUDGET)}
        for r in rows:
            tier = r.get("tier")
            if tier in counts:
                counts[tier] += 1
        return {t: round(100.0 * c / n, 1) for t, c in counts.items()} if n else {}

    overall = mix(decisions)
    per_bucket = {}
    for d in decisions:
        per_bucket.setdefault(d["bucket"], []).append(d)
    per_bucket_mix = {b: mix(rows) for b, rows in sorted(per_bucket.items())}
    return Finding("RP-004", INFO,
                   f"tier mix: {overall.get(pricing.FRONTIER, 0)}% frontier / "
                   f"{overall.get(pricing.MID, 0)}% mid / {overall.get(pricing.BUDGET, 0)}% budget",
                   "share of decisions by price tier, overall and per bucket.",
                   {"overall_pct": overall, "per_bucket_pct": per_bucket_mix})


def rp005_risk_to_budget(decisions: list[dict]) -> list[Finding]:
    """THE core check: a prompt our risk rules flagged landed on a
    budget-tier model. Each occurrence is its own REVIEW finding with the
    exact rule evidence, so a human can adjudicate prompt by prompt."""
    findings = []
    for d in decisions:
        if d.get("tier") != pricing.BUDGET or not d.get("flags"):
            continue
        rules = ", ".join(f["rule"] for f in d["flags"])
        findings.append(Finding(
            "RP-005", REVIEW, f"risk-flagged prompt routed to budget tier: {d['id']}",
            f"{d['id']} ({d['bucket']}) fired [{rules}] but was routed to "
            f"{d['chosen_model']} ({d.get('provider')}).",
            {"id": d["id"], "bucket": d["bucket"], "model": d["chosen_model"],
             "flags": d["flags"]}))
    return findings


def rp006_savings_left(decisions: list[dict]) -> Finding:
    hits, delta = [], 0.0
    for d in decisions:
        if not d.get("easy") or d.get("tier") != pricing.FRONTIER:
            continue
        chosen = pricing.cost_usd(d["chosen_model"], d["est_in_tokens"], d["est_out_tokens"])
        anchor = pricing.cost_usd(SAVINGS_ANCHOR_MODEL, d["est_in_tokens"], d["est_out_tokens"])
        if chosen is not None and anchor is not None:
            delta += chosen - anchor
        hits.append({"id": d["id"], "model": d["chosen_model"]})
    detail = (f"{len(hits)} counter-rule (easy) prompts were routed to frontier models; "
              f"sending them to {SAVINGS_ANCHOR_MODEL} (the router's own hard-pin default) "
              f"would save ~${delta:.4f} on this corpus. ESTIMATE.")
    return Finding("RP-006", INFO, f"savings left on the table: {len(hits)} easy prompts on frontier",
                   detail, {"count": len(hits), "projected_savings_usd": round(delta, 4),
                            "anchor_model": SAVINGS_ANCHOR_MODEL, "examples": hits[:5]})


def rp007_cost_projection(decisions: list[dict]) -> Finding:
    routed = baseline = 0.0
    excluded: set[str] = set()
    counted = 0
    for d in decisions:
        r = pricing.cost_usd(d["chosen_model"], d["est_in_tokens"], d["est_out_tokens"])
        b = pricing.cost_usd(d["requested_model"], d["est_in_tokens"], d["est_out_tokens"])
        if r is None or b is None:
            # UNKNOWN price on either side: drop the pair so the totals
            # stay comparable, and disclose exactly what was dropped.
            for m, c in ((d["chosen_model"], r), (d["requested_model"], b)):
                if c is None:
                    excluded.add(m)
            continue
        routed += r
        baseline += b
        counted += 1
    delta = routed - baseline
    pct = (100.0 * delta / baseline) if baseline else 0.0
    detail = (f"ESTIMATE over {counted} prompts: routed ${routed:.4f} vs requested-model baseline "
              f"${baseline:.4f} ({delta:+.4f}, {pct:+.1f}%). Basis: len/4 token estimate over the "
              f"full request text, output capped at max_tokens (default guess {DEFAULT_OUT_TOKENS}).")
    if excluded:
        detail += f" Excluded {len(excluded)} model(s) with UNKNOWN pricing: {sorted(excluded)}."
    return Finding("RP-007", INFO, f"projected corpus cost {pct:+.1f}% vs requested baseline (ESTIMATE)",
                   detail, {"routed_usd": round(routed, 4), "baseline_usd": round(baseline, 4),
                            "delta_usd": round(delta, 4), "delta_pct": round(pct, 1),
                            "prompts_counted": counted, "excluded_models": sorted(excluded),
                            "default_out_tokens": DEFAULT_OUT_TOKENS})


def rp008_determinism(probe: list[dict]) -> Finding:
    stable = sum(1 for p in probe if len(set(p["models"])) == 1)
    sev = INFO if stable == len(probe) else WARN
    detail = (f"{stable}/{len(probe)} probe prompts got the same model on all 3 calls. "
              "Note: the router's semantic cache can answer repeats, so this measures the "
              "repeat-call stability a client actually sees, not raw scorer determinism.")
    return Finding("RP-008", sev, f"decision stability {stable}/{len(probe)} prompts",
                   detail, {"probes": probe})


def gate_verdict(findings: list[Finding]) -> str:
    """FAIL only when the run itself cannot be trusted (RP-001/RP-002).
    REVIEW when any risk-flagged prompt hit the budget tier. Else PASS."""
    if any(f.severity == FAIL and f.check in ("RP-001", "RP-002") for f in findings):
        return FAIL
    if any(f.severity == REVIEW for f in findings):
        return REVIEW
    return PASS


def run_all(decisions: list[dict], probe: list[dict], health_ok: bool,
            canary: Optional[dict], canary_error: str = "") -> tuple[list[Finding], str]:
    findings = [rp001_reachability(health_ok, canary, canary_error)]
    if decisions:
        findings += rp002_contract(decisions)
        findings.append(rp003_latency(decisions))
        findings.append(rp004_tier_mix(decisions))
        findings += rp005_risk_to_budget(decisions)
        findings.append(rp006_savings_left(decisions))
        findings.append(rp007_cost_projection(decisions))
    if probe:
        findings.append(rp008_determinism(probe))
    return findings, gate_verdict(findings)
