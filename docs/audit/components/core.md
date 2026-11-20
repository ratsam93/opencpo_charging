# opencpo-core (commit b2d5ee8)

## Works
- Starts only with a database; `/health` returns 200 and `/health/ready` reports "degraded" without DB/Redis. Ports remappable via `API_PORT`, `OCPP16_PORT`, `OCPP201_PORT` (TESTED).
- OCPP 1.6 routing: Boot, Heartbeat, StatusNotification, Authorize (known/unknown tag), unknown action returns `NotImplemented` (TESTED, DB stubbed).
- `db/schema.sql` loads cleanly into empty PostgreSQL 16: 35 tables, no extensions needed (TESTED).
- 76 of 83 modules import; compileall passes (TESTED).

## Broken or missing
| Finding | Evidence |
|---|---|
| Update, backup/restore/delete, setup routers have no auth; first admin can be created by anyone while no admin exists | CODE (`api/main.py:125-129`, `admin_update.py:176`, `admin_backup.py:146/201/262`, `admin_setup.py`) |
| Charger/session/event read endpoints and webhook POST/DELETE unauthenticated; CORS `*` with credentials | CODE |
| Any charger ID accepted, no `Authorization` check, no TLS on 1.6 | TESTED |
| 2.0.1 mTLS is `CERT_OPTIONAL`; falls back to plain `ws://` when `server.crt` is missing | CODE |
| `generate_crl()` raises NameError: `Encoding` never imported (`pki/ca_ops.py:70`) | CODE + pyflakes |
| CRL only covers CPO-issued certs, so revoked MO/contract certs never appear | CODE |
| Plug & Charge stub: no `CertificateSigned`, empty `exiResponse` | CODE |
| Revocation does not disconnect live websockets | CODE |
| `db/migrations` missing but mounted by compose; `alembic upgrade head` fails 4 ways (needs psycopg v3, version table before schema, `sa.Real`, `POINT`) | TESTED |
| Admin JWT secret can be empty string; account JWT default `change-me-in-production` | CODE |
| `SECRET_KEY`, `PUBLIC_URL`, `DB_UTILS`, `CORE_API_PUBLIC_URL` never read; Redis defaults differ (6380/db 2) | CODE |
| `pywebpush`, `sqlalchemy` missing from requirements; `psycopg2-binary` duplicated | TESTED |
| `ocpi.*` submodules fail to import in isolation (circular import) | TESTED |
| `management_auth` redefined at `api/main.py:100` | pyflakes; check wiring |
| No tests | repo |

## Not tested
2.0.1 server, real transaction/meter logic, PKI chain with openssl, live auth status codes, TLS with a real cert.
