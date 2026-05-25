"""Tests for the ``ls -l`` partition parser in aur.device.partitions.

The parser has to handle three flavours of ``ls`` output (toybox / AOSP /
busybox). The fixtures here cover one example of each.
"""

from __future__ import annotations

from unittest.mock import patch

from aur.device.adb import ADB
from aur.device.partitions import _ls_dir


# Real toybox ls -l /dev/block/by-name output (paraphrased from a Pixel 6).
TOYBOX = """\
total 0
lrwxrwxrwx 1 root root 22 2024-01-15 09:33 boot_a -> /dev/block/sda9
lrwxrwxrwx 1 root root 22 2024-01-15 09:33 boot_b -> /dev/block/sda10
lrwxrwxrwx 1 root root 23 2024-01-15 09:33 super -> /dev/block/sda13
lrwxrwxrwx 1 root root 22 2024-01-15 09:33 userdata -> /dev/block/sda14
"""

# AOSP ls -l (older, MTK device).
AOSP_MTK = """\
total 0
lrwxrwxrwx root     root              2018-01-01 00:00 boot -> /dev/block/mmcblk0p35
lrwxrwxrwx root     root              2018-01-01 00:00 recovery -> /dev/block/mmcblk0p36
lrwxrwxrwx root     root              2018-01-01 00:00 userdata -> /dev/block/mmcblk0p51
"""

# Busybox-style with relative symlinks.
BUSYBOX = """\
lrwxrwxrwx 1 root root 22 Jan  1 00:00 boot -> ../../../mmcblk0p35
lrwxrwxrwx 1 root root 22 Jan  1 00:00 recovery -> ../../../mmcblk0p36
"""


class _StubADB(ADB):
    """ADB stub that returns a canned string from ``shell()``."""

    def __init__(self, canned: str):
        # Skip the real ADB.__init__ — we don't need the binary lookup.
        self._adb = "/usr/bin/false"
        self.serial = None
        self._canned = canned

    def shell(self, command: str, timeout: float = 30.0, check: bool = True) -> str:  # type: ignore[override]
        return self._canned


def test_ls_dir_parses_toybox_output() -> None:
    adb = _StubADB(TOYBOX)
    pairs = _ls_dir(adb, "/dev/block/by-name")
    by_name = dict(pairs)
    assert by_name["boot_a"] == "/dev/block/sda9"
    assert by_name["boot_b"] == "/dev/block/sda10"
    assert by_name["super"] == "/dev/block/sda13"
    assert by_name["userdata"] == "/dev/block/sda14"
    assert len(pairs) == 4


def test_ls_dir_parses_aosp_output() -> None:
    adb = _StubADB(AOSP_MTK)
    pairs = _ls_dir(adb, "/dev/block/by-name")
    by_name = dict(pairs)
    assert by_name["boot"] == "/dev/block/mmcblk0p35"
    assert by_name["recovery"] == "/dev/block/mmcblk0p36"
    assert by_name["userdata"] == "/dev/block/mmcblk0p51"


def test_ls_dir_resolves_relative_targets() -> None:
    adb = _StubADB(BUSYBOX)
    pairs = _ls_dir(adb, "/dev/block/platform/bootdevice/by-name")
    by_name = dict(pairs)
    # Three "../" segments collapse the by-name/platform/bootdevice prefix.
    assert by_name["boot"].endswith("/mmcblk0p35")
    assert by_name["recovery"].endswith("/mmcblk0p36")
    # No "../" should survive normalisation.
    assert "/../" not in by_name["boot"]


def test_ls_dir_empty_input_returns_empty() -> None:
    assert _ls_dir(_StubADB(""), "/nope") == []
