#!/usr/bin/env bash
# LinkedIn OAuth 2.0 Authorization Code flow helper for urirun-connector-linkedin.
#
# Opens your browser at LinkedIn's consent screen, catches the redirect on a
# short-lived local HTTP listener, exchanges the authorization code for an
# access token, and prints ready-to-export env vars. Nothing is written to
# disk and no secret is logged anywhere except your terminal.
#
# Prerequisites (see ../docs/oauth-setup.md):
#   - a LinkedIn Developer app with the "Sign In with LinkedIn using OpenID
#     Connect" and "Share on LinkedIn" products added
#   - that app's Auth tab has a Redirect URL matching LINKEDIN_REDIRECT_URI
#     below (default: http://localhost:8765/callback)
#
# Usage:
#   export LINKEDIN_CLIENT_ID='...'
#   export LINKEDIN_CLIENT_SECRET='...'
#   ./scripts/linkedin_oauth.sh
#
# Optional overrides:
#   LINKEDIN_REDIRECT_URI  (default: http://localhost:8765/callback)
#   LINKEDIN_SCOPE         (default: openid profile email w_member_social)

set -euo pipefail

CLIENT_ID="${LINKEDIN_CLIENT_ID:?export LINKEDIN_CLIENT_ID first (LinkedIn Developer Portal > your app > Auth)}"
CLIENT_SECRET="${LINKEDIN_CLIENT_SECRET:?export LINKEDIN_CLIENT_SECRET first (LinkedIn Developer Portal > your app > Auth)}"
REDIRECT_URI="${LINKEDIN_REDIRECT_URI:-http://localhost:8765/callback}"
SCOPE="${LINKEDIN_SCOPE:-openid profile email w_member_social}"
PYTHON="${PYTHON:-python3}"

command -v "$PYTHON" >/dev/null 2>&1 || { echo "error: $PYTHON not found" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "error: curl not found" >&2; exit 1; }

PORT="$("$PYTHON" -c "from urllib.parse import urlsplit; print(urlsplit('$REDIRECT_URI').port or 80)")"
STATE="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(16))')"

AUTH_URL="$("$PYTHON" - "$CLIENT_ID" "$REDIRECT_URI" "$STATE" "$SCOPE" <<'PYEOF'
import sys, urllib.parse
client_id, redirect_uri, state, scope = sys.argv[1:5]
params = {
    "response_type": "code",
    "client_id": client_id,
    "redirect_uri": redirect_uri,
    "state": state,
    "scope": scope,
}
print("https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params))
PYEOF
)"

echo "==> Open in your browser, log in, and click Allow:"
echo "    $AUTH_URL"
echo
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$AUTH_URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
  open "$AUTH_URL" >/dev/null 2>&1 &
fi

echo "==> Waiting for the redirect on $REDIRECT_URI (2 min timeout) ..."

CALLBACK_FILE="$(mktemp)"
trap 'rm -f "$CALLBACK_FILE"' EXIT

"$PYTHON" - "$PORT" "$STATE" "$CALLBACK_FILE" <<'PYEOF' &
import sys, http.server, urllib.parse

port, expected_state, out_path = int(sys.argv[1]), sys.argv[2], sys.argv[3]

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        error = params.get("error", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if error:
            self.wfile.write(f"<h1>LinkedIn denied access: {error}</h1>".encode())
            code = ""
        elif state != expected_state:
            self.wfile.write(b"<h1>state mismatch - possible CSRF, aborted</h1>")
            code = ""
        else:
            self.wfile.write(b"<h1>OK - you can close this tab and return to the terminal.</h1>")
        with open(out_path, "w") as f:
            f.write(code)

    def log_message(self, *a):
        pass

httpd = http.server.HTTPServer(("127.0.0.1", port), Handler)
httpd.timeout = 120
httpd.handle_request()
PYEOF
SERVER_PID=$!
wait "$SERVER_PID" 2>/dev/null || true

CODE="$(cat "$CALLBACK_FILE" 2>/dev/null || true)"
if [[ -z "$CODE" ]]; then
  echo "error: no authorization code received (timeout, denial, or state mismatch)" >&2
  echo "hint: if you're on a remote/headless box, localhost won't be reachable from your browser -" >&2
  echo "      use scripts/oauth-web/index.php on a real host instead (see ../docs/oauth-setup.md)" >&2
  exit 1
fi

echo "==> Got authorization code, exchanging it for an access token ..."
RESPONSE="$(curl -sS -X POST 'https://www.linkedin.com/oauth/v2/accessToken' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=authorization_code' \
  --data-urlencode "code=${CODE}" \
  --data-urlencode "client_id=${CLIENT_ID}" \
  --data-urlencode "client_secret=${CLIENT_SECRET}" \
  --data-urlencode "redirect_uri=${REDIRECT_URI}")"

ACCESS_TOKEN="$(echo "$RESPONSE" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')"
EXPIRES_IN="$(echo "$RESPONSE" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("expires_in",""))')"
REFRESH_TOKEN="$(echo "$RESPONSE" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("refresh_token",""))')"

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "error: token exchange failed" >&2
  echo "$RESPONSE" >&2
  exit 1
fi

echo
echo "==> Success. Token valid for ${EXPIRES_IN}s (~$((EXPIRES_IN / 86400)) days)."
echo
echo "export LINKEDIN_ACCESS_TOKEN='${ACCESS_TOKEN}'"
if [[ -n "$REFRESH_TOKEN" ]]; then
  echo "export LINKEDIN_REFRESH_TOKEN='${REFRESH_TOKEN}'"
fi
echo
echo "Next: run 'linkedin://host/profile/query/read' to confirm it works and discover your LINKEDIN_PERSON_URN."
echo "Do not commit this token or paste it anywhere outside your own shell."
