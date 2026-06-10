"""End-to-end against a live router. Gated: RUN_LIVE=1 plus a key.

    RUN_LIVE=1 WEAVE_ROUTER_KEY=rk_... pytest tests/test_live_integration.py
"""
import os

import pytest

from preflight import pricing
from preflight.client import RouteClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1" or not os.environ.get("WEAVE_ROUTER_KEY"),
    reason="live stack test; set RUN_LIVE=1 and WEAVE_ROUTER_KEY",
)


def client():
    return RouteClient(os.environ.get("ROUTER_BASE_URL", "http://localhost:8080"),
                       os.environ["WEAVE_ROUTER_KEY"])


def test_health_and_live_decision():
    c = client()
    assert c.health()
    d = c.route({"model": "claude-sonnet-4-6",
                 "messages": [{"role": "user", "content": "What is the capital of France?"}]})
    assert d.model in pricing.REGISTRY
    assert d.provider
    assert "cluster:" in d.reason


def test_live_decision_latency_sane():
    c = client()
    d = c.route({"model": "claude-sonnet-4-6",
                 "messages": [{"role": "user", "content": "Convert 3 feet to meters?"}]})
    assert 0 < d.latency_ms < 5000
