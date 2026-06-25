# urirun-connector-linkedin

LinkedIn connector for [ifuri](https://ifuri.com) / [urirun](https://github.com/if-uri/urirun) — publish posts, read your profile, and list your feed over **LinkedIn's official REST API**, exposed as `linkedin://` URI routes.

This is the **sanctioned** write path: OAuth 2.0 access tokens with approved scopes, hitting `https://api.linkedin.com`. It does **not** use the login/password flow and does **not** drive a browser. If you came here looking for browser automation that logs into LinkedIn and clicks Publish — that's intentionally not this connector, and it never will be.

## Routes

| URI | effect | API |
| --- | --- | --- |
| `linkedin://host/profile/query/read` | read your lite profile (name, headline, member URN) | `GET /v2/me` |
| `linkedin://host/post/command/publish` | publish a text post (UGC Posts) | `POST /v2/ugcPosts` |
| `linkedin://host/post/query/list` | list your recent posts | `GET /v2/ugcPosts?q=authors` |

## Prerequisites

1. A **LinkedIn Developer application** — <https://www.linkedin.com/developers/apps/new>
2. Approved **scopes** on that app:
   - `r_liteprofile` (read profile)
   - `r_member_social` (list posts)
   - `w_member_social` (publish posts)
3. An **OAuth 2.0 access token** (60-day member access token, or a longer-lived refresh flow)
4. Your **member URN**, e.g. `urn:li:person:ABC123` — you can read it once via `profile/query/read` if you don't have it

## Setup

```bash
pip install urirun-connector-linkedin
export LINKEDIN_ACCESS_TOKEN="AQXx..."        # your OAuth token
export LINKEDIN_PERSON_URN="urn:li:person:ABC123"   # optional for read; required for clean writes
```

For secrets, use the urirun secrets layer (deny-by-default) instead of env vars:

```bash
# token resolved from a secret store by reference
urirun run registry.json --uri 'linkedin://host/post/command/publish' \
  --input '{"text":"hi","token":"secret://keyring/linkedin#token","person_urn":"secret://keyring/linkedin#person_urn"}' \
  --secret-allow 'secret://keyring/linkedin#token' \
  --secret-allow 'secret://keyring/linkedin#person_urn' \
  --execute
```

## Usage

### Publish a text post

```bash
urirun-connector-linkedin                                # emit bindings
urirun compile bindings.json --out registry.json
urirun run registry.json --uri 'linkedin://host/post/command/publish' \
  --input '{"text":"Shipping a thing today.","visibility":"PUBLIC"}' \
  --execute
```

Returns:

```json
{
  "ok": true,
  "action": "post_publish",
  "published": true,
  "post_urn": "urn:li:ugcPost:7",
  "author": "urn:li:person:ABC123",
  "visibility": "PUBLIC",
  "length": 23
}
```

`visibility` is one of `PUBLIC` (default) or `CONNECTIONS`. Text over 3000 characters is rejected by LinkedIn upstream.

### Read your profile (to discover your member URN)

```bash
urirun run registry.json --uri 'linkedin://host/profile/query/read' --input '{}' --execute
```

```json
{
  "ok": true,
  "action": "profile_read",
  "member_urn": "urn:li:person:ABC123",
  "first_name": "Tom",
  "last_name": "Sapletta",
  "headline": "ifURI"
}
```

### List your recent posts

```bash
urirun run registry.json --uri 'linkedin://host/post/query/list' \
  --input '{"count":10}' --execute
```

## Safety model

- **Credentials by reference.** `token`/`person_urn` accept `getv://ENV_VAR` or `secret://keyring/...#field` and are resolved through the urirun secrets layer. An unlisted secret raises `PermissionError` and the route returns `ok:false` without touching the network.
- **`--execute` gating.** Write routes (`post/command/publish`) only call the network when the registry runner is invoked with `--execute`. Without it, the binding compiles and validates but does not publish.
- **Missing credentials = fast fail.** With no token configured, every route returns `ok:false` immediately. No network attempt.
- **API errors surface verbatim.** A 401/403/422 from LinkedIn is mapped to `ok:false` with the upstream status and message — no silent retry, no swallow.

## Why this exists instead of a browser-publishing connector

LinkedIn's web UI is protected by anti-bot defenses (rotating DOM, CAPTCHA, device fingerprinting) and its Terms of Service forbid automated interactions with the live site. The only sanctioned programmatic write path is the official API, which is what this connector uses. If you need to *read* the live site (scout the feed, capture posts to markdown), use the read-only CDP scout in [`examples/39-local-social-autonomy`](../examples/39-local-social-autonomy/) — but the publish step stays this connector.

## Development

```bash
pip install -e '.[test]'
pytest tests/
```

13 tests, fully offline (mocks `urllib.request` — never calls the real LinkedIn API).

## License

Apache-2.0 — see [NOTICE](NOTICE).
