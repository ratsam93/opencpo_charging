"""
OpenCPO Bastion — Certificate Key Vault

Manages the device TLS certificate lifecycle:
  - First boot: generate RSA keypair, create CSR, request signed cert from Core PKI
  - Auto-renewal: checks expiry daily, renews 30 days before expiry
  - Storage: /etc/opencpo/certs/ (encrypted with device-specific key)
  - TPM: detects Pi TPM HAT, uses for key storage when available
  - Fallback: LUKS-encrypted partition, or software encryption keyed to machine-id
  - Private keys never leave the device
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

CERT_DIR = Path("/etc/opencpo/certs")
CERT_FILE = CERT_DIR / "device.crt"
KEY_FILE = CERT_DIR / "device.key"
CA_FILE = CERT_DIR / "ca.crt"
MACHINE_ID_FILE = Path("/etc/machine-id")


def _device_id() -> str:
    """Stable unique device identifier based on machine-id."""
    try:
        return MACHINE_ID_FILE.read_text().strip()
    except Exception:
        return f"gw-{os.urandom(8).hex()}"


VAULT_MAGIC_V2 = b"OCV2"  # blob prefix for secret-mixed key derivation


def _vault_secret() -> bytes:
    """
    Optional operator secret mixed into key derivation.

    Read from OPENCPO_VAULT_SECRET, or from the file named by
    OPENCPO_VAULT_SECRET_FILE. Returns b"" when none is configured.
    """
    val = os.environ.get("OPENCPO_VAULT_SECRET")
    if val:
        return val.encode()
    path = os.environ.get("OPENCPO_VAULT_SECRET_FILE")
    if path:
        try:
            return Path(path).read_bytes().strip()
        except OSError as e:
            logger.error("Cannot read OPENCPO_VAULT_SECRET_FILE %s: %s", path, e)
    return b""


def _legacy_key() -> bytes:
    """sha256(machine-id + fixed salt). Obfuscation only: machine-id is world-readable."""
    import hashlib
    return hashlib.sha256(_device_id().encode() + b"opencpo-keyvault-v1").digest()


def _secret_key(secret: bytes) -> bytes:
    """scrypt over the operator secret, salted with the machine-id."""
    import hashlib
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt = hashlib.sha256(b"opencpo-keyvault-v2" + _device_id().encode()).digest()
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(secret)


def _encryption_key() -> bytes:
    """
    Derive the device encryption key.

    With OPENCPO_VAULT_SECRET (or _FILE) set, the key is scrypt(secret, salt=f(machine-id)),
    so reading /etc/machine-id alone is not enough. WITHOUT a secret this falls back to
    the legacy machine-id-only derivation, which is obfuscation, not protection.
    """
    secret = _vault_secret()
    return _secret_key(secret) if secret else _legacy_key()


def _encrypt_file(path: Path, data: bytes) -> None:
    """Symmetric encryption for key files at rest (atomic write, mode 0600)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    secret = _vault_secret()
    nonce = os.urandom(12)
    if secret:
        blob = VAULT_MAGIC_V2 + nonce + AESGCM(_secret_key(secret)).encrypt(nonce, data, None)
    else:
        logger.warning(
            "OPENCPO_VAULT_SECRET not set — vault key is derived from machine-id only "
            "(obfuscation, not protection)"
        )
        blob = nonce + AESGCM(_legacy_key()).encrypt(nonce, data, None)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


def _decrypt_file(path: Path) -> bytes:
    """Decrypt a vault blob: try the secret-mixed format first, then legacy."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = path.read_bytes()
    secret = _vault_secret()
    if raw.startswith(VAULT_MAGIC_V2):
        if not secret:
            raise ValueError("vault blob needs OPENCPO_VAULT_SECRET but none is set")
        body = raw[len(VAULT_MAGIC_V2):]
        try:
            return AESGCM(_secret_key(secret)).decrypt(body[:12], body[12:], None)
        except InvalidTag:
            pass  # fall through to legacy (blob could be a legacy one starting with the magic)
    return AESGCM(_legacy_key()).decrypt(raw[:12], raw[12:], None)


def _tmpfs_base() -> Path:
    for cand in (Path("/run"), Path("/dev/shm")):
        if cand.is_dir() and os.access(cand, os.W_OK):
            return cand
    raise RuntimeError("no writable tmpfs (/run or /dev/shm) for the decrypted key")


def decrypt_key_to_tmpfs(key_file: Optional[Path] = None, base_dir: Optional[Path] = None):
    """
    Decrypt the vault key to a mode-0600 file inside a private 0700 dir on tmpfs.

    Returns (path, cleanup). Call cleanup() as soon as the consumer has read the
    key (e.g. right after ssl.SSLContext.load_cert_chain).
    """
    import shutil
    import tempfile
    key_pem = _decrypt_file(key_file or KEY_FILE)
    tmpdir = Path(tempfile.mkdtemp(prefix="opencpo-key-", dir=base_dir or _tmpfs_base()))
    os.chmod(tmpdir, 0o700)
    path = tmpdir / "key.pem"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key_pem)
    except BaseException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    def cleanup() -> None:
        try:
            if path.exists():
                with open(path, "r+b") as f:
                    f.write(b"\0" * len(key_pem))
                    f.flush()
                    os.fsync(f.fileno())
                path.unlink()
        except OSError:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    return path, cleanup


class TPMKeyStore:
    """
    TPM 2.0 key storage via tpm2-tools (Pi TPM HAT or discrete TPM).
    Wraps the private key inside the TPM — key never appears in plaintext.
    """

    def __init__(self, handle: int = 0x81000001):
        self.handle = handle
        self._available = self._detect()

    def _detect(self) -> bool:
        import subprocess
        try:
            r = subprocess.run(
                ["tpm2_getcap", "properties-fixed"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                logger.info("TPM 2.0 detected — using hardware key storage")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    @property
    def available(self) -> bool:
        return self._available

    def generate_key(self) -> None:
        import subprocess
        import tempfile
        # Primary context lives in a private temp dir that is always removed.
        with tempfile.TemporaryDirectory(prefix="opencpo-tpm-") as td:
            self._generate_key_in(Path(td) / "primary.ctx", subprocess)

    def _generate_key_in(self, primary_ctx: Path, subprocess) -> None:
        primary = str(primary_ctx)
        subprocess.run([
            "tpm2_createprimary", "-C", "o", "-G", "rsa2048",
            "-c", primary,
        ], check=True)
        subprocess.run([
            "tpm2_create", "-G", "rsa2048", "-u", str(CERT_DIR / "tpm_pub.key"),
            "-r", str(CERT_DIR / "tpm_priv.key"), "-C", primary,
        ], check=True)
        subprocess.run([
            "tpm2_load", "-C", primary,
            "-u", str(CERT_DIR / "tpm_pub.key"),
            "-r", str(CERT_DIR / "tpm_priv.key"),
            "-c", str(CERT_DIR / "tpm_handle.ctx"),
        ], check=True)
        subprocess.run([
            "tpm2_evictcontrol", "-C", "o",
            "-c", str(CERT_DIR / "tpm_handle.ctx"),
            hex(self.handle),
        ], check=True)
        logger.info("TPM key provisioned at handle %s", hex(self.handle))


class KeyVault:
    """
    Device certificate lifecycle manager.
    Generates, stores, renews, and provides access to the device cert.
    """

    def __init__(self, config, renew_days_before: int = 30):
        self.config = config
        self.renew_days_before = renew_days_before
        self._tpm = TPMKeyStore()
        self._cert: Optional[x509.Certificate] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._pending_key_pem: Optional[bytes] = None

    def decrypt_key_to_tmpfs(self):
        """Decrypt the device key to a private tmpfs file; returns (path, cleanup)."""
        if self._tpm.available:
            raise RuntimeError("key is TPM-backed; no software key to export")
        return decrypt_key_to_tmpfs(KEY_FILE)

    async def start(self) -> None:
        CERT_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._http = httpx.AsyncClient(timeout=30)

        if not CERT_FILE.exists():
            logger.info("No device cert found — running first-boot provisioning")
            await self.provision()
        else:
            self._load_cert()
            logger.info(
                "Device cert loaded (expires %s)",
                self._cert.not_valid_after_utc.strftime("%Y-%m-%d") if self._cert else "unknown",
            )

        # Start renewal background loop
        asyncio.create_task(self._renewal_loop())

    def _load_cert(self) -> None:
        try:
            raw = CERT_FILE.read_bytes()
            self._cert = x509.load_pem_x509_certificate(raw)
        except Exception as e:
            logger.error("Failed to load device cert: %s", e)
            self._cert = None

    def _generate_keypair(self) -> rsa.RSAPrivateKey:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        if self._tpm.available:
            # Store via TPM — don't write plaintext key
            self._tpm.generate_key()
        else:
            # Persisted later by provision(), only after the signed cert is stored.
            self._pending_key_pem = key_pem

        logger.info(
            "Keypair generated (%s)",
            "TPM-backed" if self._tpm.available else "software (pending commit)",
        )
        return key

    def _build_csr(self, key: rsa.RSAPrivateKey) -> bytes:
        device_id = _device_id()
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, f"gw-{device_id[:16]}"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenCPO Bastion"),
            ]))
            .sign(key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM)

    async def provision(self) -> None:
        """First-boot: generate keypair, get CSR signed by Core PKI."""
        logger.info("Provisioning device certificate from Core PKI...")
        key = self._generate_keypair()
        csr_pem = self._build_csr(key)
        device_id = _device_id()

        try:
            r = await self._http.post(
                f"{self.config.core_api_base}/api/v1/pki/sign",
                content=csr_pem,
                headers={
                    "Content-Type": "application/x-pem-file",
                    "X-Device-ID": device_id,
                },
            )
            r.raise_for_status()

            # Response: signed cert PEM + CA cert PEM
            body = r.json()
            cert_pem = body["cert"].encode()
            ca_pem = body.get("ca", "").encode()

            # Stage the new key (encrypted) next to the old one; swap in only
            # after the signed cert is stored so a failed signing keeps the old pair.
            staged_key = None
            if self._pending_key_pem is not None:
                staged_key = KEY_FILE.with_name(KEY_FILE.name + ".new")
                _encrypt_file(staged_key, self._pending_key_pem)

            tmp_cert = CERT_FILE.with_name(CERT_FILE.name + ".tmp")
            tmp_cert.write_bytes(cert_pem)
            tmp_cert.chmod(0o644)
            os.replace(tmp_cert, CERT_FILE)
            if staged_key is not None:
                os.replace(staged_key, KEY_FILE)
                self._pending_key_pem = None

            if ca_pem:
                CA_FILE.write_bytes(ca_pem)
                CA_FILE.chmod(0o644)

            self._load_cert()
            logger.info("Device certificate provisioned successfully")

        except Exception as e:
            logger.error("Certificate provisioning failed: %s", e)
            raise

    async def _renewal_loop(self) -> None:
        while True:
            await asyncio.sleep(86400)  # check daily
            await self._maybe_renew()

    async def _maybe_renew(self) -> None:
        if not self._cert:
            self._load_cert()
        if not self._cert:
            logger.warning("No cert to check for renewal")
            return

        now = datetime.now(timezone.utc)
        expiry = self._cert.not_valid_after_utc
        days_left = (expiry - now).days

        logger.debug("Cert expires in %d days", days_left)

        if days_left <= self.renew_days_before:
            logger.info("Cert expires in %d days — renewing", days_left)
            try:
                await self.provision()
            except Exception as e:
                logger.error("Cert renewal failed: %s", e)

    @property
    def cert_path(self) -> str:
        return str(CERT_FILE)

    @property
    def key_path(self) -> str:
        return str(KEY_FILE)

    @property
    def ca_path(self) -> str:
        return str(CA_FILE) if CA_FILE.exists() else ""

    def cert_info(self) -> dict:
        if not self._cert:
            return {"status": "missing"}
        now = datetime.now(timezone.utc)
        expiry = self._cert.not_valid_after_utc
        return {
            "status": "valid",
            "subject": self._cert.subject.rfc4514_string(),
            "issuer": self._cert.issuer.rfc4514_string(),
            "not_before": self._cert.not_valid_before_utc.isoformat(),
            "not_after": expiry.isoformat(),
            "days_remaining": (expiry - now).days,
            "storage": "tpm" if self._tpm.available else "software",
        }
