"""One firing and one non-firing case per rule, so a regex edit that
breaks a rule breaks a named test."""
from preflight import heuristics as h


def req(text: str, **extra) -> dict:
    body = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": text}]}
    body.update(extra)
    return body


def fired(rule_fn, text, request=None):
    request = request or req(text)
    return rule_fn(h.user_text(request), request)


def test_math_proof_fires_on_proof_language():
    flag = fired(h.math_proof, "Prove the loop invariant holds by induction.")
    assert flag and ("induction" in flag.evidence or "prove" in flag.evidence.lower())


def test_math_proof_ignores_plain_question():
    assert fired(h.math_proof, "What port does Postgres use?") is None


def test_bloom_fires_on_higher_order_verbs():
    assert fired(h.bloom_higher_order, "Design a sharded rate limiter and justify the trade-offs.")


def test_bloom_ignores_recall_verbs():
    assert fired(h.bloom_higher_order, "What does CRUD stand for? List the letters.") is None


def test_agentic_chain_fires_on_numbered_steps():
    text = "Do this:\n1. parse the file\n2. validate rows\n3. write the summary\n4. email me"
    flag = fired(h.agentic_chain, text)
    assert flag and "numbered steps" in flag.evidence


def test_agentic_chain_ignores_two_steps():
    assert fired(h.agentic_chain, "1. read\n2. write") is None


def test_tool_schema_fires_on_tools_key():
    request = req("fix the failing test", tools=[{"name": "run_tests", "input_schema": {}}])
    flag = h.tool_schema(h.user_text(request), request)
    assert flag and "run_tests" in flag.evidence


def test_tool_schema_ignores_plain_prompt():
    assert fired(h.tool_schema, "rename a variable for me") is None


def test_long_context_fires_above_32k_est_tokens():
    request = req("x" * (32_001 * 4))
    assert h.long_context(h.user_text(request), request)


def test_long_context_ignores_short_prompt():
    assert fired(h.long_context, "short") is None


def test_repo_scope_fires_on_diff_headers():
    flag = fired(h.repo_scope, "--- a/store/cache.py\n+++ b/store/cache.py\nreview this")
    assert flag and "diff" in flag.evidence


def test_repo_scope_fires_on_call_sites():
    assert fired(h.repo_scope, "update the 23 call sites that use this client")


def test_repo_scope_ignores_single_snippet():
    assert fired(h.repo_scope, "write a function that reverses a string") is None


def test_nondet_fires_on_race_language():
    flag = fired(h.nondet_debug, "it deadlocks intermittently under load")
    assert flag


def test_nondet_ignores_deterministic_bug():
    assert fired(h.nondet_debug, "this always crashes on line 3 with a TypeError") is None


def test_rigor_fires_on_correctness_demands():
    assert fired(h.rigor_intent, "This must be correct, it moves real money.")


def test_rigor_ignores_casual_ask():
    assert fired(h.rigor_intent, "got a quick sql question for you") is None


def test_short_factoid_fires_on_wh_question():
    request = req("What is the default port for PostgreSQL?")
    flags = h.risk_flags(request)
    assert flags == []
    assert h.short_factoid(request, flags)


def test_short_factoid_blocked_by_risk_flags():
    request = req("What is the proof of the master theorem?")
    flags = h.risk_flags(request)
    assert flags  # math_proof fires
    assert h.short_factoid(request, flags) is None


def test_short_factoid_rejects_code_fences():
    request = req("What does this do?\n```python\nprint(1)\n```")
    assert h.short_factoid(request, h.risk_flags(request)) is None


def test_user_text_extracts_only_user_role():
    request = {"model": "m", "messages": [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "IGNORED"},
        {"role": "user", "content": [{"type": "text", "text": "second"},
                                     {"type": "tool_result", "content": "IGNORED TOO"}]},
    ]}
    assert h.user_text(request) == "first\nsecond"
