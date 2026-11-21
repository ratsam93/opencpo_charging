# Charger authentication (OCPP WebSocket)

Core refuses a charger's WebSocket connection (HTTP 401/403/429/400, before the handshake completes) unless
**one** of these is true. Applies to both OCPP 1.6 (port 9100) and 2.0.1 (port 9201).

| Method | When it applies |
|---|---|
| **Password** (OCPP security profile 1/2) | HTTP Basic auth: user name = charge point id, password = a per-charger secret created with the management API. Stored only as a bcrypt hash. |
| **Client certificate** (profile 3) | TLS is on and the charger presents a verified certificate whose common name equals the charge point id. A certificate for another id is refused (403). |
| **Trusted network or host** | The peer address is in `OCPP_TRUSTED_CIDRS` or resolves from `OCPP_TRUSTED_HOSTS`. Explicit opt-in, no password needed. |

Also: the charge point id must be 1-64 characters of `A-Z a-z 0-9 . _ : -` (400 otherwise; an empty id used to create a
charge point named ""), unknown chargers are no longer auto-registered, and more than 10 failures from one address in a
minute are throttled with 429 (even a correct password is refused while throttled). Unknown ids cost the same time as
wrong passwords (no id enumeration by timing).

## Managing credentials
```bash
scripts/charger-credentials.sh create STATION-A   # prints the password ONCE (create again = rotate)
scripts/charger-credentials.sh list               # ids only, never secrets
scripts/charger-credentials.sh revoke STATION-A   # revokes AND disconnects the charger (close code 1008)
```
Or the API (management key): `POST/DELETE /api/v1/charger-credentials/{id}`, `GET /api/v1/charger-credentials`.
You may supply your own password (at least 16 characters) in the POST body `{"password": "..."}`.

Configure the charger with: user name = its charge point id, password = the printed secret, security profile 1 (plain
`ws://`, only inside a private network) or 2 (`wss://`, recommended). Use a reverse proxy or the Bastion for TLS.

## Settings
| Variable | Default | Meaning |
|---|---|---|
| `OCPP_AUTH_MODE` | `required` | `off` restores the old open behaviour (development only; logs a warning) |
| `OCPP_TRUSTED_HOSTS` | `charger-farm` (compose) | hosts resolved through DNS whose address may connect without a password; set empty to trust nothing |
| `OCPP_TRUSTED_CIDRS` | empty | networks that may connect without a password, for example the private mesh your Bastion sites use (`100.64.0.0/10` for Tailscale) |

**Bastion:** it terminates the charger's (m)TLS at the site and forwards to core over the private mesh, so core sees
the Bastion's mesh address. Put that range in `OCPP_TRUSTED_CIDRS`. Anything inside a trusted range can claim any charge
point id, so keep those ranges small and private.

## Upgrading
Existing chargers stop connecting until they have a password. Create credentials first (`scripts/charger-credentials.sh`),
update the chargers, then upgrade; or set `OCPP_AUTH_MODE=off` temporarily while you migrate. The credentials table is
created automatically on startup, also for databases created before this change.
