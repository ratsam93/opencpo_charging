"""Vault decrypt-to-file round trip and provisioning atomicity."""
import asyncio
import os
import ssl
import stat

import pytest

from gateway import keyvault
from tests import _pki


@pytest.fixture(autouse=True)
def vault_env(tmp_path, monkeypatch):
    mid = tmp_path / "machine-id"
    mid.write_text("0123456789abcdef0123456789abcdef\n")
    monkeypatch.setattr(keyvault, "MACHINE_ID_FILE", mid)
    monkeypatch.setattr(keyvault, "CERT_DIR", tmp_path / "certs")
    monkeypatch.setattr(keyvault, "KEY_FILE", tmp_path / "certs" / "device.key")
    monkeypatch.setattr(keyvault, "CERT_FILE", tmp_path / "certs" / "device.crt")
    monkeypatch.setattr(keyvault, "CA_FILE", tmp_path / "certs" / "ca.crt")
    monkeypatch.delenv("OPENCPO_VAULT_SECRET", raising=False)
    monkeypatch.delenv("OPENCPO_VAULT_SECRET_FILE", raising=False)
    (tmp_path / "tmpfs").mkdir()
    return tmp_path


def _pem_pair(tmp_path):
    ca_key, ca = _pki.make_ca()
    key, cert = _pki.issue(ca_key, ca, "dev")
    cp, kp = _pki.write_pair(tmp_path, "plain", key, cert)
    return cp, open(kp, "rb").read()


def test_decrypt_to_tmpfs_roundtrip_loads_in_ssl(vault_env):
    cert, key_pem = _pem_pair(vault_env)
    keyvault._encrypt_file(keyvault.KEY_FILE, key_pem)
    assert keyvault.KEY_FILE.read_bytes() != key_pem          # blob, not PEM
    path, cleanup = keyvault.decrypt_key_to_tmpfs(base_dir=vault_env / "tmpfs")
    try:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, str(path))
    finally:
        cleanup()
    assert not path.exists() and not path.parent.exists()


def test_secret_mixed_into_derivation_and_legacy_compat(vault_env, monkeypatch):
    data = b"top secret key material"
    keyvault._encrypt_file(keyvault.KEY_FILE, data)           # legacy (no secret)
    legacy_blob = keyvault.KEY_FILE.read_bytes()

    monkeypatch.setenv("OPENCPO_VAULT_SECRET", "operator-secret")
    assert keyvault._decrypt_file(keyvault.KEY_FILE) == data  # legacy still readable
    keyvault._encrypt_file(keyvault.KEY_FILE, data)           # new format
    new_blob = keyvault.KEY_FILE.read_bytes()
    assert new_blob.startswith(keyvault.VAULT_MAGIC_V2) and new_blob != legacy_blob
    assert keyvault._decrypt_file(keyvault.KEY_FILE) == data

    monkeypatch.delenv("OPENCPO_VAULT_SECRET")                # machine-id alone is not enough
    with pytest.raises(ValueError):
        keyvault._decrypt_file(keyvault.KEY_FILE)
    monkeypatch.setenv("OPENCPO_VAULT_SECRET", "wrong")
    with pytest.raises(Exception):
        keyvault._decrypt_file(keyvault.KEY_FILE)


def test_secret_from_file(vault_env, monkeypatch):
    sf = vault_env / "secret"
    sf.write_text("file-secret\n")
    monkeypatch.setenv("OPENCPO_VAULT_SECRET_FILE", str(sf))
    keyvault._encrypt_file(keyvault.KEY_FILE, b"x")
    assert keyvault.KEY_FILE.read_bytes().startswith(keyvault.VAULT_MAGIC_V2)
    assert keyvault._decrypt_file(keyvault.KEY_FILE) == b"x"


def test_provision_keeps_old_key_when_signing_fails(vault_env, monkeypatch):
    keyvault._encrypt_file(keyvault.KEY_FILE, b"old-key")
    before = keyvault.KEY_FILE.read_bytes()

    class Cfg:
        core_api_base = "http://127.0.0.1:1"

    v = keyvault.KeyVault.__new__(keyvault.KeyVault)
    v.config = Cfg()
    v._cert = None
    v._pending_key_pem = None

    class NoTpm:
        available = False
    v._tpm = NoTpm()

    class Http:
        async def post(self, *a, **k):
            raise RuntimeError("signing refused")
    v._http = Http()
    with pytest.raises(RuntimeError):
        asyncio.run(v.provision())
    assert keyvault.KEY_FILE.read_bytes() == before
    assert not keyvault.CERT_FILE.exists()
