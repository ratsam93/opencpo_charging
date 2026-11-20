# OpenCPO platform audit

Audit of the website (opencpo.io), this orchestrator repo and the six component repos,
done 2026-11-19/20. Every finding carries an evidence label:

| Label | Meaning |
|---|---|
| **TESTED** | Observed by running the code (mock backends, local ports, throwaway Postgres) |
| **CODE** | Read from source only; not executed |
| **NOT TESTED** | Could not be checked |

Nothing was tested against real chargers, real TLS/mTLS, a real TimescaleDB, Docker (no daemon
was available) or the live demo site. Audited upstream commits: core `b2d5ee8`, admin `22bbc51`,
charge-app `9f5c2e4`, tester `479e91f`, charger-farm `f2a5daa`, bastion `1c07c77`.

## Scorecard

| Component | Basic function | Security | Tests in repo | Verdict |
|---|---|---|---|---|
| [core](components/core.md) | Handlers, PKI, REST work | **Weak**: open admin endpoints, optional mTLS, P&C stub | none | Not production-ready |
| [admin](components/admin.md) | Works against a mock core | Medium: no CSRF/rate limit/headers | none | Usable after fixes |
| [charge-app](components/charge-app.md) | Boots, 5 skins work | **Weak**: spoofable identity, open session routes | none | Fix before public use |
| [tester](components/tester.md) | Runs, writes reports | n/a | none | CLI only; 24 of 102 tests not runnable |
| [charger-farm](components/charger-farm.md) | Runs, 17 scenarios | n/a | none | 2.0.1 charger broken |
| [bastion](components/bastion.md) | Install OK, 26/27 tests pass | **Weak**: no mTLS, vault is obfuscation | 27 | Central claims not delivered |
| [orchestrator](components/orchestrator.md) | Fixed on this branch | Fixed: no default secrets | none | See fixes.md |
| [website](website.md) | Loads, renders | Weak headers | n/a | Demo form broken |

## Top risks (all CODE+TESTED where noted in the component files)

1. Core update/backup/restore/setup endpoints have no authentication (CODE).
2. Chargers connect without any identity check; mTLS is optional on 2.0.1 and absent on 1.6 (TESTED).
3. Charge app: any client can impersonate a driver with one header; anyone can read/stop any session by ID (TESTED).
4. Bastion, the component meant to deliver zero trust, serves plain `ws://` and its cert vault cannot feed its own proxy (TESTED).
5. Certificate revocation lists cannot be generated: `Encoding` is never imported (CODE, pyflakes-confirmed).
6. Plug & Charge is a stub: no certificate is ever returned (CODE).
7. Fresh `docker compose up` has no schema: `db/migrations` is missing and alembic is broken (TESTED).
8. The website demo form has a JavaScript syntax error and sends nothing (TESTED).

See [claims-vs-reality.md](claims-vs-reality.md) and the prioritised [fixes.md](fixes.md).
Reusable test scripts are in [tests/](tests/README.md).
