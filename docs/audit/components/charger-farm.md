# opencpo-charger-farm (commit f2a5daa)

## Works (TESTED)
- Both UIs boot: `main.py` (older, port from `FARM_UI_PORT`) and `control.py` (newer, port from `PORT`).
- Registry has **17** scenarios; all instantiate at all 4 intensities.
- Four scenarios (one per group) ran 35 s at 5 chargers: all connected, sent Boot/Status, no crashes.

## Broken or inconsistent
| Finding | Evidence |
|---|---|
| Website says 18 scenarios; code and README say 17 | TESTED |
| OCPP 2.0.1 charger crashes on import (`BootReasonType` missing from `ocpp.v201.enums`); no `ocpp` release tried satisfies both imports | TESTED |
| `_spawn_charger` ignores `ocpp_version`, so every scenario spawns 1.6 chargers | TESTED |
| No Authorize/StartTransaction/MeterValues reached the mock within 35 s (first "Preparing" at ~30 s): **inconclusive**, rerun longer | TESTED |
| Dockerfile runs `main.py` (ignores `PORT`) but farm compose sets `PORT=8086` and maps 8086 | CODE + TESTED |
| Scenario API differs: `POST /api/scenarios/{name}` (control.py) vs `/api/scenario/{name}/start` (main.py) | TESTED |
| `charger_cli.py` references undefined names (`OCPP_URL`, `CP_ID`, `log`, ...) so it cannot run | TESTED |
| No `/health` route; no tests; `requirements.txt` leaves `ocpp` unpinned | TESTED |
| No UnlockConnector or ClearCache handler | CODE |
