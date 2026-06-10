"""Load and validate the prompt corpus (JSONL).

Each line: {"id", "bucket", "request", "expected_tier"} where request is a
full /v1/route body. expected_tier is OUR prior about where the prompt
could safely land ("cheap_ok" / "frontier_expected" / "either"). It is an
analysis label, never ground truth: nobody has graded model outputs here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .client import PayloadError, validate_payload

BUCKETS = frozenset({
    "trivial_factoid", "formatting_sql", "single_file_codegen",
    "repo_refactor", "agentic_tool_loop", "hard_reasoning_debug",
    "imported",  # produced by scripts/import_claude_history.py
})
EXPECTED_TIERS = frozenset({"cheap_ok", "frontier_expected", "either"})


class CorpusError(ValueError):
    pass


@dataclass(frozen=True)
class CorpusEntry:
    id: str
    bucket: str
    request: dict
    expected_tier: str


def load_corpus(path: str | Path) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as err:
            raise CorpusError(f"{path}:{lineno}: invalid JSON: {err}") from err
        missing = {"id", "bucket", "request", "expected_tier"} - set(raw)
        if missing:
            raise CorpusError(f"{path}:{lineno}: missing keys {sorted(missing)}")
        if raw["id"] in seen_ids:
            raise CorpusError(f"{path}:{lineno}: duplicate id {raw['id']!r}")
        seen_ids.add(raw["id"])
        if raw["bucket"] not in BUCKETS:
            raise CorpusError(f"{path}:{lineno}: unknown bucket {raw['bucket']!r}")
        if raw["expected_tier"] not in EXPECTED_TIERS:
            raise CorpusError(f"{path}:{lineno}: unknown expected_tier {raw['expected_tier']!r}")
        try:
            validate_payload(raw["request"])
        except PayloadError as err:
            raise CorpusError(f"{path}:{lineno}: bad request: {err}") from err
        entries.append(CorpusEntry(raw["id"], raw["bucket"], raw["request"], raw["expected_tier"]))
    if not entries:
        raise CorpusError(f"{path}: empty corpus")
    return entries
