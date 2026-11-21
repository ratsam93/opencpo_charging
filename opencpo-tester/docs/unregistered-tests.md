# Unregistered test classes

Every `OCPPTest` subclass is either registered in a category in `runner.py`
(`V16_TEST_CATEGORIES` / `V201_TEST_CATEGORIES`) or listed in
`runner.EXCLUDED_TESTS` with a reason. `tests/test_registry.py` fails if a class is
neither, so new tests cannot silently go unrun.

## Excluded

| Class | Reason |
|---|---|
| `HeartbeatMultipleSamples` (v1.6, `tests/v16/boot.py`) | Stub that unconditionally passes and only points at `heartbeat_interval`, which already collects several heartbeat samples. Registering it would inflate the pass rate without testing anything. |

## Notes on registered v2.0.1 tests

The v2.0.1 `meter_values`, `smart_charging`, `firmware`, `security` and
`remote_control` modules were never imported by the runner. They are now registered
(`security` is a new category in the default order). `firmware` remains full-only
(`--full`) and skips unless `firmware.url` / `diagnostics.upload_url` are configured.
Security tests pass vacuously when the charger sends no SecurityEventNotification /
SignCertificate on its own, which is expected without a TLS security profile.

`get_composite_schedule_201` previously rejected the spec-correct status `Accepted`
(expected `OK`); fixed.
