# opencpo-tester (commit 479e91f)

## Works (TESTED)
- Installs; `main.py --help` OK. Listener port controlled by `PORT` / `--port`.
- Against a simulated OCPP 1.6 charger: 11 tests ran (5 pass, 2 fail, 4 skip), grade C; PDF, HTML and JSON reports written.

## Broken or misleading
| Finding | Evidence |
|---|---|
| 102 test classes exist (59 v1.6 + 43 v2.0.1) but only **78 are runnable** (v1.6: 58, v2.0.1: 20); 24 are not registered; the v2.0.1 security module is never imported | TESTED |
| It is a CLI + WebSocket listener, not a web app; a browser on 8090 gets `426 Upgrade Required` | TESTED |
| `DEFAULT_WS_URL` (set in compose) is never read; the tester never dials out to core | TESTED |
| `HOST` env var is never read | TESTED |
| No tests for reservations, local list, ChangeAvailability, ClearCache, certificate install | CODE |
| No tests of its own | repo |

## Not tested
Most v1.6 categories, any v2.0.1 test run (farm 2.0.1 charger fails, see charger-farm.md), PDF content.
