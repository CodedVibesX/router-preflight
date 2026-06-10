"""Difficulty heuristics: which prompts are risky to hand a budget model.

Eight risk rules plus one cheap-confidence counter-rule. Each is a pure
function over the request: it returns a Flag with a short evidence string
when it fires, else None. They mark prompts where routing to a bottom-tier
model deserves human review. They are priors, not ground truth.

Grounding for the rule choices:

  * RouterArena (arXiv:2510.00202): routers score >89% on the easy band
    but often <10% on the hard band, and the benchmark builds difficulty
    levels from Bloom's taxonomy. Hence the math/proof rule (1), the
    Bloom verb rule (2), and the non-deterministic debugging rule (7),
    which targets the same hard band.
  * Avengers-Pro (arXiv:2508.12631): cluster-based routing, evaluated on
    tau2-bench and LiveCodeBench hard splits. Multi-step agentic chains
    (3) and tool schemas (4) are where those splits live.
  * RULER (arXiv:2404.06654): effective context length is far below the
    claimed window; quality degrades with input length. Hence the
    estimated-token rule (5).
  * SWE-bench (arXiv:2310.06770): repo-scope tasks are a different class
    of problem from snippet tasks. Hence the repo-scope markers rule (6).

Rule (8), explicit rigor intent, is not benchmark-derived: when the user
says correctness is critical, the cost of a weak model is asymmetric.
"""
from __future__ import annotations

import json
import re
from typing import NamedTuple, Optional


class Flag(NamedTuple):
    rule: str
    evidence: str


def user_text(request: dict) -> str:
    """Concatenated user-role text. Mirrors the router, which embeds only
    user-role text (ROUTER_EMBED_ONLY_USER_MESSAGE=true), so the rules
    judge the same words the scorer sees."""
    parts: list[str] = []
    for msg in request.get("messages", []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def est_tokens(text: str) -> int:
    """len/4 heuristic. An ESTIMATE for thresholds and cost math, not a
    tokenizer. The error band (roughly +/-25% on code-heavy text) is fine
    for the order-of-magnitude decisions made here."""
    return len(text) // 4


_MATH = re.compile(
    r"\b(prove|proof|theorem|lemma|by induction|invariant|np-hard|asymptotic"
    r"|big-?o\b|time complexity|space complexity|converge[sn]?|counterexample)\b",
    re.I,
)
_BLOOM_HIGH = re.compile(
    r"\b(design|architect|optimi[sz]e|refactor|derive|evaluate|critique"
    r"|synthesi[sz]e|justify|trade-?offs?|restructure|extract\w*)\b",
    re.I,
)
_NUMBERED_STEP = re.compile(r"^\s*\d+[.)]\s", re.M)
_CHAINED = re.compile(r"\b(then|after that|next,|finally)\b", re.I)
_TOOL_TEXT = re.compile(r"input_schema|tool_use|tool_result|function_call")
_REPO_PHRASES = re.compile(
    r"across (the )?(codebase|files|services|modules|repos?)|call ?sites?"
    r"|every caller|monorepo|cross-file|in all callers|\b\d+ files\b",
    re.I,
)
_DIFF_HEADER = re.compile(r"^(---|\+\+\+) [ab]/", re.M)
_FILE_PATH = re.compile(r"\b[\w./-]+\.(py|go|ts|tsx|js|rs|java|rb|c|cc|cpp|h|sql|proto)\b")
_NONDET = re.compile(
    r"\b(intermittent(ly)?|flaky|race condition|data race|deadlock|heisenbug"
    r"|non-?deterministic|toctou|only (in|under) (prod|production|load)"
    r"|sometimes (fails|passes|crashes)|occasional(ly)?|once in a while)\b",
    re.I,
)
_RIGOR = re.compile(
    r"must be correct|production-critical|safety-critical|mission-critical"
    r"|zero[- ]downtime|cannot afford|do not guess|regulatory|audit(or|ed)?\b"
    r"|financial (transaction|data)|real money",
    re.I,
)
_WH_OPENER = re.compile(
    r"^(what|which|who|when|where|why|how|is|are|does|do|did|can|should)\b", re.I
)


def math_proof(text: str, request: dict) -> Optional[Flag]:
    m = _MATH.search(text)
    return Flag("math_proof", f"matched {m.group(0)!r}") if m else None


def bloom_higher_order(text: str, request: dict) -> Optional[Flag]:
    """Fires on analyze/evaluate/create verbs, the upper Bloom levels
    RouterArena uses to construct its hard band. Recall verbs (what/list/
    define) deliberately do not fire."""
    m = _BLOOM_HIGH.search(text)
    return Flag("bloom_higher_order", f"matched {m.group(0)!r}") if m else None


def agentic_chain(text: str, request: dict) -> Optional[Flag]:
    steps = len(_NUMBERED_STEP.findall(text))
    if steps >= 3:
        return Flag("agentic_chain", f"{steps} numbered steps")
    chains = len(_CHAINED.findall(text))
    if chains >= 3:
        return Flag("agentic_chain", f"{chains} chained imperatives")
    return None


def tool_schema(text: str, request: dict) -> Optional[Flag]:
    tools = request.get("tools")
    if isinstance(tools, list) and tools:
        names = [t.get("name", "?") for t in tools if isinstance(t, dict)]
        return Flag("tool_schema", f"{len(tools)} tool(s) in request: {', '.join(names[:4])}")
    m = _TOOL_TEXT.search(text)
    return Flag("tool_schema", f"matched {m.group(0)!r} in text") if m else None


def long_context(text: str, request: dict) -> Optional[Flag]:
    toks = est_tokens(full_request_text(request))
    if toks > 32_000:
        return Flag("long_context", f"~{toks} est tokens (len/4) > 32k")
    return None


def repo_scope(text: str, request: dict) -> Optional[Flag]:
    if _DIFF_HEADER.search(text):
        return Flag("repo_scope", "unified diff headers present")
    m = _REPO_PHRASES.search(text)
    if m:
        return Flag("repo_scope", f"matched {m.group(0)!r}")
    paths = {p.group(0) for p in _FILE_PATH.finditer(text)}
    if len(paths) >= 3:
        return Flag("repo_scope", f"{len(paths)} distinct file paths referenced")
    return None


def nondet_debug(text: str, request: dict) -> Optional[Flag]:
    m = _NONDET.search(text)
    return Flag("nondet_debug", f"matched {m.group(0)!r}") if m else None


def rigor_intent(text: str, request: dict) -> Optional[Flag]:
    m = _RIGOR.search(text)
    return Flag("rigor_intent", f"matched {m.group(0)!r}") if m else None


RISK_RULES = (
    math_proof,
    bloom_higher_order,
    agentic_chain,
    tool_schema,
    long_context,
    repo_scope,
    nondet_debug,
    rigor_intent,
)


def risk_flags(request: dict) -> list[Flag]:
    text = user_text(request)
    return [flag for rule in RISK_RULES if (flag := rule(text, request))]


def short_factoid(request: dict, flags: list[Flag]) -> Optional[Flag]:
    """Counter-rule: the prompt looks like a cheap-model slam dunk.
    RouterArena's easy band (>89% router accuracy) is exactly this shape:
    one short recall question, no code, no risk markers."""
    if flags:
        return None
    text = user_text(request).strip()
    if est_tokens(text) >= 100:
        return None
    if "```" in text:
        return None
    if text.count("?") != 1 or not text.endswith("?"):
        return None
    if not _WH_OPENER.match(text):
        return None
    return Flag("short_factoid", f"single wh-question, ~{est_tokens(text)} est tokens")


def full_request_text(request: dict) -> str:
    """Everything a downstream model would actually be billed for:
    system + all message text + serialized tool schemas."""
    parts: list[str] = []
    system = request.get("system")
    if isinstance(system, str):
        parts.append(system)
    elif isinstance(system, list):
        parts.append(json.dumps(system))
    for msg in request.get("messages", []):
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.append(json.dumps(content))
    if request.get("tools"):
        parts.append(json.dumps(request["tools"]))
    return "\n".join(parts)
