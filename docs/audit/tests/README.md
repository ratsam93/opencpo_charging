# Test scripts

Scripts written by the audit agents. They ran as part of the audit (see the component files).
They contain hard-coded paths and ports from the audit sandbox (e.g. `/home/user/opencpo_charging`,
ports 18000-18199) and use throwaway test keys; edit before reuse. All servers bind 127.0.0.1.

| Script | Tests | Used for |
|---|---|---|
| `core_import_driver.py` | core | import every module, list failures |
| `ocpp16_client.py` | core | OCPP 1.6 client: Boot, Heartbeat, Authorize, Start/Stop, unknown action, bad subprotocol |
| `mock_core_admin.py` | admin | tiny FastAPI mock of core for dashboard tests |
| `mock_core_charge_app.py` | charge-app | mock core for skin/PWA tests |
| `mock_core_charge_app_security.py`, `charge_app_security.sh` | charge-app | header-spoof / session-ownership / error-leak probes |
| `tester_inventory.py` | tester | count registered vs defined tests |
| `farm_scenarios_driver.py` | charger-farm | run a scenario against a mock CSMS |

Not included: runs that came back static-only (PKI, core 2.0.1, admin security, bastion proxy).
