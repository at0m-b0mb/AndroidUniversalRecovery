"""Tests for the partition-name resolver in RecoveryOps.

The interesting logic is A/B slot handling: ``boot`` on an A/B device with
active slot ``_a`` should resolve to ``boot_a``, but ``boot_b`` should also
resolve as itself (no double-suffixing).
"""

from __future__ import annotations

import pytest

from aur.device.adb import ADB
from aur.device.fingerprint import DeviceFingerprint
from aur.device.partitions import PartitionEntry
from aur.recovery_ops import RecoveryOps, RecoveryOpsError


class _NoopADB(ADB):
    def __init__(self) -> None:
        self._adb = "/usr/bin/false"
        self.serial = None


def _fp_ab_rooted(slot: str) -> DeviceFingerprint:
    return DeviceFingerprint(
        serial="x", codename="vayu", manufacturer="xiaomi",
        brand="POCO", model="POCO X3 Pro",
        platform="sm6150", arch="arm64-v8a",
        android_release="12", android_sdk="31",
        is_ab=True, has_dynamic_partitions=True, is_treble=True,
        bootloader="", kernel_version="",
        selected_props={}, all_props={"ro.boot.slot_suffix": slot},
        partitions=[
            PartitionEntry("boot_a", "/dev/block/sda9", 100_663_296, "by-name"),
            PartitionEntry("boot_b", "/dev/block/sda10", 100_663_296, "by-name"),
            PartitionEntry("userdata", "/dev/block/sda14", 0, "by-name"),
        ],
        fstab_raw="", recovery_fstab_raw="",
        rooted=True, in_recovery=False,
    )


def test_resolve_short_name_picks_active_slot() -> None:
    ops = RecoveryOps(_NoopADB(), _fp_ab_rooted("_a"))
    assert ops._resolve("boot").name == "boot_a"

    ops_b = RecoveryOps(_NoopADB(), _fp_ab_rooted("_b"))
    assert ops_b._resolve("boot").name == "boot_b"


def test_resolve_explicit_slot_kept() -> None:
    ops = RecoveryOps(_NoopADB(), _fp_ab_rooted("_a"))
    # Explicit boot_b on an A/B device with active _a should not be
    # silently rewritten to boot_a — that would be a footgun.
    assert ops._resolve("boot_b").name == "boot_b"


def test_resolve_unknown_partition_raises() -> None:
    ops = RecoveryOps(_NoopADB(), _fp_ab_rooted("_a"))
    with pytest.raises(RecoveryOpsError, match="not found"):
        ops._resolve("nonexistent")


def test_init_refuses_unrooted_normal_boot() -> None:
    fp = _fp_ab_rooted("_a")
    fp.rooted = False  # no root, not in recovery
    with pytest.raises(RecoveryOpsError, match="need root"):
        RecoveryOps(_NoopADB(), fp)
