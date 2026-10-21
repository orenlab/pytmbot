#!/usr/bin/env python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Certificate trust gate for container builds (eMudhra incident, October 2026).

Runs inside the Docker build and fails it when the image would still trust
the "emSign ECC Root CA - G3" root, whose intermediate CA keys were
compromised. Standard library only, so it runs with any Python in the image.

    build    CA-04  uv used by the build is fixed (>= 0.13.4)
    runtime  CA-01  ca-certificates is the fixed Ubuntu package
             CA-02  the system trust store (OpenSSL defaults) does not trust the root
             CA-03  the installed certifi is fixed and does not trust the root
             CA-05  no other CA bundle in the image trusts the root
             CA-06  TLS verification is not disabled globally

Every check prints PASS, FAIL, NOT APPLICABLE or UNVERIFIED. Any FAIL or
UNVERIFIED fails the gate: a state that cannot be confirmed is not safe.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import ssl
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final, cast

# SHA-256 of the DER certificate, cross-checked against the Mozilla bundle in
# certifi 2026.7.22 and Ubuntu's emSign_ECC_Root_CA_-_G3.crt.
DISTRUSTED_ROOTS: Final[dict[str, str]] = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": (
        "emSign ECC Root CA - G3"
    ),
}
DISTRUSTED_COMMON_NAMES: Final[frozenset[str]] = frozenset(DISTRUSTED_ROOTS.values())

# Fixed versions from GHSA-hq85-5cpj-mr62, GHSA-6q48-6c7w-9gw2 and USN-8944-1.
MIN_UV: Final[str] = "0.13.4"
MIN_CERTIFI: Final[str] = "2026.10.19"
MIN_CA_CERTIFICATES: Final[str] = "20260816ubuntu0.26.04.1"

CA_BUNDLE_ENV_VARS: Final[tuple[str, ...]] = (
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
# Locally added CAs and the system Python packages, besides the interpreter's own.
OTHER_BUNDLE_ROOTS: Final[tuple[Path, ...]] = (
    Path("/usr/local/share/ca-certificates"),
    Path("/usr/lib/python3/dist-packages"),
)
_PEM_PATTERN: Final[re.Pattern[bytes]] = re.compile(
    rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S
)


@dataclass(frozen=True, slots=True)
class Result:
    invariant: str
    status: str  # PASS, FAIL, NOT APPLICABLE or UNVERIFIED
    evidence: str


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _pem_certificates(path: Path) -> Iterator[bytes]:
    """Yield DER certificates from a PEM file (unreadable files yield nothing)."""
    try:
        data = path.read_bytes()
    except OSError:
        return
    for pem in _PEM_PATTERN.findall(data):
        yield ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))


def _common_name(der: bytes) -> str:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=der)
    loaded = context.get_ca_certs()
    if not loaded:  # not a CA certificate, so it cannot anchor a chain
        return ""
    # RDNs of (attribute, value) pairs.
    subject = cast("tuple[tuple[tuple[str, str], ...], ...]", loaded[0]["subject"])
    return next(
        (value for rdn in subject for key, value in rdn if key == "commonName"), ""
    )


def distrusted_in(certificates: Iterable[bytes]) -> list[str]:
    """Names of distrusted roots found by fingerprint or by subject common name."""
    found: list[str] = []
    for der in certificates:
        fingerprint = hashlib.sha256(der).hexdigest()
        if fingerprint in DISTRUSTED_ROOTS:
            found.append(f"{DISTRUSTED_ROOTS[fingerprint]} ({fingerprint[:16]}…)")
        elif (name := _common_name(der)) in DISTRUSTED_COMMON_NAMES:
            found.append(f"{name} (same subject, {fingerprint[:16]}…)")
    return list(dict.fromkeys(found))  # capath links repeat the same certificate


def _dpkg_version(package: str) -> str | None:
    if shutil.which("dpkg-query") is None:
        return None
    query = subprocess.run(
        ["dpkg-query", "-W", "-f=${Version}", package],
        capture_output=True,
        text=True,
        check=False,
    )
    return query.stdout.strip() or None


def check_ca_certificates(minimum: str) -> Result:
    installed = _dpkg_version("ca-certificates")
    if installed is None:
        return Result("CA-01", "UNVERIFIED", "ca-certificates version unknown (dpkg)")
    compare = subprocess.run(
        ["dpkg", "--compare-versions", installed, "ge", minimum], check=False
    )
    status = "PASS" if compare.returncode == 0 else "FAIL"
    return Result(
        "CA-01", status, f"ca-certificates {installed}, required >= {minimum}"
    )


def _capath_certificates(capath: str | None) -> list[bytes]:
    if not capath or not Path(capath).is_dir():
        return []
    certificates: list[bytes] = []
    for entry in sorted(Path(capath).iterdir()):
        if entry.is_file():
            certificates.extend(_pem_certificates(entry))
    return certificates


def check_system_store() -> Result:
    """Inspect the certificates OpenSSL actually loads for default contexts."""
    context = ssl.create_default_context()  # what aiohttp and urllib3 use
    loaded = context.get_ca_certs(binary_form=True)
    capath = _capath_certificates(ssl.get_default_verify_paths().capath)
    if not loaded and not capath:
        return Result("CA-02", "UNVERIFIED", "no system trust store was loaded")
    found = distrusted_in([*loaded, *capath])
    evidence = (
        f"{len(loaded)} certificates loaded from the default cafile, "
        f"{len(capath)} in the default capath"
    )
    if found:
        return Result("CA-02", "FAIL", f"{evidence}; trusted: {', '.join(found)}")
    return Result("CA-02", "PASS", f"{evidence}; no distrusted root")


def check_certifi(minimum: str) -> Result:
    try:
        installed = metadata.version("certifi")
    except metadata.PackageNotFoundError:
        return Result("CA-03", "NOT APPLICABLE", "certifi is not installed")
    try:
        import certifi
    except ImportError:
        return Result("CA-03", "UNVERIFIED", f"certifi {installed} cannot be imported")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    found = distrusted_in(context.get_ca_certs(binary_form=True))
    too_old = _version_tuple(installed) < _version_tuple(minimum)
    evidence = f"certifi {installed} (required >= {minimum}), bundle {certifi.where()}"
    if too_old or found:
        return Result(
            "CA-03", "FAIL", f"{evidence}; trusted: {', '.join(found) or '-'}"
        )
    return Result("CA-03", "PASS", f"{evidence}; no distrusted root")


def _bundle_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
        elif root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".pem", ".crt", ".cer"}:
                    yield path


def check_other_bundles(site_packages: list[Path]) -> Result:
    """Look for CA bundles outside certifi and the system store."""
    env_paths = [
        Path(os.environ[name]) for name in CA_BUNDLE_ENV_VARS if os.environ.get(name)
    ]
    certifi_dir = next(
        (p / "certifi" for p in site_packages if (p / "certifi").is_dir()), None
    )
    roots = dict.fromkeys([*OTHER_BUNDLE_ROOTS, *site_packages, *env_paths])
    candidates = [
        path
        for path in dict.fromkeys(_bundle_files(roots))
        if certifi_dir is None or certifi_dir not in path.parents
    ]
    findings: list[str] = []
    bundles = 0
    for path in candidates:
        certificates = list(_pem_certificates(path))
        bundles += bool(certificates)
        findings.extend(f"{path}: {name}" for name in distrusted_in(certificates))
    env_note = ", ".join(
        f"{name} set" for name in CA_BUNDLE_ENV_VARS if os.environ.get(name)
    )
    evidence = f"{bundles} other PEM bundles; CA env overrides: {env_note or 'none'}"
    if findings:
        return Result("CA-05", "FAIL", f"{evidence}; trusted: {'; '.join(findings)}")
    return Result("CA-05", "PASS", evidence)


def check_verification_enabled() -> Result:
    context = ssl.create_default_context()
    https_default = ssl._create_default_https_context  # what urllib uses
    problems = []
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        problems.append("default SSL context does not verify")
    if https_default is not ssl.create_default_context:
        problems.append("stdlib HTTPS uses an unverified context")
    if os.environ.get("PYTHONHTTPSVERIFY") == "0":
        problems.append("PYTHONHTTPSVERIFY=0")
    if problems:
        return Result("CA-06", "FAIL", "; ".join(problems))
    return Result(
        "CA-06", "PASS", "default contexts require verified certificates and hostnames"
    )


def check_uv(minimum: str) -> Result:
    uv = shutil.which("uv")
    if uv is None:
        return Result("CA-04", "UNVERIFIED", "uv not found on PATH")
    output = subprocess.run(
        [uv, "--version"], capture_output=True, text=True, check=False
    )
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", output.stdout)
    if match is None:
        return Result(
            "CA-04", "UNVERIFIED", f"cannot parse uv version: {output.stdout!r}"
        )
    installed = match.group(1)
    status = "PASS" if _version_tuple(installed) >= _version_tuple(minimum) else "FAIL"
    return Result("CA-04", status, f"uv {installed}, required >= {minimum}")


def run(mode: str, args: argparse.Namespace) -> list[Result]:
    if mode == "build":
        return [check_uv(args.min_uv)]
    site_packages = [
        Path(p)
        for p in sys.path
        if p.endswith(("site-packages", "dist-packages")) and Path(p).is_dir()
    ]
    return [
        check_ca_certificates(args.min_ca_certificates),
        check_system_store(),
        check_certifi(args.min_certifi),
        check_other_bundles(site_packages),
        check_verification_enabled(),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Certificate trust gate for container builds."
    )
    parser.add_argument("mode", choices=("build", "runtime"))
    parser.add_argument("--min-uv", default=MIN_UV)
    parser.add_argument("--min-certifi", default=MIN_CERTIFI)
    parser.add_argument("--min-ca-certificates", default=MIN_CA_CERTIFICATES)
    args = parser.parse_args(argv)

    results = run(args.mode, args)
    for result in results:
        print(f"ca-trust-gate {result.invariant} {result.status}: {result.evidence}")
    failed = [r.invariant for r in results if r.status in {"FAIL", "UNVERIFIED"}]
    if failed:
        print(f"ca-trust-gate: FAILED ({', '.join(failed)})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
