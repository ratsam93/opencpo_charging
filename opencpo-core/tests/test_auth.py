"""Routes that used to be open must answer 401 without the management key."""
import pytest

from tests.conftest import KEY

SID = "00000000-0000-0000-0000-000000000001"

# (method, path) -> was reachable by anyone before the fix (confirmed against a live stack)
PROTECTED = [
    ("GET", "/api/v1/chargers"),
    ("GET", "/api/v1/chargers/CP1"),
    ("GET", "/api/v1/chargers/CP1/sessions"),
    ("GET", "/api/v1/sessions"),
    ("GET", "/api/v1/sessions/stats/today"),
    ("GET", f"/api/v1/sessions/{SID}"),
    ("GET", "/api/v1/events/history"),
    ("GET", "/api/v1/events/stream"),
    ("GET", "/api/v1/events/info"),
    ("POST", "/api/v1/events/webhooks"),
    ("DELETE", "/api/v1/events/webhooks/1"),
    ("GET", "/api/v1/admin/update/status"),
    ("GET", "/api/v1/admin/update/history"),
    ("POST", "/api/v1/admin/update/run"),
    ("POST", "/api/v1/admin/update/postpone"),
    ("GET", "/api/v1/admin/backups"),
    ("POST", "/api/v1/admin/backups"),
    ("POST", f"/api/v1/admin/backups/{SID}/restore"),
    ("DELETE", f"/api/v1/admin/backups/{SID}"),
    ("GET", "/api/v1/charger-credentials"),
    ("POST", "/api/v1/charger-credentials/CP1"),
    ("DELETE", "/api/v1/charger-credentials/CP1"),
    ("POST", "/api/v1/admin/setup/step/admin"),
    ("POST", "/api/v1/admin/setup/step/org"),
    ("POST", "/api/v1/admin/setup/step/branding"),
    ("POST", "/api/v1/admin/setup/step/smtp"),
    ("POST", "/api/v1/admin/setup/step/pki"),
    ("POST", "/api/v1/admin/setup/step/pricing"),
    ("POST", "/api/v1/admin/setup/step/features"),
    ("POST", "/api/v1/admin/setup/step/tailscale"),
    ("POST", "/api/v1/admin/setup/skip/org"),
    ("GET", f"/api/v1/public/sessions/{SID}"),
    ("POST", f"/api/v1/public/sessions/{SID}/stop"),
    ("POST", f"/api/v1/public/sessions/{SID}/cancel"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_requires_key(client, method, path):
    r = client.request(method, path, json={})
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


@pytest.mark.parametrize("method,path", PROTECTED)
def test_wrong_key_rejected(client, method, path):
    r = client.request(method, path, json={}, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", [p for p in PROTECTED if "stream" not in p[1]])
def test_correct_key_passes_authentication(client, method, path):
    r = client.request(method, path, json={}, headers=KEY)
    assert r.status_code != 401, f"{method} {path} rejected a valid key"


# Must stay reachable without a key: the admin UI, the charge app and chargers rely on them.
PUBLIC = [
    ("GET", "/health"),
    ("GET", "/api/v1/admin/setup/status"),
    ("POST", "/api/v1/admin/auth/login"),
    ("POST", "/api/v1/public/sessions"),
    ("GET", "/api/v1/pricing/current"),
]


@pytest.mark.parametrize("method,path", PUBLIC)
def test_public_routes_stay_public(client, method, path):
    r = client.request(method, path, json={})
    assert r.status_code not in (401, 403), f"{method} {path} should stay public, got {r.status_code}"
