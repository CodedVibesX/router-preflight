#!/usr/bin/env python3
"""Run the preflight gate against a live Weave Router.

Usage:
  python scripts/run_preflight.py --base-url http://localhost:8080 \\
      --key rk_... --corpus corpus/coding_agent_v1.jsonl --out output/

Exit codes: 0 PASS, 1 REVIEW, 2 FAIL. Wire it into CI like any other gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preflight import checks, heuristics, pricing, report as report_mod
from preflight.client import ContractError, RouteClient, RouterUnavailable
from preflight.corpus import load_corpus

PROBE_CALLS = 3
PROBE_PROMPTS = 5
_CLUSTER_RE = re.compile(r"cluster:(v[\d.]+)")


def route_corpus(client: RouteClient, entries) -> list[dict]:
    decisions = []
    for entry in entries:
        decision = client.route(entry.request)
        flags = heuristics.risk_flags(entry.request)
        easy = heuristics.short_factoid(entry.request, flags)
        full_text = heuristics.full_request_text(entry.request)
        out_tokens = entry.request.get("max_tokens") or checks.DEFAULT_OUT_TOKENS
        decisions.append({
            "id": entry.id,
            "bucket": entry.bucket,
            "expected_tier": entry.expected_tier,
            "requested_model": entry.request["model"],
            "chosen_model": decision.model,
            "provider": decision.provider,
            "reason": decision.reason,
            "latency_ms": decision.latency_ms,
            "est_in_tokens": heuristics.est_tokens(full_text),
            "est_out_tokens": min(out_tokens, checks.DEFAULT_OUT_TOKENS * 8),
            "flags": [f._asdict() for f in flags],
            "easy": easy._asdict() if easy else None,
            "tier": pricing.tier_of(decision.model),
        })
        print(f"  {entry.id:28s} -> {decision.model:34s} {decision.latency_ms:7.1f}ms", flush=True)
    return decisions


def determinism_probe(client: RouteClient, entries) -> list[dict]:
    # Stride 13, not a round 12: on the 60-entry corpus that is indices
    # 0/13/26/39/52, which reaches the hard_reasoning_debug bucket at the
    # tail; a stride of 12 would stop at index 48 and never probe it.
    chosen = entries[::13][:PROBE_PROMPTS]
    probe = []
    for entry in chosen:
        models = [client.route(entry.request).model for _ in range(PROBE_CALLS)]
        probe.append({"id": entry.id, "models": models, "stable": len(set(models)) == 1})
    return probe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.environ.get("ROUTER_BASE_URL", "http://localhost:8080"))
    ap.add_argument("--key", default=os.environ.get("WEAVE_ROUTER_KEY"))
    ap.add_argument("--corpus", default="corpus/coding_agent_v1.jsonl")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    if not args.key:
        ap.error("pass --key or set WEAVE_ROUTER_KEY")

    entries = load_corpus(args.corpus)
    client = RouteClient(args.base_url, args.key)

    health_ok = client.health()
    canary, canary_error, decisions, probe = None, "", [], []
    if health_ok:
        try:
            d = client.route({"model": entries[0].request["model"],
                              "messages": [{"role": "user", "content": "canary: which model would you pick?"}]})
            canary = {"chosen_model": d.model, "provider": d.provider}
        except (ContractError, RouterUnavailable) as err:
            canary_error = str(err)
    if canary:
        print(f"routing {len(entries)} prompts against {args.base_url} ...")
        decisions = route_corpus(client, entries)
        probe = determinism_probe(client, entries)

    findings, verdict = checks.run_all(decisions, probe, health_ok, canary, canary_error)

    cluster = "unknown"
    if decisions:
        m = _CLUSTER_RE.search(decisions[0]["reason"])
        cluster = m.group(1) if m else "unknown"
    meta = {
        "base_url": args.base_url,
        "corpus": args.corpus,
        "cluster_version": cluster,
        "run_date": date.today().isoformat(),
        "corpus_kind": "curated synthetic (not customer data)",
    }
    rep = report_mod.build_report(meta, decisions, findings, verdict, probe)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")
    report_mod.write_outputs(rep, out)
    print(report_mod.render_terminal(rep))
    print(f"\nwrote {out / 'decisions.jsonl'}, {out / 'report.json'}, {out / 'report.html'}")
    return {"PASS": 0, "REVIEW": 1, "FAIL": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
