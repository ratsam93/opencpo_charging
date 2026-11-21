"""HA replication key derivation and crypto requirements."""
import asyncio
import sys

import pytest

from gateway import ha
from gateway.config import GatewayConfig


def _mgr(key):
    cfg = GatewayConfig()
    m = ha.HAManager(cfg)
    m._encryption_key = key.encode()
    return m


def test_derive_key_is_32_bytes_and_uses_whole_secret():
    a = ha.derive_aes_key("x" * 40 + "A")
    b = ha.derive_aes_key("x" * 40 + "B")        # differs only past char 32
    assert len(a) == 32 and a != b
    assert ha.derive_aes_key("s") != ha.derive_aes_key("s ")


def test_encrypt_roundtrip_and_no_plaintext():
    m = _mgr("shared-secret-" + "y" * 50)
    ct = m._encrypt(b"state")
    assert b"state" not in ct and m._decrypt(ct) == b"state"
    with pytest.raises(Exception):
        _mgr("other")._decrypt(ct)


def test_refuses_replication_without_cryptography(monkeypatch):
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    m = _mgr("k")
    with pytest.raises(ImportError):               # raises, never returns plaintext
        m._encrypt(b"state")
    with pytest.raises(RuntimeError):
        m._require_crypto()
    m._role = "active"
    asyncio.run(m._replication_loop())             # returns immediately, no plaintext sender


def test_keepalived_auth_pass_not_default():
    p1, p2 = ha._keepalived_auth_pass(""), ha._keepalived_auth_pass("")
    assert p1 != "opencpo0" and len(p1) == 8 and p1 != p2
    assert ha._keepalived_auth_pass("abc") == ha._keepalived_auth_pass("abc")
