"""Regression tests for the async bot (bot_async.py).

These cover the paths that previously killed the long-running loop:
the string-shaped 409 error, unguarded retryAfter parsing, and
transport failures on action POST.
"""
import asyncio

import httpx
import pytest

import bot_async


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class FakeClient:
    """Minimal stand-in for httpx.AsyncClient."""

    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.calls = []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, timeout))
        return self.get_response

    async def post(self, url, content=None, headers=None, timeout=None):
        self.calls.append(("POST", url, timeout))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response


# --- error_code: both arena error shapes -------------------------------

def test_error_code_dict_shape():
    assert bot_async.error_code({"error": {"code": "arena_transaction_busy"}}) == "arena_transaction_busy"


def test_error_code_string_shape_does_not_crash():
    # This is the exact payload that used to raise AttributeError.
    assert bot_async.error_code(
        {"error": "action_conflict", "message": "A different action was already submitted"}
    ) == "action_conflict"


def test_error_code_missing_and_non_dict():
    assert bot_async.error_code({}) is None
    assert bot_async.error_code("boom") is None
    assert bot_async.error_code(None) is None


# --- retryAfter parsing ------------------------------------------------

@pytest.mark.parametrize("err,expected", [
    ({"retryAfter": 3}, 3),
    ({"retryAfter": "2"}, 2),
    ({"retryAfter": "1.5"}, 1),
    ({"retryAfter": None}, 1),
    ({"retryAfter": "2s"}, 1),
    ({}, 1),
    (None, 1),
    ("oops", 1),
])
def test_parse_retry_after_never_raises(err, expected):
    assert bot_async._parse_retry_after(err) == expected


# --- api() mapping -----------------------------------------------------

def test_api_get_json_ok():
    client = FakeClient(get_response=FakeResponse(200, '{"ok": true}'))
    status, body = asyncio.run(bot_async.api(client, "GET", "/x", "key"))
    assert status == 200
    assert body == {"ok": True}


def test_api_non_json_body():
    client = FakeClient(get_response=FakeResponse(502, "<html>bad gateway</html>"))
    status, body = asyncio.run(bot_async.api(client, "GET", "/x", "key"))
    assert status == 502
    assert body == {"error": "<html>bad gateway</html>"}


def test_api_timeout_maps_to_status_zero():
    client = FakeClient(post_response=httpx.TimeoutException("read timed out"))
    status, body = asyncio.run(bot_async.api(client, "POST", "/x", "key", {}))
    assert status == 0
    assert body == {"error": "timeout"}


def test_api_generic_exception_maps_to_status_zero():
    client = FakeClient(post_response=RuntimeError("socket exploded"))
    status, body = asyncio.run(bot_async.api(client, "POST", "/x", "key", {}))
    assert status == 0
    assert body["error"] == "socket exploded"


# --- validate_deck / load_creds ---------------------------------------

def test_validate_deck_accepts_live_deck():
    assert bot_async.validate_deck(bot_async.DECK) is True


def test_validate_deck_rejects_wrong_size():
    with pytest.raises(AssertionError):
        bot_async.validate_deck([1] * 59)


def test_validate_deck_rejects_copy_limit():
    deck = [625] * 5 + [1] * 55
    with pytest.raises(AssertionError):
        bot_async.validate_deck(deck)


def test_load_creds_missing_fields(tmp_path, monkeypatch):
    bad = tmp_path / "creds.json"
    bad.write_text('{"apiKey": "x"}')
    monkeypatch.setattr(bot_async, "CREDS_PATH", bad)
    with pytest.raises(SystemExit):
        bot_async.load_creds()


# --- post_action retry contract ---------------------------------------

def test_post_action_action_conflict_returns_immediately(monkeypatch):
    calls = []

    async def fake_api(client, method, path, api_key=None, body=None, timeout=30):
        calls.append(body)
        return 409, {"error": "action_conflict", "message": "already submitted"}

    monkeypatch.setattr(bot_async, "api", fake_api)
    status, resp = asyncio.run(
        bot_async.post_action(None, "key", "match-1", 3, "[0]", timeout=5)
    )
    assert status == 409
    assert resp["error"] == "action_conflict"
    assert len(calls) == 1  # must not retry a duplicate submission


def test_post_action_retries_transport_failure(monkeypatch):
    responses = [(0, {"error": "timeout"}), (200, {"idempotent": False})]
    calls = []

    async def fake_api(client, method, path, api_key=None, body=None, timeout=30):
        calls.append(body)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(bot_async, "api", fake_api)
    status, resp = asyncio.run(
        bot_async.post_action(None, "key", "match-2", 4, "[1]", timeout=5)
    )
    assert status == 200
    assert len(calls) == 2


def test_post_action_gives_up_after_budget(monkeypatch):
    calls = []

    async def fake_api(client, method, path, api_key=None, body=None, timeout=30):
        calls.append(body)
        return 0, {"error": "timeout"}

    monkeypatch.setattr(bot_async, "api", fake_api)
    status, resp = asyncio.run(
        bot_async.post_action(None, "key", "match-3", 5, "[0]", timeout=2)
    )
    assert status == 0
    assert 1 <= len(calls) <= 4


def test_post_action_retries_busy_without_crashing(monkeypatch):
    responses = [
        (409, {"error": {"code": "arena_transaction_busy", "retryAfter": "oops"}}),
        (200, {"idempotent": True}),
    ]
    calls = []

    async def fake_api(client, method, path, api_key=None, body=None, timeout=30):
        calls.append(body)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(bot_async, "api", fake_api)
    status, resp = asyncio.run(
        bot_async.post_action(None, "key", "match-4", 6, "[0]", timeout=5)
    )
    assert status == 200
    assert len(calls) == 2
