#!/usr/bin/env python3
"""Turn your own Claude Code history into a preflight corpus.

Reads ~/.claude/projects/**/*.jsonl session files, pulls out the user
messages you actually typed, and writes them in the corpus JSONL format so
you can audit the router against YOUR traffic instead of the curated
synthetic corpus.

Honesty note: the session-file shape handled here ({"type": "user",
"message": {"role": "user", "content": ...}}) matches Claude Code 1.x
local history. The extraction and redaction logic is unit-tested against
a synthetic sample (tests/fixtures/sample_claude_history.jsonl); it has
NOT been run against a live history inside this repo's recorded run.

Usage:
  python scripts/import_claude_history.py --out corpus/mine.jsonl --redact
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Redaction is best-effort hygiene for sharing, not a DLP guarantee.
_REDACTIONS = (
    (re.compile(r"\b(sk|rk|sk-ant|sk-or-v1)[-_][A-Za-z0-9_-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?:/home/|/Users/|C:\\Users\\)[^\s'\"]+"), "[REDACTED_PATH]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "[REDACTED_IP]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def extract_user_texts(session_file: Path) -> list[str]:
    """User-typed text only: skips meta entries, tool results, and the
    synthetic command echoes Claude Code writes into the transcript."""
    texts = []
    for line in session_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "user" or entry.get("isMeta"):
            continue
        message = entry.get("message") or {}
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts = [content]
        elif isinstance(content, list):
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
        else:
            continue
        text = "\n".join(p for p in parts if p).strip()
        if text and not text.startswith("<"):
            texts.append(text)
    return texts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--redact", action="store_true", help="scrub keys, emails, paths, IPs")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="requested model to record")
    ap.add_argument("--limit", type=int, default=200, help="max prompts to emit")
    args = ap.parse_args()

    root = Path(args.claude_dir)
    if not root.is_dir():
        print(f"no history at {root}", file=sys.stderr)
        return 1

    count = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for session_file in sorted(root.glob("**/*.jsonl")):
            for text in extract_user_texts(session_file):
                if count >= args.limit:
                    break
                if args.redact:
                    text = redact(text)
                entry = {
                    "id": f"imported_{count:04d}",
                    "bucket": "imported",
                    "request": {"model": args.model,
                                "messages": [{"role": "user", "content": text}]},
                    "expected_tier": "either",
                }
                out.write(json.dumps(entry) + "\n")
                count += 1
    print(f"wrote {count} prompts to {args.out}")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
