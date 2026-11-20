# Website claims vs. what the code does

Source: https://opencpo.io (checked 2026-11-19). Labels as in the README.

| Claim | Verdict | Evidence |
|---|---|---|
| Chargers are "invisible on the internet", mTLS, per-device certificates | **Not delivered** | Core 1.6 has no TLS, 2.0.1 TLS is optional and falls back to `ws://` (TESTED: unregistered charger accepted, no auth). Bastion listener is plain `ws://` (CODE). |
| Built-in PKI: Root, CPO Sub-CA, MO Sub-CA | Implemented, with a crash | CA hierarchy exists (CODE). `generate_crl()` raises NameError (`ca_ops.py:70`, pyflakes). Runtime PKI chain not run. |
| ISO 15118 Plug & Charge | **Stub** | `SignCertificate` logs and returns Accepted; `Get15118EVCertificate` returns empty `exiResponse` (CODE). |
| Revoke a compromised device in under 1 second | **Unsupported** | No live disconnect on revoke, no CRL/OCSP at handshake, CRL generation crashes (CODE). |
| NIS2 compliant by design | Unsupported | Needs encryption, identity, audit trail; first two not enforced, audit log is PKI-only (CODE). |
| Full audit trail, queryable | Partial | OCPP messages stored; only PKI events have a query endpoint (CODE). |
| OCPP 1.6 + 2.0.1 Central System | Implemented | 1.6 routing works (TESTED, DB stubbed); 2.0.1 handlers exist (CODE). |
| Driver PWA: scan QR, charge, pay | Partial | Boots, manifest + icons OK (TESTED). Payment not in repo (CODE). Service worker scope is `/static/` so offline recovery fails (TESTED). QR needs `BarcodeDetector` (no iOS/Firefox) (CODE). |
| 5 skins, one env var | **True** | All five boot and serve CSS (TESTED). Unknown name silently 404s CSS. |
| Skin converter command | Wrong as written | Script is `tools/stitch-to-skin.py`, not in repo root; no compose file in the charge-app repo (CODE). |
| Admin: chargers, sessions, tariffs, PKI, live OCPP viewer | **True** | Pages render against a mock core (TESTED). Remote terminal is a stub (CODE). |
| Farm: 18 stress scenarios | **False: 17** | Registry count 17, all instantiate (TESTED); README says 17. |
| Farm: simulate networks | Partial | 1.6 chargers connect and boot (TESTED). No transactions seen in a 35 s run (inconclusive). 2.0.1 charger crashes on import (TESTED). |
| Tester: validate firmware, pass/fail reports | Works for 1.6 | 11 tests ran, PDF/HTML/JSON reports written (TESTED). Only 78 of 102 test classes are runnable; 2.0.1 has 20 (TESTED). No web UI. |
| Bastion: OCPP proxy, cert vault, sensors, UniFi, LPR, 4G, HA | Mixed | See [bastion.md](components/bastion.md). Install and 26/27 tests OK (TESTED); mTLS missing, vault unusable by proxy (TESTED). |
| "Six production-ready components" | Overstated | No component has its own test suite except bastion (27 tests). |
| "Production code from a team that charges real vehicles every day" | Not verifiable here | |
