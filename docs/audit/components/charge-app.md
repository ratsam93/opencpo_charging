# opencpo-charge-app (commit 9f5c2e4)

## Works (TESTED, mock core)
- Home and charger pages boot for `default` and all five skins; `/skin/style.css` served (19-20 KB). `manifest.json`, both icons and `sw.js` return 200.
- Unknown `SKIN` does not crash.

## Broken or weak
| Finding | Evidence |
|---|---|
| **Header `X-Client-Cert-Serial` is trusted from any client**: attacker gets a device cookie and the victim's profile | TESTED |
| **No ownership check on session routes**: with only a session ID, poll/receipt/PDF/stop/cancel all succeed and reach core | TESTED |
| Management API key sent to core on anonymous calls | TESTED |
| Stop route returns core's raw error text to the browser | TESTED |
| Auth cookie has no `Secure` flag (`COOKIE_SECURE` defaults off); no CSP/HSTS/X-Frame-Options/nosniff | TESTED |
| Service worker registered at `/static/sw.js` -> scope `/static/`, offline recovery cannot work; no `Service-Worker-Allowed` | TESTED |
| Unknown `SKIN` silently 404s the CSS | TESTED |
| No `/health`, no Dockerfile healthcheck; port 8003 hardcoded, `PORT` ignored; `PUBLIC_URL` unused | TESTED |
| Payment is not implemented here (display string `EUR 25` only) | CODE |
| QR scanning needs `BarcodeDetector` (no iOS Safari / Firefox) | CODE |
| `stitch-to-skin.py` lives in `tools/`; website command fails from repo root; no compose file in repo | CODE |
| No tests | repo |

## Not tested
Cookie replay on full flows, JWT forgery, real TLS proxy, converter run on a real Stitch zip, browser install/offline.
