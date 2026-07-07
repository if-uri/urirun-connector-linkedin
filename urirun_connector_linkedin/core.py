# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

"""LinkedIn connector for urirun — official REST API over linkedin:// routes.

This connector talks ONLY to the official LinkedIn REST API
(``https://api.linkedin.com``) using an OAuth 2.0 access token with approved
scopes (``r_liteprofile``, ``r_member_social``, ``w_member_social``). It never
uses the login/password flow and never drives a browser — that's the whole
point: a sanctioned, ToS-compliant write path instead of CDP/KVM automation.

Routes match the connect.ifuri.com contract:

* ``linkedin://me/profile/query/read``   -- read your own profile (lite)
* ``linkedin://me/post/command/publish`` -- publish a text post (UGC Posts API)
* ``linkedin://me/post/query/list``      -- list your recent posts

Credentials are addressed by reference and resolved through the urirun secrets
layer (deny-by-default):

* ``token``        -> ``getv://LINKEDIN_ACCESS_TOKEN`` or
                      ``secret://keyring/linkedin#token``
* ``person_urn``   -> ``getv://LINKEDIN_PERSON_URN`` or
                      ``secret://keyring/linkedin#person_urn``

An empty ``token``/``person_urn`` falls back to the ``LINKEDIN_ACCESS_TOKEN`` /
``LINKEDIN_PERSON_URN`` env vars so existing setups keep working.

Write routes (``post/command/publish``) are gated by urirun's ``--execute`` on
the registry runner — without it the binding refuses to call the network.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import urirun

CONNECTOR_ID = "linkedin"
conn = urirun.connector(CONNECTOR_ID, scheme="linkedin")

try:  # Optional contract runtime guard; absent toolkit must not break standalone connector import.
    from urirun_connectors_toolkit.contract_gate import enforce as _enforce
    from urirun_connector_linkedin.contracts import CONTRACTS as _CONTRACTS_EARLY

    _enforce(conn, _CONTRACTS_EARLY,
             validate=os.environ.get("URIRUN_CONTRACT_CHECK") == "1")
    del _CONTRACTS_EARLY
except Exception:  # noqa: BLE001 - contracts are CI/planner enrichment, not a hard runtime dependency
    pass

API_BASE = "https://api.linkedin.com"
_resolve_secret = urirun.resolve_secret


# --- credential resolution ---------------------------------------------------

def _creds(
    token: str = "",
    person_urn: str = "",
    secret_allow: str = "",
) -> dict[str, str] | None:
    """Resolve the access token + member URN through the secrets layer.

    Returns ``None`` when no token is configured, so the caller can return a
    fast ``ok: false`` without touching the network.
    """
    try:
        tok = _resolve_secret(token, secret_allow) or os.getenv("LINKEDIN_ACCESS_TOKEN", "")
        urn = _resolve_secret(person_urn, secret_allow) or os.getenv("LINKEDIN_PERSON_URN", "")
    except PermissionError as exc:
        raise PermissionError(
            f"credential denied by policy (add it to secret_allow): {exc}"
        ) from exc
    if not tok:
        return None
    return {"token": tok, "person_urn": urn}


def _missing_creds_result(action: str):
    return urirun.fail(
        "set LINKEDIN_ACCESS_TOKEN (and LINKEDIN_PERSON_URN for writes) "
        "to use the LinkedIn API",
        connector=CONNECTOR_ID, action=action,
    )


# --- low-level API client ----------------------------------------------------

class _LinkedInError(RuntimeError):
    def __init__(self, status: int, message: str, body: str = "") -> None:
        super().__init__(f"LinkedIn API {status}: {message}" + (f"\n{body}" if body else ""))
        self.status = status
        self.message = message
        self.body = body


def _api(
    method: str,
    path: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    version_header: str = "2",
) -> Any:
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": version_header,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        message = exc.reason or "HTTP error"
        try:
            parsed = json.loads(err_body) if err_body else {}
            if isinstance(parsed, dict):
                fields = parsed.get("fields") or parsed.get("message")
                if isinstance(fields, dict):
                    message = "; ".join(f"{k}={v}" for k, v in fields.items()) or message
                elif isinstance(fields, str) and fields:
                    message = fields
        except (ValueError, TypeError):
            pass
        raise _LinkedInError(exc.code, message, err_body) from exc


def _resolve_person_urn(token: str, fallback_urn: str) -> str:
    """Use the explicit URN when given; otherwise resolve it from /v2/me.

    The publish endpoint requires the author URN up front, so when the caller
    didn't supply one we read the lite profile once to fetch it.
    """
    if fallback_urn:
        return fallback_urn
    profile = _api("GET", "/v2/me?projection=(id)", token)
    member_id = str(profile.get("id", "")).strip()
    if not member_id:
        raise _LinkedInError(400, "could not resolve member URN from /v2/me")
    return f"urn:li:person:{member_id}"


# --- routes ------------------------------------------------------------------

@conn.handler("profile/query/read", isolated=True,
              meta={"label": "Read your LinkedIn profile (lite)"})
def profile_read(token: str = "", secret_allow: str = "") -> dict[str, Any]:
    """Read ``r_liteprofile`` fields: localized first/last name, headline, and
    the member URN you'll need as ``LINKEDIN_PERSON_URN`` for publishes."""
    try:
        creds = _creds(token=token, secret_allow=secret_allow)
    except PermissionError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="profile_read")
    if not creds:
        return _missing_creds_result("profile_read")
    try:
        data = _api(
            "GET",
            "/v2/me?projection=(id,localizedFirstName,localizedLastName,localizedHeadline,"
            "profilePicture(displayImage~:playableStreams))",
            creds["token"],
        )
    except _LinkedInError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="profile_read",
                           status=exc.status)
    member_id = str(data.get("id", "")).strip()
    return urirun.ok(
        connector=CONNECTOR_ID, action="profile_read",
        member_urn=f"urn:li:person:{member_id}" if member_id else "",
        first_name=data.get("localizedFirstName", ""),
        last_name=data.get("localizedLastName", ""),
        headline=data.get("localizedHeadline", ""),
        raw=data,
    )


@conn.handler("post/command/publish", isolated=True,
              meta={"label": "Publish a text post to LinkedIn (UGC Posts API)"})
def post_publish(
    text: str = "",
    token: str = "",
    person_urn: str = "",
    visibility: str = "PUBLIC",
    secret_allow: str = "",
) -> dict[str, Any]:
    """Publish a text post via the UGC Posts endpoint (``POST /v2/ugcPosts``).

    ``visibility`` is one of ``PUBLIC`` or ``CONNECTIONS`` (the two values
    LinkedIn's API accepts for member-authored UGC). Returns the UGC post URN
    on success.
    """
    if not text:
        return urirun.fail("text is required", connector=CONNECTOR_ID, action="post_publish")
    if visibility not in {"PUBLIC", "CONNECTIONS"}:
        return urirun.fail(
            f"visibility must be PUBLIC or CONNECTIONS, got: {visibility}",
            connector=CONNECTOR_ID, action="post_publish",
        )
    try:
        creds = _creds(token=token, person_urn=person_urn, secret_allow=secret_allow)
    except PermissionError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="post_publish")
    if not creds:
        return _missing_creds_result("post_publish")
    try:
        author = _resolve_person_urn(creds["token"], creds["person_urn"])
        payload = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        result = _api("POST", "/v2/ugcPosts", creds["token"], body=payload)
    except _LinkedInError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="post_publish",
                           status=exc.status)
    # LinkedIn returns 201 with a JSON body containing the new URN.
    post_urn = ""
    if isinstance(result, dict):
        post_urn = str(result.get("id") or result.get("urn") or "")
    return urirun.ok(
        connector=CONNECTOR_ID, action="post_publish",
        published=True, post_urn=post_urn, author=author, visibility=visibility,
        length=len(text),
    )


@conn.handler("post/query/list", isolated=True,
              meta={"label": "List your recent LinkedIn posts"})
def post_list(
    token: str = "",
    person_urn: str = "",
    count: int = 10,
    secret_allow: str = "",
) -> dict[str, Any]:
    """List your recent UGC posts (``GET /v2/ugcPosts?q=authors``).

    Requires the ``r_member_social`` scope. ``count`` is capped to 1..50 per
    LinkedIn's pagination limits.
    """
    count = max(1, min(50, int(count)))
    try:
        creds = _creds(token=token, person_urn=person_urn, secret_allow=secret_allow)
    except PermissionError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="post_list")
    if not creds:
        return _missing_creds_result("post_list")
    try:
        author = _resolve_person_urn(creds["token"], creds["person_urn"])
        path = f"/v2/ugcPosts?q=authors&authors={urllib.parse.quote(author)}&count={count}"
        data = _api("GET", path, creds["token"])
    except _LinkedInError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="post_list",
                           status=exc.status)
    elements = data.get("elements", []) if isinstance(data, dict) else []
    posts: list[dict[str, Any]] = []
    for el in elements:
        share = (el.get("specificContent") or {}).get("com.linkedin.ugc.ShareContent", {})
        text = (share.get("shareCommentary") or {}).get("text", "")
        posts.append({
            "urn": el.get("id", ""),
            "text": text,
            "lifecycleState": el.get("lifecycleState", ""),
            "created": el.get("created", {}).get("time", "") if isinstance(el.get("created"), dict) else "",
        })
    return urirun.ok(
        connector=CONNECTOR_ID, action="post_list",
        count=len(posts), posts=posts, author=author,
    )


POST_MAX_CHARS = 3000  # LinkedIn's per-post character limit for member UGC


@conn.handler("post/command/draft", isolated=True,
              meta={"label": "Prepare a LinkedIn post draft locally (no network, no creds)"})
def post_draft(text: str = "", visibility: str = "PUBLIC") -> dict[str, Any]:
    """Prepare a post draft WITHOUT publishing — pure, local, credential-free.

    The real publish path needs an OAuth token, but "draft only, no publication"
    tasks do not. This validates the copy, counts length against LinkedIn's
    3000-char limit, extracts hashtags, and returns ``published:false`` — giving
    the autonomy loop a credential-free deliverable instead of escalating for
    creds it does not need. Touches no network.
    """
    if not text:
        return urirun.fail("text is required", connector=CONNECTOR_ID, action="post_draft")
    if visibility not in {"PUBLIC", "CONNECTIONS"}:
        return urirun.fail(
            f"visibility must be PUBLIC or CONNECTIONS, got: {visibility}",
            connector=CONNECTOR_ID, action="post_draft",
        )
    length = len(text)
    hashtags = list(dict.fromkeys(re.findall(r"#\w+", text)))
    return urirun.ok(
        connector=CONNECTOR_ID, action="post_draft",
        published=False, visibility=visibility, length=length,
        remaining=POST_MAX_CHARS - length, over_limit=length > POST_MAX_CHARS,
        hashtags=hashtags, preview=text,
    )


# Join route contracts onto the live bindings by route key so planners and MCP/A2A projections see
# the declared output shape. Standalone installs without the contract toolkit keep working.
try:
    from urirun_connectors_toolkit.contract_gate import attach_contracts as _attach_contracts
    from urirun_connector_linkedin.contracts import CONTRACTS as _CONTRACTS

    _attach_contracts(conn, _CONTRACTS)
except Exception:  # noqa: BLE001 - enrichment only
    pass


# --- authoring surface -------------------------------------------------------

def urirun_bindings() -> dict[str, Any]:
    return conn.bindings()


def connector_manifest() -> dict[str, Any]:
    return conn.manifest(urirun.load_manifest(__package__))


def main(argv: list[str] | None = None) -> int:
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    raise SystemExit(main())
