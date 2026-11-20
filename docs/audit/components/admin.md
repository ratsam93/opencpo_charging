# opencpo-admin (commit 22bbc51)

## Works (TESTED, mock core)
- `/health` 200; `/` redirects to `/login`; login/logout flow and error message OK.
- All 53 GET routes redirect to `/login` when logged out, except `/health`, `/login`, `/setup/start`.
- `/chargers`, `/sessions`, `/tariffs`, `/pki` render when logged in; no Jinja errors.

## Broken or weak
| Finding | Evidence |
|---|---|
| `/groups/1`, `/tokens/1`, `/pki` return 500 when core returns an unexpected shape (no error handling) | TESTED |
| Cookie lacks `Secure`; `GET /logout` (CSRF-able); no CSRF protection, rate limiting or security headers | CODE |
| ~50 places interpolate exception text/user input into HTML f-strings without escaping | CODE |
| Public-path check uses `startswith` (`/setupXYZ`, `/healthXYZ` bypass auth middleware) | CODE |
| Setup check fails open when core is unreachable; `POST /setup/step/*` forwards unauthenticated | CODE |
| Empty `JWT_SECRET`: PyJWT refuses an empty key locally, falls back to core `/me` (outcome depends on core) | CODE |
| Remote terminal is a stub (`templates/remote.html:285`) | CODE |
| `ORG_NAME` and `PUBLIC_URL` from compose are ignored; `.env.example` stale | CODE |
| Container runs as root, no HEALTHCHECK | CODE |
| No tests | repo |

## Not tested
POST actions, HTMX partials, SSE stream, XSS payloads, rate limiting, forged-token acceptance with a real core.
