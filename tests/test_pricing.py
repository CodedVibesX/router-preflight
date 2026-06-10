from preflight import pricing


def test_registry_has_exactly_15_models():
    assert len(pricing.PRICES) == 15


def test_all_shipped_prices_are_known_and_sourced():
    for p in pricing.PRICES.values():
        assert p.known, f"{p.model} shipped without a price"
        assert p.source.startswith("https://")
        assert p.seen == "2026-06-10"


def test_frontier_tier_is_the_four_flagships():
    frontier = {m for m, p in pricing.PRICES.items() if p.tier == pricing.FRONTIER}
    assert frontier == {"claude-opus-4-7", "claude-opus-4-8", "gpt-5.5",
                        "gemini-3.1-pro-preview"}


def test_cost_usd_math():
    # sonnet-4-6: $3 in / $15 out per Mtok
    assert pricing.cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0
    assert pricing.cost_usd("claude-sonnet-4-6", 500_000, 0) == 1.5


def test_cost_usd_returns_none_for_unregistered_model():
    assert pricing.cost_usd("not-a-model", 1000, 1000) is None


def test_cost_usd_returns_none_for_unknown_price(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "mystery-model",
                        pricing.ModelPrice("mystery-model", "acme", pricing.MID,
                                           None, None, "nowhere"))
    assert pricing.cost_usd("mystery-model", 1000, 1000) is None


def test_pricing_table_carries_sources():
    table = pricing.pricing_table()
    assert len(table) == 15
    assert all(row["source"] and row["seen"] for row in table)


def test_openrouter_rows_match_committed_snapshot():
    """The 8 OpenRouter-sourced prices must equal the live snapshot
    fetched on 2026-06-10 and committed under data/. (The snapshot's
    9th row, gemini-3.1-pro-preview, is priced from Google's page.)"""
    import json
    from pathlib import Path
    snap_path = Path(__file__).resolve().parents[1] / "data" / "openrouter_prices_2026-06-10.json"
    snap = {m["id"]: m["pricing"] for m in json.loads(snap_path.read_text())["models"]}
    or_models = {
        "deepseek/deepseek-v4-flash": "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro": "deepseek/deepseek-v4-pro",
        "moonshotai/kimi-k2.6": "moonshotai/kimi-k2.6",
        "qwen/qwen3-coder-next": "qwen/qwen3-coder-next",
        "qwen/qwen3-next-80b-a3b-instruct": "qwen/qwen3-next-80b-a3b-instruct",
        "xiaomi/mimo-v2.5-pro": "xiaomi/mimo-v2.5-pro",
        "gemini-3.5-flash": "google/gemini-3.5-flash",
        "gemini-3.1-flash-lite-preview": "google/gemini-3.1-flash-lite-preview",
    }
    for registry_id, openrouter_id in or_models.items():
        p = pricing.PRICES[registry_id]
        live_in = float(snap[openrouter_id]["prompt"]) * 1e6
        live_out = float(snap[openrouter_id]["completion"]) * 1e6
        assert abs(p.usd_in - live_in) < 1e-6, registry_id
        assert abs(p.usd_out - live_out) < 1e-6, registry_id
