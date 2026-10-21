from __future__ import annotations

import importlib.util
import ssl
import sys
from pathlib import Path
from types import ModuleType

import certifi
import pytest

GATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ca_trust_gate.py"

# Ubuntu's emSign_ECC_Root_CA_-_G3.crt, removed by USN-8944-1.
EMSIGN_ECC_ROOT_G3_PEM = """-----BEGIN CERTIFICATE-----
MIICTjCCAdOgAwIBAgIKPPYHqWhwDtqLhDAKBggqhkjOPQQDAzBrMQswCQYDVQQG
EwJJTjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNo
bm9sb2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0g
RzMwHhcNMTgwMjE4MTgzMDAwWhcNNDMwMjE4MTgzMDAwWjBrMQswCQYDVQQGEwJJ
TjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNobm9s
b2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0gRzMw
djAQBgcqhkjOPQIBBgUrgQQAIgNiAAQjpQy4LRL1KPOxst3iAhKAnjlfSU2fySU0
WXTsuwYc58Byr+iuL+FBVIcUqEqy6HyC5ltqtdyzdc6LBtCGI79G1Y4PPwT01xyS
fvalY8L1X44uT6EYGQIrMgqCZH0Wk9GjQjBAMB0GA1UdDgQWBBR8XQKEE9TMipuB
zhccLikenEhjQjAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB/zAKBggq
hkjOPQQDAwNpADBmAjEAvvNhzwIQHWSVB7gYboiFBS+DCBeQyh+KTOgNG3qxrdWB
CUfvO6wIBHxcmbHtRwfSAjEAnbpV/KlK6O3t5nYBQnvI+GDZjVGLVTv7jHvrZQnD
+JbNR6iC8hZVdyR+EhCVBCyj
-----END CERTIFICATE-----
"""


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ca_trust_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_distrusted_root_is_found(gate: ModuleType) -> None:
    der = ssl.PEM_cert_to_DER_cert(EMSIGN_ECC_ROOT_G3_PEM)

    assert gate.distrusted_in([der]) == ["emSign ECC Root CA - G3 (86a1ecba089c4a8d…)"]


def test_bundle_with_the_root_is_flagged(gate: ModuleType, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.pem"
    bundle.write_text(Path(certifi.where()).read_text() + EMSIGN_ECC_ROOT_G3_PEM)

    assert gate.distrusted_in(gate._pem_certificates(bundle))


def test_locked_certifi_passes(gate: ModuleType) -> None:
    result = gate.check_certifi(gate.MIN_CERTIFI)

    assert result.status == "PASS", result.evidence


def test_older_certifi_fails(gate: ModuleType) -> None:
    assert gate.check_certifi("9999.1.1").status == "FAIL"


@pytest.mark.parametrize(
    ("statuses", "exit_code"),
    [
        (("PASS", "NOT APPLICABLE"), 0),
        (("PASS", "UNVERIFIED"), 1),
        (("FAIL",), 1),
    ],
)
def test_gate_fails_unless_everything_is_confirmed(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    statuses: tuple[str, ...],
    exit_code: int,
) -> None:
    results = [gate.Result(f"CA-0{i}", s, "-") for i, s in enumerate(statuses, 1)]
    monkeypatch.setattr(gate, "run", lambda mode, args: results)

    assert gate.main(["runtime"]) == exit_code


def test_versions_compare_numerically(gate: ModuleType) -> None:
    assert gate._version_tuple("0.13.10") > gate._version_tuple("0.13.4")
    assert gate._version_tuple("2026.10.19") > gate._version_tuple("2026.10.18")
