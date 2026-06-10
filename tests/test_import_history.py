"""Importer logic against a synthetic Claude Code session file.
The live ~/.claude/projects path is deliberately not touched in tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_claude_history import extract_user_texts, redact

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_claude_history.jsonl"


def test_extracts_only_typed_user_text():
    texts = extract_user_texts(SAMPLE)
    # meta command echo, assistant turn, tool_result turn, summary line, and
    # the three known Claude Code echo shapes (<command-name>,
    # <local-command-stdout>, <system-...>) must all be skipped; the three
    # real user messages survive, including the one that begins with pasted
    # XML/JSX, which a bare startswith("<") filter would wrongly drop.
    assert len(texts) == 3
    assert texts[0].startswith("Fix the race condition")
    assert texts[1].startswith("now add a retry")
    assert texts[2].startswith("<Button onClick={save}/>")


def test_redact_scrubs_keys_emails_paths_ips():
    texts = extract_user_texts(SAMPLE)
    scrubbed = redact("\n".join(texts))
    assert "dev@example.com" not in scrubbed
    assert "sk-ant-abc12345678" not in scrubbed
    assert "/home/larry" not in scrubbed
    assert "10.0.0.5" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_KEY]" in scrubbed
    assert "[REDACTED_PATH]" in scrubbed
    assert "[REDACTED_IP]" in scrubbed


def test_redact_leaves_normal_code_alone():
    text = "def retry(fn, attempts=3): pass"
    assert redact(text) == text
