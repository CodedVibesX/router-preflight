"""List prices and tier map for the 15 models in the v0.65 cluster registry.

Every price is a public list price in USD per million tokens with its
source URL and the date it was read. None of these numbers are invented:
the OpenRouter rows were fetched live from openrouter.ai/api/v1/models on
2026-06-10, and a filtered extract of that response is committed at
data/openrouter_prices_2026-06-10.json: the 8 models priced from it, plus
gemini-3.1-pro-preview kept in the extract as a cross-check against the
Google page it is actually priced from. The rest were read from the
vendors' published pricing pages the same day.
A model with no verifiable price gets price=None (UNKNOWN) and is excluded
from all cost math, with a warning the caller is expected to surface.

Tiers are a judgment call and are documented as one. "frontier" is the four
flagship reasoning models the router can escalate to. Below that, the split
follows the vendors' own model-class naming (haiku / mini / lite / flash =
budget) cross-checked against blended list price; deepseek-v4-pro and
mimo-v2.5-pro are priced under $1/Mtok blended but are positioned as
full-strength models, so they sit in "mid". The raw decisions.jsonl keeps
chosen model and price per prompt, so a reviewer who draws the line
elsewhere can re-cut the data without rerunning anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FRONTIER = "frontier"
MID = "mid"
BUDGET = "budget"

_ANTHROPIC_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
_OPENAI_PRICING = "https://openai.com/api/pricing"
_OPENAI_DEV_PRICING = "https://developers.openai.com/api/docs/pricing"
_GOOGLE_PRICING = "https://ai.google.dev/gemini-api/docs/pricing"
_OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
_SEEN = "2026-06-10"


@dataclass(frozen=True)
class ModelPrice:
    model: str
    provider: str
    tier: str
    usd_in: Optional[float]   # USD per 1M input tokens; None = UNKNOWN
    usd_out: Optional[float]  # USD per 1M output tokens; None = UNKNOWN
    source: str
    seen: str = _SEEN

    @property
    def known(self) -> bool:
        return self.usd_in is not None and self.usd_out is not None


def _p(model: str, provider: str, tier: str, usd_in: Optional[float],
       usd_out: Optional[float], source: str) -> ModelPrice:
    return ModelPrice(model, provider, tier, usd_in, usd_out, source)


PRICES: dict[str, ModelPrice] = {p.model: p for p in (
    _p("claude-haiku-4-5", "anthropic", BUDGET, 1.00, 5.00, _ANTHROPIC_PRICING),
    _p("claude-sonnet-4-6", "anthropic", MID, 3.00, 15.00, _ANTHROPIC_PRICING),
    _p("claude-opus-4-7", "anthropic", FRONTIER, 5.00, 25.00, _ANTHROPIC_PRICING),
    _p("claude-opus-4-8", "anthropic", FRONTIER, 5.00, 25.00, _ANTHROPIC_PRICING),
    _p("gpt-5.5", "openai", FRONTIER, 5.00, 30.00, _OPENAI_PRICING),
    _p("gpt-5.4-mini", "openai", BUDGET, 0.75, 4.50, _OPENAI_DEV_PRICING),
    _p("gemini-3.1-pro-preview", "google", FRONTIER, 2.00, 12.00, _GOOGLE_PRICING),
    _p("gemini-3.5-flash", "google", MID, 1.50, 9.00, _OPENROUTER_MODELS),
    _p("gemini-3.1-flash-lite-preview", "google", BUDGET, 0.25, 1.50, _OPENROUTER_MODELS),
    _p("qwen/qwen3-coder-next", "bedrock", BUDGET, 0.11, 0.80, _OPENROUTER_MODELS),
    _p("qwen/qwen3-next-80b-a3b-instruct", "bedrock", BUDGET, 0.09, 1.10, _OPENROUTER_MODELS),
    _p("deepseek/deepseek-v4-flash", "deepinfra", BUDGET, 0.0983, 0.1966, _OPENROUTER_MODELS),
    _p("xiaomi/mimo-v2.5-pro", "deepinfra", MID, 0.435, 0.87, _OPENROUTER_MODELS),
    _p("deepseek/deepseek-v4-pro", "fireworks", MID, 0.435, 0.87, _OPENROUTER_MODELS),
    _p("moonshotai/kimi-k2.6", "fireworks", MID, 0.68, 3.41, _OPENROUTER_MODELS),
)}

REGISTRY = frozenset(PRICES)


def tier_of(model: str) -> Optional[str]:
    info = PRICES.get(model)
    return info.tier if info else None


def cost_usd(model: str, in_tokens: int, out_tokens: int) -> Optional[float]:
    """ESTIMATE: list price applied to len/4 token estimates.
    Returns None for models with UNKNOWN pricing so callers cannot
    silently fold a made-up number into a total."""
    info = PRICES.get(model)
    if info is None or not info.known:
        return None
    return (in_tokens * info.usd_in + out_tokens * info.usd_out) / 1_000_000


def pricing_table() -> list[dict]:
    """Structured table for report.json: every number with its source."""
    return [
        {
            "model": p.model, "provider": p.provider, "tier": p.tier,
            "usd_per_mtok_in": p.usd_in, "usd_per_mtok_out": p.usd_out,
            "source": p.source, "seen": p.seen,
        }
        for p in sorted(PRICES.values(), key=lambda x: (x.tier, x.model))
    ]
