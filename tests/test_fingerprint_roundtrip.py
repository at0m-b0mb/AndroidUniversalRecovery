"""DeviceFingerprint JSON round-trip — guards against accidental schema drift."""

from __future__ import annotations

from pathlib import Path

from aur.device.fingerprint import DeviceFingerprint
from aur.device.partitions import PartitionEntry


def _sample() -> DeviceFingerprint:
    return DeviceFingerprint(
        serial="ABCDEF",
        codename="vayu",
        manufacturer="xiaomi",
        brand="POCO",
        model="POCO X3 Pro",
        platform="sm6150",
        arch="arm64-v8a",
        android_release="12",
        android_sdk="31",
        is_ab=True,
        has_dynamic_partitions=True,
        is_treble=True,
        bootloader="unknown",
        kernel_version="Linux localhost 4.19.157 ...",
        selected_props={"ro.product.device": "vayu"},
        all_props={"ro.product.device": "vayu", "ro.build.version.release": "12"},
        partitions=[
            PartitionEntry(name="boot_a", block_device="/dev/block/sda9",
                           size_bytes=104857600, source="/dev/block/by-name"),
            PartitionEntry(name="userdata", block_device="/dev/block/sda14",
                           size_bytes=128_000_000_000, source="/dev/block/by-name"),
        ],
        fstab_raw="/dev/block/by-name/userdata /data ext4 ...",
        recovery_fstab_raw="",
        rooted=False,
        in_recovery=False,
    )


def test_fingerprint_json_roundtrip(tmp_path: Path) -> None:
    fp = _sample()
    target = tmp_path / "fp.json"
    fp.save_json(target)
    assert target.exists()

    loaded = DeviceFingerprint.load_json(target)
    assert loaded.codename == fp.codename
    assert loaded.is_ab is True
    assert len(loaded.partitions) == 2
    assert loaded.partitions[0].block_device == "/dev/block/sda9"
    assert loaded.partitions[1].size_bytes == 128_000_000_000


def test_fingerprint_save_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c" / "fp.json"
    _sample().save_json(target)
    assert target.exists()
