# Live full-stack test (2026-11-21)

The real `docker-compose.yml` was run in a disposable sandbox (core, admin, charge-app, charger-farm,
tester, Postgres, Redis) with the fixed component branches and core from upstream (`b2d5ee8`), and nine
test agents drove it concurrently. Evidence labels: **LIVE** = observed against the running stack.
Sandbox deviations: Debian's apt mirror was unreachable, so the admin and core images were built without
their `apt` steps (only `curl` and the Docker client) and use Python healthchecks; TLS and real chargers
were not available.

## What works (LIVE)
| Area | Result |
|---|---|
| Stack | All services healthy; ports on loopback; core mounts only `./scripts` (ro), backups and PKI volumes; admin/charge-app run non-root |
| `scripts/load-schema.sh` | Loads 35 tables; second run is a no-op |
| Restarts | Restarting core, Postgres, or `down`+`up` loses no data and core reconnects by itself |
| Core OCPP 1.6 | Boot, Status, Heartbeat, Authorize, Start/Stop transaction, MeterValues, DataTransfer stored correctly; server-initiated commands work |
| Core PKI | CA hierarchy, issue SECC/contract/user certs verify with `openssl`; revoke 19-38 ms; OCSP revoked/good |
| Admin | ~25 pages render; CSRF/rate-limit/escaping/headers hold; real browser shows no errors or CSP violations |
| Charge app | Full flow against core; stranger gets 403; no browser errors; service worker scope `/` |
| Farm | Boots in ~40 ms; sessions start in ~9 s; 1.6 messages reach the database; cleans up after scenarios |
| Bastion | Proxy relays to real core (websockets 12 and 17); mTLS, reconnect and vault behave as specified; 48 tests pass |
| Tester | 63 + 43 tests run; reports written; 21-test 2.0.1 run grade B |

## Bugs found by the live test and fixed
| Repo | Bug | Status |
|---|---|---|
| orchestrator | **The CA was regenerated whenever the core container was recreated** (no volume), orphaning every issued certificate | fixed: `pki-data` volume (root CA fingerprint identical after `down`+`up`) |
| admin | Feature toggle 404 (regression from my escaping pass), PKI download 500 (no API key), missing invoice 500, UI 503 when core rate-limited | fixed, verified live |
| charge-app | Another driver's session returned (and ownership cookie granted) via core's duplicate guard; cert-setup proxy forwarded spoofable cert headers | fixed, verified live |
| farm | Scenarios never cleaned up chargers; reusing an id with another OCPP version silently kept the old charger | fixed, verified live |
| tester | `--timeout` ignored; errored tests printed "All tests passed" with exit 0; StartTransaction answered twice | fixed, verified live |

## Still open: opencpo-core (not forked; edit in the monorepo)
Ranked by impact; all confirmed LIVE unless noted.
1. **Payment webhook `/api/payments/webhook` has no signature check**: anyone can mark a session paid and trigger a charge.
2. **OCPP 2.0.1 stores almost nothing**: timestamps are passed to asyncpg as strings (`ocpp201/handler.py` ~176-184, `transaction.py`, `meter.py`); also only 1 of ~60 messages reaches `ocpp_messages`; server commands (Reset, GetVariables...) fail with "not connected" for 2.0.1 chargers.
3. **Unauthenticated admin surface**: update, backup, restore, setup (also writable after setup completes: organisation name overwritten), charger/session/event reads, webhook create/delete, public session GET/stop (returns driver phone and email).
4. **Chargers connect without authentication** (any id auto-registers; no TLS on 9100/9201; a bogus Authorization header is accepted); `StartTransaction` does not check the idTag.
5. **Two connections for one charger corrupt its state** (unconditional `pop` in `ocpp16/server.py`).
6. **Duplicate-session guard** keys on charger+connector only and returns another driver's session; core links sessions to accounts by unverified phone; session JSON has no owner field.
7. **PKI**: `GET /crl` crashes (`Encoding` not imported, `pki/ca_ops.py:70`; adding the import makes CRLs verify); OCSP responses carry the wrong certificate id; audit-log filters crash (`\$1`); `/issue/secc` returns no private key; CA private keys are mode 0644; revoking does not disconnect a live charger.
8. **CORS `*` with credentials**; rate limiter trusts a client-set `X-Real-IP` and counts the admin container as one client; `/docs` public.
9. `GET /api/v1/public/sessions/pending` returns 500; unknown chargers/connectors accepted; receipt PDF module missing; Redis consumer timeouts (3 seen, unattributed).
10. **Bastion cannot provision against this core**: it calls `/api/v1/pki/sign`, which does not exist.

## Left in other repos (minor)
- Bastion: retry counter resets on every successful upstream handshake (retries forever); cert/key swap not atomic.
- Farm: no `UnlockConnector`/`ClearCache`/`GetLocalListVersion` handlers; 2.0.1 `Reset` closes the socket before the reply is sent; `GetCompositeSchedule` is a stub.
- Tester: some tests pass vacuously (e.g. `set_charging_profile_invalid`, `set_variables_201_unknown_component`); it does not follow a charger that reconnects.
