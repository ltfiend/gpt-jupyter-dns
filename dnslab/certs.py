"""Lab CA and per-instance leaf certificates.

A throwaway lab CA is generated lazily into <workspace>/certs/dnslab/ and
leaf certs are issued per instance with a SAN matching the instance's
TLS hostname (<instance>.dnslab.test). Private keys are written world-
readable on purpose: server containers run as arbitrary uids and this CA
signs nothing outside the lab network.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .state import certs_dir

CA_NAME = "dnslab-ca"
CA_DAYS = 3650
LEAF_DAYS = 730


def ca_file() -> Path:
    ensure_ca()
    return certs_dir() / f"{CA_NAME}.pem"


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o644)  # lab-only key; containers with random uids must read it


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o644)


def _load_cert(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def _expired_or_missing(cert_path: Path, key_path: Path) -> bool:
    if not cert_path.exists() or not key_path.exists():
        return True
    cert = _load_cert(cert_path)
    return cert.not_valid_after_utc <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)


def ensure_ca(force: bool = False) -> tuple[Path, Path]:
    d = certs_dir()
    cert_path, key_path = d / f"{CA_NAME}.pem", d / f"{CA_NAME}.key"
    if not force and not _expired_or_missing(cert_path, key_path):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "dnslab lab CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "dnslab"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        # SKI/AKI are mandatory under strict validation (e.g. Python 3.13+
        # enables VERIFY_X509_STRICT in default ssl contexts)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                       critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    _write_key(key_path, key)
    _write_cert(cert_path, cert)
    return cert_path, key_path


def ensure_cert(instance: str, sans: list[str] | None = None, force: bool = False) -> tuple[Path, Path]:
    """Issue (or reuse) a leaf cert for an instance.

    SANs default to <instance>.dnslab.test; extra DNS names or IP literals
    may be passed (IPs are added as IP SANs).
    """
    ca_cert_path, ca_key_path = ensure_ca()
    d = certs_dir()
    cert_path, key_path = d / f"{instance}.pem", d / f"{instance}.key"

    wanted = list(dict.fromkeys([f"{instance}.dnslab.test", *(sans or [])]))
    if not force and not _expired_or_missing(cert_path, key_path):
        cert = _load_cert(cert_path)
        # reissue if the CA is newer than the leaf or SANs changed
        ca_cert = _load_cert(ca_cert_path)
        try:
            existing = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            have = {str(g.value) for g in existing}
        except x509.ExtensionNotFound:
            have = set()
        if cert.not_valid_before_utc >= ca_cert.not_valid_before_utc and set(wanted) <= have:
            return cert_path, key_path

    ca_cert = _load_cert(ca_cert_path)
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    key = ec.generate_private_key(ec.SECP256R1())
    san_entries: list[x509.GeneralName] = []
    for s in wanted:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            san_entries.append(x509.DNSName(s))
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, wanted[0])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=LEAF_DAYS))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                       critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
                ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key_path, key)
    _write_cert(cert_path, cert)
    return cert_path, key_path


def regen(force: bool = True) -> None:
    """Wipe and reissue the CA; leaf certs regenerate on next start()."""
    d = certs_dir()
    if force:
        for f in d.glob("*.pem"):
            f.unlink()
        for f in d.glob("*.key"):
            f.unlink()
    ensure_ca(force=True)
