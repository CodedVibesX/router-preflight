# router-preflight

A preflight gate for adopting the [Weave Router](https://github.com/workweave/router). Before you point coding-agent traffic at a routing layer, replay a prompt corpus through `POST /v1/route`, the endpoint that returns routing decisions without calling any LLM, and read the audit: where your prompts would land, what that mix costs, and which individual decisions deserve a human look before you commit.

The question it answers is narrow on purpose: is it safe to switch my agent's base URL to this router today, with these knobs, for my kind of traffic?

## The recorded run

Everything in `output/` comes from one real run: 60 prompts routed live against a from-source router build (cluster artifact v0.65), June 10, 2026.

    verdict: REVIEW
    frontier share : 78.3%
    cost vs asked  : +52.7% ($2.0893 routed vs $1.3681 baseline, ESTIMATE)
    decision speed : p50 25ms / p95 84ms
    review flags   : 2

The two review flags are the interesting part. `refactor_06` (split a 900-line God class, plan the extraction order) and `refactor_07` (introduce dependency injection across 12 files) both landed on claude-haiku-4-5, the cheapest model in the registry, while the other eight repo-refactor prompts went frontier. Maybe haiku handles them fine. Maybe not. That is exactly the kind of decision you want surfaced before an agent burns a workday on it, and it is why the verdict is REVIEW rather than PASS or FAIL.

The flip side got measured too: 9 of 10 trivial factoid prompts went to frontier models. The v0.65 artifact ships quality-first (alpha=0.96, and the server logs say so loudly). That is a knob setting, not a bug. The gate's job is to put a number on what the knob costs you: about +53% over sending everything to the model you asked for, on this corpus.

## What it checks

| check | what | gate effect |
|---|---|---|
| RP-001 | router reachable, key accepted | FAIL if not |
| RP-002 | decision contract: model+provider present, chosen model in the v0.65 registry | FAIL on violation |
| RP-003 | decision latency p50/p95 | WARN if p95 > 250ms |
| RP-004 | tier mix (frontier/mid/budget), overall and per bucket | info |
| RP-005 | risk-flagged prompt routed to a budget model | REVIEW, one finding per occurrence |
| RP-006 | easy prompts routed to frontier (savings left on the table) | info |
| RP-007 | projected corpus cost vs requested-model baseline | info, ESTIMATE |
| RP-008 | decision stability, 5 prompts x 3 calls | WARN if unstable |

FAIL is reserved for runs the gate itself cannot trust: router down, auth broken, contract violated. Routing choices the heuristics disagree with are REVIEW, never FAIL, because the corpus prior can be wrong and the knobs might be deliberate. Exit codes: 0 PASS, 1 REVIEW, 2 FAIL.

The risk rules (8 of them, plus one cheap-confidence counter-rule) are pure functions with one firing and one non-firing test each. They lean on published evidence: RouterArena (arXiv:2510.00202) for the easy/hard band gap and Bloom-level construction, Avengers-Pro (arXiv:2508.12631) for agentic and hard coding splits, RULER (arXiv:2404.06654) for context-length degradation, SWE-bench (arXiv:2310.06770) for the repo-scope vs snippet distinction.

## Run it

You need a running router and a key. With the router's own docker compose:

    cd router && docker compose up -d && make seed

Or, if you built from source the way the recorded run did (embedded Postgres, pstest Pub/Sub shim, ONNX embedder assets):

    WVR_RUNTIME=/path/to/runtime WVR_BIN=/path/to/bins scripts/start_stack.sh

Then:

    pip install requests pillow pytest
    python scripts/run_preflight.py --base-url http://localhost:8080 --key rk_... \
        --corpus corpus/coding_agent_v1.jsonl --out output/
    python -m preflight.moneyshot output/report.json output/moneyshot.png

Tests run offline against recorded fixtures; the live suite is opt-in:

    pytest                                   # 73 pass offline, 2 live tests skip
    RUN_LIVE=1 WEAVE_ROUTER_KEY=rk_... pytest tests/test_live_integration.py

## The corpus

`corpus/coding_agent_v1.jsonl` is a curated synthetic corpus, not customer data: 60 prompts, six buckets of ten (trivial factoids, formatting/SQL, single-file codegen, repo-scope refactors, agentic tool loops with real tool schemas and tool_result turns, hard reasoning and nondeterministic debugging). Each entry carries `expected_tier`, which is the auditor's prior about where the prompt could safely land. It is a label for analysis, never ground truth; nobody graded model outputs here.

Sixty synthetic prompts tell you about the router. Your own prompts tell you about your bill:

    python scripts/import_claude_history.py --out corpus/mine.jsonl --redact
    python scripts/run_preflight.py --corpus corpus/mine.jsonl --out output-mine/

The importer reads `~/.claude/projects/**/*.jsonl`, keeps only text you actually typed, and `--redact` scrubs keys, emails, paths, and IPs before anything leaves your machine. It is unit-tested against a synthetic sample file; it has not been exercised against a live history in this repo's recorded run.

## What I learned building it

The contract gotcha drove the client design. The route endpoint returns 200 for any JSON object, so a typo like `"mesages"` silently routes on empty text and you get a confident-looking decision about nothing. The client validates its own payloads before sending; that check exists because I hit the failure, not because a linter suggested it.

Decision latency is a real budget line for agents. 25ms median sounds free until you remember an agent loop makes hundreds of route calls per session. p95 here was 84ms on one box with the embedder warm.

And the determinism probe needed honesty: repeats came back 5/5 identical, but the router runs a semantic cache, so that measures the repeat stability a client actually sees, not raw scorer determinism. The finding says so.

## Limitations and non-goals

- This is a decision audit. It never calls an LLM and cannot tell you whether haiku would have answered those two refactor prompts well. Pairing decisions with output quality scoring is the obvious next layer and is out of scope here.
- Token counts are len/4 estimates and output tokens are a max_tokens-capped guess (default 1024). Every dollar figure is an ESTIMATE built from those counts and public list prices as of June 10, 2026, with per-row source URLs in `preflight/pricing.py` and a committed OpenRouter snapshot in `data/`. A model without a verifiable price would be excluded from cost math and disclosed; in v0.65 all 15 have prices.
- The corpus is curated synthetic data unless you import your own history. Results reflect the v0.65 default knobs; retrain the artifact or change alpha and the numbers move.
- The heuristics are recall-imperfect priors. Known miss in the shipped corpus: `refactor_09` (Django multi-tenant rework) fires no rule, so RP-005 would stay silent if it routed cheap. Tightening rules until they catch everything would just overfit the corpus.
- Latency numbers are single-box, client-measured, embedder warm. Not a load test.
- Tier boundaries are a documented judgment call (vendor model-class naming cross-checked against blended list price). `output/decisions.jsonl` keeps model and price per prompt so you can re-cut the tiers without rerunning.

## License

MIT for everything in this repo. The Weave Router itself is ELv2 (Elastic License 2.0); this tool talks to it over HTTP and vendors none of its code.
