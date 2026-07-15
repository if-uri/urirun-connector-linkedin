# LinkedIn OAuth setup

How to create a LinkedIn Developer app and get an access token for
`urirun-connector-linkedin`. Two paths are provided for the token exchange —
pick whichever fits where you're running from.

## 1. Create the LinkedIn Developer app

1. Go to <https://www.linkedin.com/developers/apps/new>.
2. Fill in the form:
   - **App name** — anything, e.g. `urirun-linkedin`
   - **LinkedIn Page** — LinkedIn requires every app to be linked to a
     Company Page. If you don't have one, create a minimal one first
     (LinkedIn → *Create a Company Page*).
   - **App logo** — any image satisfies the requirement.
3. Open the **Products** tab on the new app and request both (self-serve,
   approved instantly):
   - **Sign In with LinkedIn using OpenID Connect** → grants `openid profile email`
   - **Share on LinkedIn** → grants `w_member_social`
4. Open the **Auth** tab and note:
   - **Client ID**
   - **Client Secret** (treat like a password — never commit it, never paste it in chat)
   - Add a **Redirect URL** matching whichever token-exchange path you use below.

> `r_member_social` (needed for `linkedin://host/post/query/list`, listing
> your own posts) is restricted to LinkedIn-approved partners — self-serve
> apps almost never get it. `profile/query/read` and `post/command/publish`
> work fine without it.

## 2. Get an access token

Both paths implement the same [3-legged OAuth 2.0 Authorization Code
flow](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow):
redirect the browser to LinkedIn's consent screen → LinkedIn redirects back
with a `code` → exchange that code for an `access_token` server-side (the
`client_secret` never touches the browser).

### Path A — shell script (local machine, browser reachable at `localhost`)

Use this when you're running the connector on the same machine as the
browser you'll approve access from.

```bash
# In the LinkedIn app's Auth tab, add this exact Redirect URL:
#   http://localhost:8765/callback

export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
./scripts/linkedin_oauth.sh
```

It opens your browser at the LinkedIn consent screen, runs a short-lived
local HTTP listener to catch the redirect, exchanges the code for a token via
`curl`, and prints:

```
export LINKEDIN_ACCESS_TOKEN='AQXx...'
export LINKEDIN_REFRESH_TOKEN='AQXx...'   # if the app has refresh tokens enabled
```

Nothing is written to disk. Requires `python3` (used only for URL
encoding/decoding and the local callback listener) and `curl`.

### Path B — `index.php` (remote/headless box, or you'd rather use a stable HTTPS URL)

Use this when the machine running the connector isn't the machine with the
browser (a remote server, a headless dev box, CI), so `localhost` in the
redirect URL wouldn't be reachable.

```bash
cd scripts/oauth-web
cp config.sample.php config.php
# edit config.php: LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI
```

Deploy `index.php` + `config.php` behind HTTPS on a host you control — e.g.
`https://connect.ifuri.com/oauth/linkedin/index.php`. Set
`LINKEDIN_REDIRECT_URI` in `config.php` to that exact URL (no query string,
no `#fragment`), and add the same URL as a Redirect URL in the LinkedIn app's
Auth tab.

Open the deployed URL in a browser, click **Connect LinkedIn**, approve, and
copy the `export LINKEDIN_ACCESS_TOKEN=...` line it prints into your shell.

`config.php` is gitignored — never commit it, since it holds the client
secret. The page holds the token only for the duration of that one HTTP
response; it isn't logged or written to disk anywhere.

## 3. Use the token

For quick local testing:

```bash
export LINKEDIN_PERSON_URN=""   # optional; profile_read derives it for you
urirun-connector-linkedin                                 # emit bindings
urirun compile bindings.json --out registry.json
urirun run registry.json --uri 'linkedin://host/profile/query/read' --input '{}' --execute
```

For anything beyond ad-hoc testing, route the token through urirun's secrets
layer instead of a bare env var — see the "Safety model" section in the
[README](../README.md#safety-model).

## 4. Token lifetime

- Access tokens last **60 days**.
- Refresh tokens (if issued) last **365 days**, but programmatic refresh is
  only enabled for a limited set of partners — most self-serve apps need to
  re-run the flow above when the access token expires.
- Requesting a different `scope` than a previously granted one invalidates
  all previously issued tokens for that app+member pair.

## Why not the old `r_liteprofile` / `w_member_social` setup?

If you've seen older LinkedIn integration guides referencing `GET /v2/me` or
`POST /v2/ugcPosts` with `r_liteprofile`/`r_member_social`/`w_member_social`
scopes granted directly (no OIDC product) — that surface is retired for new
apps. This connector (since the OIDC/Posts-API migration) only targets the
current surfaces: `GET /v2/userinfo` for identity and `POST /rest/posts` for
publishing, both documented above.
