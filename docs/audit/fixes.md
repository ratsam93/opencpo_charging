# Prioritised fix list

Status: **done** = on branch `claude/great-newton-0flk8g`; **todo** = needs a fork of that component
that Claude can push to. P0 = fix before exposing anything to the internet.

| # | Pri | Repo | Fix | Status |
|---|---|---|---|---|
| 1 | P0 | orchestrator | Remove default secrets, wire `POSTGRES_PASSWORD`, generate `MANAGEMENT_API_KEY`, bind DB/Redis to localhost | **done** |
| 2 | P0 | orchestrator | Quote `.env` values; remove `ocpp` password fallback in `update.sh` | **done** |
| 2b | P0 | orchestrator | Safe compose defaults: loopback-only ports (`BIND_ADDR`), no Docker socket / repo mount in core (opt-in `docker-compose.updater.yml`); `configure.py` no longer echoes generated secrets in prompts; `scripts/load-schema.sh` for the manual schema load; `scripts/deploy.sh` pull-based auto-deploy with rollback | **done** |
| 2c | P0 | orchestrator | `pki-data` volume so the certificate authority survives container recreation (found by the live test) | **done** |
| 3 | P0 | core | Require `management_auth` on admin update/backup/setup, chargers, sessions, events, webhooks; restrict CORS origins | **done** (management key on chargers/sessions/events, admin update/backup/setup writes, public session read/stop/cancel; verified live) |
| 3b | P0 | core | Payment webhook: HMAC-signed (or management key), 5 min replay window, provider statuses only; `postgresql-client` in the image so backups work | **done** (webhook verified live; image rebuild not possible in the sandbox) |
| 4 | P0 | core | Authenticate chargers: require mTLS or per-charger credentials; refuse plain `ws://` unless explicitly allowed | todo |
| 5 | P0 | charge-app | Ignore `X-Client-Cert-Serial` unless `TRUST_CLIENT_CERT_HEADER` is set | **done on branch** `claude/audit-fixes` (not merged) |
| 6 | P0 | charge-app | Session routes require the owner's cookie/token; stop sending the management key for anonymous calls; do not return raw errors | **done on branch** `claude/audit-fixes` (not merged) |
| 7 | P1 | core | Fix `ca_ops.py:70` (`from cryptography.hazmat.primitives.serialization import Encoding`); include MO certs in CRL | todo |
| 8 | P1 | core | Ship working schema bootstrap: create `db/migrations/001_initial.sql` from `schema.sql`, or fix alembic (psycopg2 URL, create schema first, `sa.REAL`, `POINT`) | todo |
| 9 | P1 | core | Implement `SignCertificate`->`CertificateSigned` and `Get15118EVCertificate`, or stop claiming Plug & Charge | todo |
| 10 | P1 | core | Disconnect live websocket on revoke; check CRL/OCSP at handshake | todo |
| 11 | P1 | bastion | Terminate mTLS on the listener; fix vault so the proxy can read its key; verify upstream TLS always; fix `websockets` handler signature and reconnect loop | **done on branch** `claude/audit-fixes` (not merged; HA peers must upgrade together) |
| 12 | P1 | admin | Fail at startup on empty `JWT_SECRET`; CSRF + login rate limit; escape HTML f-strings; fail setup check closed; handle core error shapes | **done on branch** `claude/audit-fixes` (not merged; CSP is permissive) |
| 13 | P1 | website | Fix demo-form JS (`\n` in strings), add a 404 page, alt text, security headers | todo (site source not in any repo) |
| 14 | P2 | tester | Register the 24 unrunnable tests; fix compose/docs (CLI + WebSocket listener, not a web app) | **done on branch** `claude/audit-fixes` (not merged; 43 v2.0.1 and 63 v1.6 tests runnable) |
| 15 | P2 | charger-farm | Pin `ocpp`, fix 2.0.1 charger imports, pass `ocpp_version` in scenarios, align Dockerfile/compose port, fix `charger_cli.py` | **done on branch** `claude/audit-fixes` (not merged; also fixed a receive-loop bug that stalled every session start) |
| 16 | P2 | charge-app | Register service worker with a wider scope; add `/health`; `Secure` cookie by default; skin-name validation; fix converter docs | **partly done on branch** (`/health`, service-worker scope, `Secure` cookie, skin fallback); QR fallback and converter docs still todo |
| 17 | P2 | orchestrator | Add CI (shellcheck, `compose config`, `configure.py` round trip); checksum-verify downloads; reconsider `docker.sock`; add Bastion/healthchecks | todo |
| 18 | P2 | website | "18 scenarios" -> 17; qualify mTLS / Plug & Charge / NIS2 / "production-ready" claims | todo |
| 19 | P3 | all | Add test suites; fix version/changelog/security-policy drift | todo |

## Open questions that need a longer test
- Do farm scenarios start sessions? (run > 35 s)
- Does the Bastion proxy accept connections on `websockets` >= 13?
- Does the PKI chain verify with `openssl` once item 7 is fixed?
