# Payment webhook

`POST /api/payments/webhook` tells core that a driver's payment changed state. It marks the session's
`payment_status` and, when a session becomes `paid` or `authorized`, sends `RemoteStartTransaction` to the
charger. **Anyone who can call it can start charging for free, so it is authenticated.**

A call is accepted when it has **either**
1. a valid signature (below), **or**
2. the management key (`X-API-Key` / `Authorization: Bearer`), for adapters that run inside the platform.

Otherwise it gets `401`. If `PAYMENT_WEBHOOK_SECRET` is empty, only the management key works.

## Signing (HMAC-SHA256)

```
X-Webhook-Timestamp: <unix seconds>
X-Webhook-Signature: sha256=<hex( HMAC_SHA256(PAYMENT_WEBHOOK_SECRET, "<timestamp>." + raw_body) )>
```
The timestamp must be within 5 minutes of the server clock (replay protection). Sign the exact bytes you send.

Body: `{"session_id": "<uuid>", "status": "<status>"}` where status is one of
`pending, open, authorized, paid, failed, cancelled, expired, refunded`. Any other value is rejected with `400`:
internal states such as `remote_start_failed` can only be set by core.

### Example
```bash
BODY='{"session_id":"<uuid>","status":"paid"}'
TS=$(date +%s)
SIG="sha256=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$PAYMENT_WEBHOOK_SECRET" | sed 's/^.* //')"
curl -X POST http://core:8000/api/payments/webhook \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Timestamp: $TS" -H "X-Webhook-Signature: $SIG" -d "$BODY"
```
```python
import hashlib, hmac, json, time, requests
body = json.dumps({"session_id": sid, "status": "paid"}).encode()
ts = str(int(time.time()))
sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
requests.post(url, data=body, headers={"Content-Type": "application/json",
              "X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig})
```
`configure.py` generates `PAYMENT_WEBHOOK_SECRET` for new installs. For an existing install add
`PAYMENT_WEBHOOK_SECRET='<openssl rand -hex 32>'` to `.env` and recreate core.
