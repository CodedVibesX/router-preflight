"""Client behavior: payload self-validation, contract parsing, retries.
The HTTP layer is stubbed; the validation/parse/retry logic under test
is the real code."""
import json

import pytest

from preflight.client import (ContractError, PayloadError, RouteClient,
                              RouterUnavailable, validate_payload)


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


GOOD = {"model": "claude-opus-4-8", "provider": "anthropic", "reason": "cluster:v0.65 ..."}


def make_client(monkeypatch, responses):
    client = RouteClient("http://example.test", "rk_test")
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        resp = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return resp

    monkeypatch.setattr(client.session, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return client, calls


def test_typoed_field_rejected_before_sending():
    # The server would 200 on this and route on empty text. We refuse to send it.
    with pytest.raises(PayloadError, match="mesages"):
        validate_payload({"model": "m", "mesages": [{"role": "user", "content": "hi"}]})


def test_empty_messages_rejected():
    with pytest.raises(PayloadError):
        validate_payload({"model": "m", "messages": []})


def test_bad_role_rejected():
    with pytest.raises(PayloadError, match="role"):
        validate_payload({"model": "m", "messages": [{"role": "system", "content": "x"}]})


def test_valid_payload_passes():
    validate_payload({"model": "m", "messages": [{"role": "user", "content": "hi"}],
                      "system": "s", "tools": [], "max_tokens": 10})


def test_route_parses_decision(monkeypatch):
    client, _ = make_client(monkeypatch, [FakeResponse(200, GOOD)])
    d = client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert d.model == "claude-opus-4-8"
    assert d.provider == "anthropic"
    assert d.latency_ms >= 0


def test_route_retries_502_then_succeeds(monkeypatch):
    client, calls = make_client(monkeypatch, [FakeResponse(502, text="bad gateway"),
                                              FakeResponse(200, GOOD)])
    d = client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert d.model == "claude-opus-4-8"
    assert calls["n"] == 2


def test_route_does_not_retry_401(monkeypatch):
    client, calls = make_client(monkeypatch, [FakeResponse(401, text="unauthorized")])
    with pytest.raises(ContractError, match="401"):
        client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert calls["n"] == 1


def test_missing_provider_is_contract_error(monkeypatch):
    client, _ = make_client(monkeypatch, [FakeResponse(200, {"model": "x", "reason": "r"})])
    with pytest.raises(ContractError, match="provider"):
        client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})


def test_exhausted_retries_raise_unavailable(monkeypatch):
    client, calls = make_client(monkeypatch, [FakeResponse(503, text="scorer down")])
    with pytest.raises(ContractError, match="503"):
        client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    # 503 is retried twice, then surfaced from the final attempt
    assert calls["n"] == 3


def test_connection_errors_raise_unavailable(monkeypatch):
    import requests as req_lib
    client = RouteClient("http://example.test", "rk_test", retries=1)

    def boom(url, json=None, timeout=None):
        raise req_lib.ConnectionError("refused")

    monkeypatch.setattr(client.session, "post", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RouterUnavailable):
        client.route({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
