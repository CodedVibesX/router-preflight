from collections import Counter
from pathlib import Path

import pytest

from preflight import pricing
from preflight.corpus import CorpusError, load_corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus" / "coding_agent_v1.jsonl"


def test_shipped_corpus_is_60_prompts_6_buckets_x_10():
    entries = load_corpus(CORPUS)
    assert len(entries) == 60
    counts = Counter(e.bucket for e in entries)
    assert counts == {
        "trivial_factoid": 10, "formatting_sql": 10, "single_file_codegen": 10,
        "repo_refactor": 10, "agentic_tool_loop": 10, "hard_reasoning_debug": 10,
    }


def test_shipped_corpus_requests_a_registry_model():
    for e in load_corpus(CORPUS):
        assert e.request["model"] in pricing.REGISTRY, e.id


def test_agentic_bucket_carries_real_tool_schemas():
    agentic = [e for e in load_corpus(CORPUS) if e.bucket == "agentic_tool_loop"]
    with_tools = [e for e in agentic if e.request.get("tools")]
    assert len(with_tools) == 10
    for e in with_tools:
        assert all("input_schema" in t for t in e.request["tools"]), e.id


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "c.jsonl"
    line = ('{"id": "a", "bucket": "trivial_factoid", "expected_tier": "cheap_ok", '
            '"request": {"model": "m", "messages": [{"role": "user", "content": "hi?"}]}}')
    p.write_text(line + "\n" + line + "\n")
    with pytest.raises(CorpusError, match="duplicate id"):
        load_corpus(p)


def test_unknown_bucket_rejected(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "a", "bucket": "vibes", "expected_tier": "cheap_ok", '
                 '"request": {"model": "m", "messages": [{"role": "user", "content": "hi?"}]}}\n')
    with pytest.raises(CorpusError, match="unknown bucket"):
        load_corpus(p)


def test_malformed_request_rejected(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "a", "bucket": "trivial_factoid", "expected_tier": "cheap_ok", '
                 '"request": {"model": "m", "mesages": []}}\n')
    with pytest.raises(CorpusError, match="bad request"):
        load_corpus(p)
