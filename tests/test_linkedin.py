# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

import urirun_connector_linkedin as li
import urirun_connector_linkedin.core as core

ROUTE_READ = "linkedin://host/profile/query/read"
ROUTE_PUBLISH = "linkedin://host/post/command/publish"
ROUTE_LIST = "linkedin://host/post/query/list"


# --- draft (credential-free, no network) -------------------------------------

def test_post_draft_prepares_without_network_or_creds() -> None:
    """IFURI-060/062: draft path must never touch the network or need a token."""
    with patch("urllib.request.urlopen", side_effect=AssertionError("draft must not call the API")):
        r = core.post_draft(text="Shipping #ifuri today. #mcp")
    assert r["ok"] is True
    assert r["published"] is False
    assert r["length"] == 27
    assert r["remaining"] == 3000 - 27
    assert r["over_limit"] is False
    assert r["hashtags"] == ["#ifuri", "#mcp"]
    assert r["preview"] == "Shipping #ifuri today. #mcp"


def test_post_draft_requires_text() -> None:
    r = core.post_draft(text="")
    assert r["ok"] is False


def test_post_draft_flags_over_limit() -> None:
    r = core.post_draft(text="x" * 3200)
    assert r["ok"] is True and r["over_limit"] is True and r["remaining"] < 0


def test_post_draft_rejects_bad_visibility() -> None:
    r = core.post_draft(text="hi", visibility="SECRET")
    assert r["ok"] is False


# --- helpers -----------------------------------------------------------------

class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, reason: str = "OK",
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.status = status
        self.reason = reason
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _ok_json(payload: dict[str, Any], headers: dict[str, str] | None = None) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"), headers=headers)


def _http_error(status: int, reason: str, body: dict[str, Any]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.linkedin.com/x",
        code=status,
        msg=reason,
        hdrs=None,
        fp=io.BytesIO(json.dumps(body).encode("utf-8")),
    )


def _captured_request() -> dict[str, Any]:
    """Records what the connector passed to urllib.request.Request."""
    captured: dict[str, Any] = {}

    class _Req:
        def __init__(self, url, data=None, headers=None, method="GET"):
            captured["url"] = url
            captured["method"] = method
            captured["data"] = data
            captured["headers"] = headers or {}

    return captured, _Req


# --- binding document + manifest ---------------------------------------------

def test_bindings_document_has_three_routes():
    doc = li.urirun_bindings()
    bindings = doc["bindings"] if "bindings" in doc else doc
    uris = list(bindings.keys())
    assert ROUTE_READ in uris
    assert ROUTE_PUBLISH in uris
    assert ROUTE_LIST in uris


def test_publish_binding_is_command_and_requires_execute():
    doc = li.urirun_bindings()
    bindings = doc["bindings"] if "bindings" in doc else doc
    pub = bindings[ROUTE_PUBLISH]
    # connector exposes it as a local-function route; the gating that matters
    # is the runtime's --execute flag, not a per-route autoExecute toggle.
    assert pub["kind"] == "local-function"
    policy = pub.get("policy", {})
    assert policy.get("autoExecute") is not True


def test_connector_manifest_reports_official_api_scheme():
    manifest = li.connector_manifest()
    assert manifest["id"] == "linkedin"
    assert "linkedin" in manifest.get("uriSchemes", [])
    assert "Social" in manifest.get("category", "")


# --- missing credentials: must NOT hit the network --------------------------

def test_profile_read_without_token_returns_fail_and_does_not_call_network(monkeypatch):
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINKEDIN_PERSON_URN", raising=False)
    called = {"n": 0}

    def boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not reach the network without a token")

    monkeypatch.setattr(core.urllib.request, "urlopen", boom)
    result = li.profile_read(token="", secret_allow="")
    assert result["ok"] is False
    assert "LINKEDIN_ACCESS_TOKEN" in result["error"]
    assert called["n"] == 0


# --- profile_read happy path -------------------------------------------------

def test_profile_read_returns_member_urn_and_names(monkeypatch):
    captured, _Req = _captured_request()
    monkeypatch.setattr(core.urllib.request, "Request", _Req)
    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda req, timeout=30: _ok_json({
                            "sub": "ABC123",
                            "given_name": "Tom",
                            "family_name": "Sapletta",
                            "name": "Tom Sapletta",
                            "email": "tom@example.com",
                        }))
    result = li.profile_read(token="tok-123", secret_allow="")
    assert result["ok"] is True
    assert result["member_urn"] == "urn:li:person:ABC123"
    assert result["first_name"] == "Tom"
    assert result["last_name"] == "Sapletta"
    assert result["full_name"] == "Tom Sapletta"
    assert result["email"] == "tom@example.com"
    assert "Bearer tok-123" == captured["headers"]["Authorization"]
    assert "/v2/userinfo" in captured["url"]


# --- publish -----------------------------------------------------------------

def test_post_publish_requires_text():
    result = li.post_publish(text="", token="tok", person_urn="urn:li:person:X")
    assert result["ok"] is False
    assert "text is required" in result["error"]


def test_post_publish_rejects_invalid_visibility():
    result = li.post_publish(text="hi", visibility="FOLOWERS",
                             token="tok", person_urn="urn:li:person:X")
    assert result["ok"] is False
    assert "PUBLIC or CONNECTIONS" in result["error"]


def test_post_publish_happy_path_posts_rest_posts(monkeypatch):
    captured, _Req = _captured_request()
    monkeypatch.setattr(core.urllib.request, "Request", _Req)
    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda req, timeout=30: _FakeResponse(
                            b"{}", status=201, reason="Created",
                            headers={"x-restli-id": "urn:li:share:7"}))
    result = li.post_publish(
        text="Shipping a thing today.",
        token="tok-abc",
        person_urn="urn:li:person:ABC",
        visibility="PUBLIC",
    )
    assert result["ok"] is True
    assert result["published"] is True
    assert result["post_urn"] == "urn:li:share:7"
    assert result["author"] == "urn:li:person:ABC"
    assert result["visibility"] == "PUBLIC"
    # payload is the Posts API request body
    sent = json.loads(captured["data"])
    assert sent["author"] == "urn:li:person:ABC"
    assert sent["lifecycleState"] == "PUBLISHED"
    assert sent["commentary"] == "Shipping a thing today."
    assert sent["visibility"] == "PUBLIC"
    assert sent["distribution"]["feedDistribution"] == "MAIN_FEED"
    assert captured["url"].endswith("/rest/posts")
    assert captured["method"] == "POST"
    assert captured["headers"]["LinkedIn-Version"] == core.LINKEDIN_API_VERSION


def test_post_publish_resolves_urn_from_userinfo_when_not_supplied(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(req, timeout=30):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/v2/userinfo" in url:
            calls.append("userinfo")
            return _ok_json({"sub": "FROM_USERINFO"})
        calls.append("posts")
        return _FakeResponse(b"{}", status=201, reason="Created",
                             headers={"x-restli-id": "urn:li:share:1"})

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    result = li.post_publish(text="hi", token="tok", person_urn="")
    assert result["ok"] is True
    assert result["author"] == "urn:li:person:FROM_USERINFO"
    assert calls == ["userinfo", "posts"]


def test_post_publish_maps_api_error_to_fail(monkeypatch):
    def boom(req, timeout=30):
        raise _http_error(401, "Unauthorized", {
            "message": "Invalid access token",
            "status": 401,
        })
    monkeypatch.setattr(core.urllib.request, "urlopen", boom)
    result = li.post_publish(text="hi", token="bad", person_urn="urn:li:person:X")
    assert result["ok"] is False
    assert result["status"] == 401
    assert "Invalid access token" in result["error"]


# --- post_list ---------------------------------------------------------------

def test_post_list_returns_parsed_posts(monkeypatch):
    captured, _Req = _captured_request()
    monkeypatch.setattr(core.urllib.request, "Request", _Req)
    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda req, timeout=30: _ok_json({
                            "elements": [
                                {"id": "urn:li:share:1",
                                 "lifecycleState": "PUBLISHED",
                                 "createdAt": 1750672800000,
                                 "commentary": "post A"},
                                {"id": "urn:li:share:2",
                                 "lifecycleState": "PUBLISHED",
                                 "createdAt": 1750669200000,
                                 "commentary": "post B"},
                            ]}))
    result = li.post_list(token="tok", person_urn="urn:li:person:ABC", count=5)
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["posts"][0]["text"] == "post A"
    assert result["posts"][0]["created"] == 1750672800000
    # count is capped and author is URL-encoded
    assert "count=5" in captured["url"]
    assert "author=urn%3Ali%3Aperson%3AABC" in captured["url"]
    assert captured["headers"]["X-RestLi-Method"] == "FINDER"


def test_post_list_caps_count_to_50(monkeypatch):
    captured, _Req = _captured_request()
    monkeypatch.setattr(core.urllib.request, "Request", _Req)
    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda req, timeout=30: _ok_json({"elements": []}))
    li.post_list(token="tok", person_urn="urn:li:person:X", count=99999)
    assert "count=50" in captured["url"]


# --- credential resolution via secrets layer ---------------------------------

def test_post_publish_denies_secret_without_allow(monkeypatch):
    # resolve_secret raises PermissionError when the referenced secret is not
    # in secret_allow; the route must surface that as ok:false, not crash.
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    def deny(_value, allow):
        raise PermissionError("not allowed")
    monkeypatch.setattr(core, "_resolve_secret", deny)
    result = li.post_publish(text="hi", token="secret://keyring/linkedin#token", secret_allow="")
    assert result["ok"] is False
    assert "denied by policy" in result["error"]
