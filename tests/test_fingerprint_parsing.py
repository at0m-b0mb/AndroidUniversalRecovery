"""Tests for the pure parsing helpers in aur.device.fingerprint.

These don't need a real device — they exercise the regex/dict parsing on
captured ``getprop`` output. Capture corpus lives in ``tests/fixtures/``.
"""

from __future__ import annotations

from aur.device.fingerprint import _parse_getprop, _truthy


def test_parse_getprop_basic_lines() -> None:
    dump = (
        "[ro.product.device]: [vayu]\n"
        "[ro.product.brand]: [Xiaomi]\n"
        "[ro.build.version.release]: [12]\n"
    )
    out = _parse_getprop(dump)
    assert out["ro.product.device"] == "vayu"
    assert out["ro.product.brand"] == "Xiaomi"
    assert out["ro.build.version.release"] == "12"


def test_parse_getprop_empty_value_kept() -> None:
    out = _parse_getprop("[some.empty.key]: []\n")
    assert out == {"some.empty.key": ""}


def test_parse_getprop_skips_garbage() -> None:
    dump = (
        "[ok.key]: [value]\n"
        "not a getprop line\n"
        "[]: []\n"                 # empty key — regex rejects
        "[k.with-special!@#]: [v ]\n"
    )
    out = _parse_getprop(dump)
    assert out["ok.key"] == "value"
    assert "k.with-special!@#" in out
    # The trailing space in the captured value is preserved by the regex.
    assert out["k.with-special!@#"] == "v "


def test_parse_getprop_value_with_brackets_inside() -> None:
    # Values containing ']' would break a naive parser. Our regex is greedy
    # up to the last ']' on the line.
    dump = "[ro.product.fingerprint]: [Xiaomi/vayu/vayu:12/SKQ1.211006.001/V13:user/release-keys]\n"
    out = _parse_getprop(dump)
    assert out["ro.product.fingerprint"].endswith("release-keys")


def test_truthy_handles_common_forms() -> None:
    assert _truthy("true")
    assert _truthy("True")
    assert _truthy("1")
    assert _truthy("yes")
    assert not _truthy("false")
    assert not _truthy("0")
    assert not _truthy("")
    assert not _truthy(None)
