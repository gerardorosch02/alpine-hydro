"""ENTSO-E errors must never carry the API key."""

import traceback

import pytest

from alpinehydro.fetch.entsoe import _SafeClient, redact

URL = "https://web-api.tp.entsoe.eu/api?documentType=A75&securityToken=abc-123-SECRET&periodStart=1"


class _Failing:
    def query_generation(self, *a, **k):
        raise ValueError(f"599 Server Error for url: {URL}")


def test_redact_removes_token():
    assert "SECRET" not in redact(URL)
    assert "securityToken=REDACTED&periodStart=1" in redact(URL)


def test_safe_client_error_and_traceback_hold_no_token():
    with pytest.raises(RuntimeError) as info:
        _SafeClient(_Failing()).query_generation("DE")
    assert "SECRET" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None
    text = "".join(traceback.format_exception(info.value))
    assert "SECRET" not in text
