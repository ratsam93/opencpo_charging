# opencpo-bastion (commit 1c07c77)

## Works (TESTED)
- `requirements.txt` installs on x86 (RPi.GPIO skipped by platform marker); compileall passes.
- 27 tests: 26 pass, 1 fails, identically on `websockets` 12.0 and 17.4.
- HA AES round trip works; key derivation and plaintext fallback behave as described below.

## Broken or not delivered
| Finding | Evidence |
|---|---|
| **No mTLS on the charger side**: listener is plain `ws://` on 0.0.0.0; charger ID is taken from the URL path with no check | CODE |
| **Vault key cannot be used by the proxy**: `ssl.load_cert_chain` fails (`PEM lib`) on the vault's encrypted blob | TESTED |
| Vault key = `sha256(/etc/machine-id + fixed salt)`; machine-id is world-readable (0644), so it is obfuscation | TESTED |
| Upstream TLS verification disabled (`CERT_NONE`) when no CA file exists | CODE |
| `provision()` overwrites the key before the CSR is signed; TPM path leaves `/tmp/primary.ctx` | CODE |
| HA key = secret padded with `0` to 32 chars, extra chars ignored; replication falls back to plaintext without `cryptography`; keepalived default `opencpo0` | TESTED |
| Proxy handler `lambda ws, path` likely fails on `websockets` >= 13; requirement allows 13+ | CODE, **still untested** |
| Reconnect loop drops the charger after upstream closes; VIP bind setting ignored (dead code) | CODE |
| Calls core endpoints (`/api/v1/pki/sign`, `/api/v1/lpr/detect`) not found in core; Bastion absent from orchestrator compose | CODE |
| `test_recent_reads_limit` fails: second `LPRProcessor` re-registers Prometheus metrics (`DuplicateTimeseries`, `gateway/lpr.py:97`) | TESTED |
| Undefined name `Any` at `gateway/cctv.py:105`; UniFi TLS verification disabled; ONVIF PTZ raises NotImplementedError | pyflakes / CODE |
| 13 modules untested incl. `keyvault`, `ha`, `main`, `connectivity`, `updater` | TESTED |
| LPR relays UniFi detections; no independent engine | CODE |

## Not tested
Hardware paths (sensors, 4G failover, TPM), image build, the proxy relay itself, HA failover.
