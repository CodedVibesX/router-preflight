"""Every severity path through the checks, including a deliberately
broken contract response and the UNKNOWN-pricing exclusion."""
from preflight import checks, pricing
from preflight.checks import (FAIL, INFO, PASS, REVIEW, WARN, gate_verdict,
                              rp001_reachability, rp002_contract, rp003_latency,
                              rp004_tier_mix, rp005_risk_to_budget,
                              rp006_savings_left, rp007_cost_projection,
                              rp008_determinism)


def decision(id="p1", bucket="trivial_factoid", chosen="claude-opus-4-8",
             provider="anthropic", requested="claude-sonnet-4-6", latency=12.0,
             flags=None, easy=None, in_tok=100, out_tok=1024):
    return {
        "id": id, "bucket": bucket, "expected_tier": "either",
        "requested_model": requested, "chosen_model": chosen, "provider": provider,
        "reason": "cluster:v0.65 ...", "latency_ms": latency,
        "est_in_tokens": in_tok, "est_out_tokens": out_tok,
        "flags": flags or [], "easy": easy, "tier": pricing.tier_of(chosen),
    }


def test_rp001_fails_when_down():
    assert rp001_reachability(False, None).severity == FAIL


def test_rp001_fails_on_auth_or_route_error():
    f = rp001_reachability(True, None, "HTTP 401: missing router key")
    assert f.severity == FAIL and "401" in f.detail


def test_rp001_passes_with_canary():
    assert rp001_reachability(True, {"chosen_model": "claude-opus-4-8"}).severity == PASS


def test_rp002_passes_on_registry_models():
    findings = rp002_contract([decision(), decision(id="p2", chosen="claude-haiku-4-5")])
    assert [f.severity for f in findings] == [PASS]


def test_rp002_fails_on_model_outside_registry():
    # Deliberately broken decision: a model the v0.65 artifact cannot produce.
    findings = rp002_contract([decision(chosen="gpt-7-ultra")])
    assert findings[0].severity == FAIL
    assert "gpt-7-ultra" in findings[0].detail


def test_rp002_fails_on_missing_provider():
    findings = rp002_contract([decision(provider="")])
    assert findings[0].severity == FAIL


def test_rp003_info_when_fast():
    f = rp003_latency([decision(latency=10.0) for _ in range(10)])
    assert f.severity == INFO and f.evidence["p95_ms"] == 10.0


def test_rp003_warns_on_slow_p95():
    rows = [decision(latency=10.0) for _ in range(9)] + [decision(latency=400.0)]
    f = rp003_latency(rows)
    assert f.severity == WARN and f.evidence["p95_ms"] == 400.0


def test_rp004_tier_mix_math():
    rows = [decision(chosen="claude-opus-4-8"), decision(chosen="claude-sonnet-4-6"),
            decision(chosen="claude-haiku-4-5"), decision(chosen="gpt-5.5")]
    f = rp004_tier_mix(rows)
    assert f.evidence["overall_pct"] == {"frontier": 50.0, "mid": 25.0, "budget": 25.0}


def test_rp005_reviews_flagged_prompt_on_budget_model():
    d = decision(chosen="deepseek/deepseek-v4-flash",
                 flags=[{"rule": "nondet_debug", "evidence": "matched 'race condition'"}])
    findings = rp005_risk_to_budget([d])
    assert len(findings) == 1
    assert findings[0].severity == REVIEW
    assert "nondet_debug" in findings[0].detail


def test_rp005_silent_when_flagged_prompt_goes_frontier():
    d = decision(chosen="claude-opus-4-8",
                 flags=[{"rule": "math_proof", "evidence": "matched 'prove'"}])
    assert rp005_risk_to_budget([d]) == []


def test_rp005_silent_when_unflagged_prompt_goes_budget():
    assert rp005_risk_to_budget([decision(chosen="claude-haiku-4-5")]) == []


def test_rp006_counts_easy_on_frontier_and_projects_savings():
    d = decision(chosen="claude-opus-4-8", easy={"rule": "short_factoid", "evidence": "..."},
                 in_tok=1000, out_tok=1000)
    f = rp006_savings_left([d])
    assert f.evidence["count"] == 1
    # opus (5+25) vs haiku (1+5) on 1k/1k tokens: delta = 0.030 - 0.006
    assert abs(f.evidence["projected_savings_usd"] - 0.024) < 1e-9


def test_rp007_cost_math_known_models():
    d = decision(chosen="claude-opus-4-8", requested="claude-sonnet-4-6",
                 in_tok=1_000_000, out_tok=0)
    f = rp007_cost_projection([d])
    assert f.evidence["routed_usd"] == 5.0
    assert f.evidence["baseline_usd"] == 3.0
    assert f.evidence["prompts_counted"] == 1


def test_rp007_excludes_unknown_priced_models(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "mystery-model",
                        pricing.ModelPrice("mystery-model", "acme", pricing.MID,
                                           None, None, "nowhere"))
    rows = [decision(chosen="mystery-model"), decision(chosen="claude-opus-4-8")]
    f = rp007_cost_projection(rows)
    assert f.evidence["prompts_counted"] == 1
    assert f.evidence["excluded_models"] == ["mystery-model"]
    assert "UNKNOWN" in f.detail


def test_rp008_info_when_stable():
    probe = [{"id": f"p{i}", "models": ["m", "m", "m"]} for i in range(5)]
    assert rp008_determinism(probe).severity == INFO


def test_rp008_warns_when_unstable():
    probe = [{"id": "p0", "models": ["a", "b", "a"]}] + \
            [{"id": f"p{i}", "models": ["m", "m", "m"]} for i in range(1, 5)]
    f = rp008_determinism(probe)
    assert f.severity == WARN and "4/5" in f.title


def test_verdict_fail_beats_review():
    findings = [checks.Finding("RP-001", FAIL, "down", ""),
                checks.Finding("RP-005", REVIEW, "x", "")]
    assert gate_verdict(findings) == FAIL


def test_verdict_review_when_any_rp005():
    findings = [checks.Finding("RP-001", PASS, "ok", ""),
                checks.Finding("RP-005", REVIEW, "x", "")]
    assert gate_verdict(findings) == REVIEW


def test_verdict_pass_on_info_and_warn_only():
    findings = [checks.Finding("RP-001", PASS, "ok", ""),
                checks.Finding("RP-003", WARN, "slow", "")]
    assert gate_verdict(findings) == PASS
