"""Replay recorded router traffic through the audit logic, offline.

Two fixture sets:
  * keystone_fixtures.jsonl: 10 requests captured against the live router
    while standing the stack up (independent of this tool's runner).
  * captured_run.jsonl: the 60 decisions from the recorded full run that
    produced output/report.json. Re-running the checks over it must
    reproduce the committed verdict and headline numbers, which keeps the
    published artifacts honest.
"""
import json
from pathlib import Path

from preflight import checks, heuristics, pricing

ROOT = Path(__file__).resolve().parents[1]
KEYSTONE = ROOT / "tests" / "fixtures" / "keystone_fixtures.jsonl"
CAPTURED = ROOT / "tests" / "fixtures" / "captured_run.jsonl"
REPORT = ROOT / "output" / "report.json"


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_keystone_responses_conform_to_contract():
    records = load_jsonl(KEYSTONE)
    assert len(records) == 10
    for r in records:
        assert r["status"] == 200
        resp = r["response"]
        assert set(resp) >= {"model", "provider", "reason"}
        assert resp["model"] in pricing.REGISTRY, resp["model"]
        assert r["latency_ms"] > 0


def test_keystone_records_survive_the_full_check_pipeline():
    decisions = []
    for r in load_jsonl(KEYSTONE):
        request, resp = r["request"], r["response"]
        flags = heuristics.risk_flags(request)
        decisions.append({
            "id": r["name"], "bucket": "imported", "expected_tier": "either",
            "requested_model": request["model"], "chosen_model": resp["model"],
            "provider": resp["provider"], "reason": resp["reason"],
            "latency_ms": r["latency_ms"],
            "est_in_tokens": heuristics.est_tokens(heuristics.full_request_text(request)),
            "est_out_tokens": request.get("max_tokens") or checks.DEFAULT_OUT_TOKENS,
            "flags": [f._asdict() for f in flags],
            "easy": None, "tier": pricing.tier_of(resp["model"]),
        })
    findings, verdict = checks.run_all(decisions, [], True, {"chosen_model": "x"})
    assert verdict in ("PASS", "REVIEW")
    # The keystone capture requested claude-sonnet-4-5, which is NOT in the
    # v0.65 registry, so RP-007 must exclude it rather than invent a price.
    rp007 = next(f for f in findings if f.check == "RP-007")
    assert "claude-sonnet-4-5" in rp007.evidence["excluded_models"]


def test_captured_run_reproduces_committed_report():
    decisions = load_jsonl(CAPTURED)
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    probe = report["probe"]
    findings, verdict = checks.run_all(decisions, probe, True, {"chosen_model": "x"})
    assert verdict == report["verdict"]
    rp004 = next(f for f in findings if f.check == "RP-004")
    assert rp004.evidence["overall_pct"]["frontier"] == report["headline"]["frontier_share_pct"]
    rp007 = next(f for f in findings if f.check == "RP-007")
    assert rp007.evidence["delta_pct"] == report["headline"]["cost_delta_pct_vs_requested"]
