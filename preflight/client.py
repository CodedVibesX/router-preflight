"""Client for the Weave Router decision endpoint (POST /v1/route).

The endpoint scores an Anthropic Messages-shaped request and returns the
routing decision without calling any upstream LLM:

    {"model": "...", "provider": "...", "reason": "cluster:v0.65 ..."}

Two contract details drive the design:

  * The server returns 200 for ANY JSON object. A typo'd field name
    ("mesages") silently routes on empty text, so this client validates
    its own payload before sending rather than trusting the server to
    reject garbage.
  * Only "model" and "provider" are stable outputs. "reason" is a
    diagnostic string whose format can change between cluster versions,
    so it is carried through verbatim and never parsed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

ALLOWED_KEYS = {"model", "messages", "system", "tools", "max_tokens"}
ALLOWED_ROLES = {"user", "assistant"}
RETRYABLE_STATUS = {502, 503}


class PayloadError(ValueError):
    """The request body would not exercise the router the way we think."""


class ContractError(RuntimeError):
    """The router's response broke the documented decision contract."""


class RouterUnavailable(RuntimeError):
    """The router could not be reached after retries."""


@dataclass(frozen=True)
class RouteDecision:
    model: str
    provider: str
    reason: str
    status_code: int
    latency_ms: float


def validate_payload(body: dict) -> None:
    """Reject bodies the server would silently accept but score on empty text."""
    if not isinstance(body, dict):
        raise PayloadError(f"body must be a dict, got {type(body).__name__}")
    unknown = set(body) - ALLOWED_KEYS
    if unknown:
        raise PayloadError(f"unknown top-level keys {sorted(unknown)}; allowed: {sorted(ALLOWED_KEYS)}")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise PayloadError("'model' must be a non-empty string")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise PayloadError("'messages' must be a non-empty list")
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise PayloadError(f"messages[{i}] must be an object")
        if msg.get("role") not in ALLOWED_ROLES:
            raise PayloadError(f"messages[{i}].role must be one of {sorted(ALLOWED_ROLES)}")
        content = msg.get("content")
        if not isinstance(content, (str, list)):
            raise PayloadError(f"messages[{i}].content must be a string or a block list")
    if "system" in body and not isinstance(body["system"], (str, list)):
        raise PayloadError("'system' must be a string or a block list")
    if "tools" in body and not isinstance(body["tools"], list):
        raise PayloadError("'tools' must be a list")
    if "max_tokens" in body and not isinstance(body["max_tokens"], int):
        raise PayloadError("'max_tokens' must be an int")


class RouteClient:
    def __init__(self, base_url: str, router_key: str, timeout: float = 10.0, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {router_key}",
            "content-type": "application/json",
        })

    def health(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def route(self, body: dict) -> RouteDecision:
        """POST one request to /v1/route and return the parsed decision.

        Retries connection errors and 502/503 (the router's transient
        routing failures). 4xx is never retried: a bad key or bad body
        will not get better on a second attempt.
        """
        validate_payload(body)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                t0 = time.perf_counter()
                resp = self.session.post(f"{self.base_url}/v1/route", json=body, timeout=self.timeout)
                latency_ms = (time.perf_counter() - t0) * 1000.0
            except requests.RequestException as err:
                last_err = err
                time.sleep(0.25 * (attempt + 1))
                continue
            if resp.status_code in RETRYABLE_STATUS and attempt < self.retries:
                last_err = ContractError(f"router returned {resp.status_code}: {resp.text[:200]}")
                time.sleep(0.25 * (attempt + 1))
                continue
            return self._parse(resp, latency_ms)
        raise RouterUnavailable(f"{self.base_url} unreachable after {self.retries + 1} attempts: {last_err}")

    def _parse(self, resp: requests.Response, latency_ms: float) -> RouteDecision:
        if resp.status_code != 200:
            raise ContractError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as err:
            raise ContractError(f"non-JSON 200 response: {resp.text[:200]}") from err
        for key in ("model", "provider"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ContractError(f"decision missing or non-string '{key}': {data}")
        return RouteDecision(
            model=data["model"],
            provider=data["provider"],
            reason=str(data.get("reason", "")),
            status_code=resp.status_code,
            latency_ms=round(latency_ms, 2),
        )
