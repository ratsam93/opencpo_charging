# Repository layout

Everything lives in this one repository. Each component is a folder with its own `Dockerfile`, and
`docker-compose.yml` builds them from here.

| Folder | What it is | Compose service | Origin |
|---|---|---|---|
| `opencpo-core/` | OCPP 1.6 / 2.0.1 CSMS, REST API, PKI | `ocpp-core` | upstream `opencpo/opencpo-core` @ `b2d5ee8` (**unmodified so far; see `docs/audit/live-test.md`**) |
| `opencpo-admin/` | operator dashboard | `cpo-admin` | fork `opencpo-admin_charger` @ `96a92c4` |
| `opencpo-charge-app/` | driver PWA | `charge-app` | fork `opencpo-charge-app` @ `bac950d` |
| `opencpo-charger-farm/` | virtual charger simulator | `charger-farm` | fork `opencpo-charger-farm` @ `b8fb3f2` |
| `opencpo-tester/` | OCPP compliance tester (CLI + WebSocket listener) | `compliance-tester` | fork `opencpo-tester` @ `d9dd09f` |
| `opencpo-bastion/` | Raspberry Pi site controller (not part of compose) | none | fork `opencpo-bastion` @ `ac1b8dd` |

The folders were imported as plain source (no nested git history). The old per-component repositories
under `ratsam93/` are no longer the place to make changes: work here, with one branch and one pull
request per change. Each folder keeps its own `LICENSE` and `NOTICE` (Apache-2.0).

Other top-level pieces: `scripts/` (deploy, schema loader), `deploy/` (systemd, Caddy), `docs/`, `configure.py`,
`setup.sh`, `update.sh`.

## Running a component's tests
```bash
cd opencpo-admin && pip install -r requirements.txt pytest && pytest        # admin (20)
cd opencpo-charge-app && pip install -r requirements-dev.txt && pytest      # charge app (19)
cd opencpo-tester && pip install -r requirements.txt pytest && pytest       # tester (6)
cd opencpo-charger-farm && pip install -r requirements-dev.txt && pytest    # farm (10)
cd opencpo-bastion && pip install -r requirements.txt pytest pytest-asyncio && pytest   # bastion (48)
scripts/test-deploy.sh                                                      # deploy script (40)
```
Core has no test suite upstream yet.

Audited commits and findings: [audit/README.md](audit/README.md), [audit/live-test.md](audit/live-test.md).
