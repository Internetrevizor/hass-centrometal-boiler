"""TLS policy tests.

Centrometal's public endpoint may present an incomplete certificate chain on
some Home Assistant hosts. Default mode is therefore ``off`` so installations do
not fill the log with certificate fallback warnings. Users can force strict
verification with ``CENTROMETAL_VERIFY_SSL=1`` or use ``auto`` to try verified
TLS first and fallback only on certificate errors.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "centrometal_boiler"))

from centrometal_web_boiler.HttpClient import (  # noqa: E402
    TLS_VERIFY_ENV,
    _ssl_request_value,
    _tls_verify_mode,
)


def test_tls_default_is_off(monkeypatch) -> None:
    monkeypatch.delenv(TLS_VERIFY_ENV, raising=False)
    assert _tls_verify_mode() == "off"
    assert _ssl_request_value() is False


def test_tls_strict_env(monkeypatch) -> None:
    monkeypatch.setenv(TLS_VERIFY_ENV, "1")
    assert _tls_verify_mode() == "strict"
    assert _ssl_request_value() is None


def test_tls_off_env(monkeypatch) -> None:
    monkeypatch.setenv(TLS_VERIFY_ENV, "0")
    assert _tls_verify_mode() == "off"
    assert _ssl_request_value() is False


def test_tls_auto_env(monkeypatch) -> None:
    monkeypatch.setenv(TLS_VERIFY_ENV, "auto")
    assert _tls_verify_mode() == "auto"
    assert _ssl_request_value() is None


def test_tls_unknown_env_falls_back_to_off(monkeypatch) -> None:
    monkeypatch.setenv(TLS_VERIFY_ENV, "unexpected")
    assert _tls_verify_mode() == "off"
    assert _ssl_request_value() is False
