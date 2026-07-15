<?php
/**
 * Copy this file to config.php (gitignored) and fill in the values from
 * https://www.linkedin.com/developers/apps > your app > Auth tab.
 */

declare(strict_types=1);

define('LINKEDIN_CLIENT_ID', 'YOUR_CLIENT_ID');
define('LINKEDIN_CLIENT_SECRET', 'YOUR_CLIENT_SECRET');

// Must exactly match a Redirect URL configured on the LinkedIn app: absolute
// HTTPS URL, no query string, no #fragment — typically the URL this very
// file is deployed at, e.g. https://connect.ifuri.com/oauth/linkedin/index.php
define('LINKEDIN_REDIRECT_URI', 'https://example.com/path/to/index.php');

define('LINKEDIN_SCOPE', 'openid profile email w_member_social');
