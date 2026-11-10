"""`MAITY_TEST_SHARD` (tests/conftest.py, CI's `hub-postgresql`): only `<k>/<n>` in ASCII digits
with 1 <= k <= n is a shard; anything else is a usage error, never an internal one (review of
#1625: `str.isdigit` took "²")."""

from __future__ import annotations

import pytest

from tests.conftest import _shard


@pytest.mark.parametrize(
    ("raw", "want"), [("", None), (" ", None), ("1/3", (1, 3)), ("3/3", (3, 3)), (" 2/3 ", (2, 3))]
)
def test_a_shard_or_the_whole_suite(
    monkeypatch: pytest.MonkeyPatch, raw: str, want: tuple[int, int] | None
) -> None:
    monkeypatch.setenv("MAITY_TEST_SHARD", raw)
    assert _shard() == want


@pytest.mark.parametrize(
    "raw", ["0/3", "4/3", "x", "1", "1/", "/3", "1/3/3", "-1/3", "²/3", "1/²", "١/3", "1 /3"]
)
def test_any_other_value_is_a_usage_error(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("MAITY_TEST_SHARD", raw)
    with pytest.raises(pytest.UsageError):
        _shard()
