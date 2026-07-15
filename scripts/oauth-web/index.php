<?php
/**
 * LinkedIn OAuth 2.0 (Authorization Code flow) landing + callback for
 * urirun-connector-linkedin.
 *
 * Use this instead of scripts/linkedin_oauth.sh when http://localhost isn't
 * reachable from the browser doing the LinkedIn login (e.g. running the
 * connector on a remote/headless box). Deploy this file behind HTTPS on a
 * host you control, point the LinkedIn app's Redirect URL at it, and open it
 * in a browser.
 *
 * Setup:
 *   1. cp config.sample.php config.php   (config.php is gitignored — never commit it)
 *   2. Fill in LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET / LINKEDIN_REDIRECT_URI
 *      in config.php. LINKEDIN_REDIRECT_URI must be the exact HTTPS URL this
 *      file will be served at (no query string, no #fragment).
 *   3. Deploy this directory behind HTTPS.
 *   4. In the LinkedIn Developer Portal (https://www.linkedin.com/developers/apps)
 *      > your app > Auth tab, add that same URL as a Redirect URL.
 *   5. Visit the deployed URL, click "Connect LinkedIn", approve, and copy
 *      the printed `export LINKEDIN_ACCESS_TOKEN=...` line into your shell.
 *
 * This script holds the token only for the duration of the HTTP response —
 * it is never written to disk, logged, or stored server-side.
 */

declare(strict_types=1);

session_start();

$configFile = __DIR__ . '/config.php';
if (!is_file($configFile)) {
    http_response_code(500);
    die('Missing config.php — copy config.sample.php to config.php and fill in your LinkedIn app credentials.');
}
require $configFile; // defines LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI, LINKEDIN_SCOPE

foreach (['LINKEDIN_CLIENT_ID', 'LINKEDIN_CLIENT_SECRET', 'LINKEDIN_REDIRECT_URI', 'LINKEDIN_SCOPE'] as $const) {
    if (!defined($const)) {
        http_response_code(500);
        die("config.php is missing the {$const} constant.");
    }
}

function h(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
}

function linkedin_authorize_url(string $state): string
{
    $params = [
        'response_type' => 'code',
        'client_id' => LINKEDIN_CLIENT_ID,
        'redirect_uri' => LINKEDIN_REDIRECT_URI,
        'state' => $state,
        'scope' => LINKEDIN_SCOPE,
    ];
    return 'https://www.linkedin.com/oauth/v2/authorization?' . http_build_query($params);
}

/** @return array{access_token:string,expires_in:int,refresh_token:?string} */
function linkedin_exchange_code(string $code): array
{
    $ch = curl_init('https://www.linkedin.com/oauth/v2/accessToken');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
        CURLOPT_POSTFIELDS => http_build_query([
            'grant_type' => 'authorization_code',
            'code' => $code,
            'client_id' => LINKEDIN_CLIENT_ID,
            'client_secret' => LINKEDIN_CLIENT_SECRET,
            'redirect_uri' => LINKEDIN_REDIRECT_URI,
        ]),
    ]);
    $body = curl_exec($ch);
    if ($body === false) {
        $err = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException('curl error: ' . $err);
    }
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $data = json_decode((string) $body, true);
    if (!is_array($data) || $status !== 200) {
        throw new RuntimeException("LinkedIn token exchange failed (HTTP {$status}): {$body}");
    }
    return $data;
}

// --- LinkedIn reported an error (user declined, bad scope, ...) -------------
if (isset($_GET['error'])) {
    http_response_code(400);
    echo '<h1>LinkedIn declined the request</h1><p>'
        . h((string) $_GET['error']) . ': ' . h((string) ($_GET['error_description'] ?? ''))
        . '</p>';
    exit;
}

// --- callback leg: exchange the authorization code for a token --------------
if (isset($_GET['code'])) {
    $state = (string) ($_GET['state'] ?? '');
    if (!isset($_SESSION['li_oauth_state']) || !hash_equals((string) $_SESSION['li_oauth_state'], $state)) {
        http_response_code(400);
        die('state mismatch — possible CSRF, aborted. Start over from this page\'s landing screen.');
    }
    unset($_SESSION['li_oauth_state']);

    try {
        $token = linkedin_exchange_code((string) $_GET['code']);
    } catch (Throwable $e) {
        http_response_code(502);
        die('Token exchange failed: ' . h($e->getMessage()));
    }

    $accessToken = (string) ($token['access_token'] ?? '');
    $expiresIn = (int) ($token['expires_in'] ?? 0);
    $refreshToken = (string) ($token['refresh_token'] ?? '');
    ?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>LinkedIn token</title></head>
<body style="font-family:ui-monospace,monospace;max-width:48rem;margin:2rem auto;line-height:1.5">
  <h1>Done</h1>
  <p>Token valid for <?= $expiresIn ?> s (~<?= round($expiresIn / 86400) ?> days).</p>
  <p><strong>Copy and run this in your own shell</strong> — do not leave this tab open longer than necessary:</p>
  <pre style="background:#f4f4f4;padding:1rem;overflow-x:auto">export LINKEDIN_ACCESS_TOKEN='<?= h($accessToken) ?>'<?php if ($refreshToken !== ''): ?>

export LINKEDIN_REFRESH_TOKEN='<?= h($refreshToken) ?>'<?php endif; ?></pre>
  <p style="color:#900">This page does not persist the token anywhere — it exists only in this response. Close the tab after copying it, and never commit it or paste it into chat/tickets.</p>
</body></html>
    <?php
    exit;
}

// --- landing leg: start the flow ---------------------------------------------
$state = bin2hex(random_bytes(16));
$_SESSION['li_oauth_state'] = $state;
$authUrl = linkedin_authorize_url($state);
?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Connect LinkedIn — urirun-connector-linkedin</title></head>
<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:5rem auto;text-align:center">
  <h1>urirun-connector-linkedin</h1>
  <p>Click below to sign in to LinkedIn and grant this app access.</p>
  <p><a href="<?= h($authUrl) ?>"
        style="display:inline-block;padding:.75rem 1.5rem;background:#0a66c2;color:#fff;
               border-radius:.4rem;text-decoration:none;font-weight:600">Connect LinkedIn</a></p>
  <p style="color:#666;font-size:.9rem">Scope requested: <?= h(LINKEDIN_SCOPE) ?></p>
</body></html>
