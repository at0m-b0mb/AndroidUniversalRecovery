"""Device fingerprinting — collect everything we need from a connected phone
to drive device-tree generation downstream.

The fingerprint is the canonical input to the generators. It is also
serializable to JSON/YAML so a user can fingerprint a phone once and run the
generator offline later.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aur.device.adb import ADB
from aur.device.partitions import PartitionEntry, read_partitions

# Properties we care about. We pull the full getprop dump anyway, but this
# named subset is what flows directly into the device tree.
INTERESTING_PROPS = (
    "ro.product.device",
    "ro.product.vendor.device",
    "ro.product.model",
    "ro.product.vendor.model",
    "ro.product.brand",
    "ro.product.vendor.brand",
    "ro.product.manufacturer",
    "ro.product.vendor.manufacturer",
    "ro.product.name",
    "ro.product.cpu.abi",
    "ro.product.cpu.abilist",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.fingerprint",
    "ro.bootloader",
    "ro.board.platform",
    "ro.hardware",
    "ro.hardware.chipname",
    "ro.boot.hardware.platform",
    "ro.boot.hardware.sku",
    "ro.boot.bootloader",
    "ro.boot.slot_suffix",          # presence => A/B device
    "ro.boot.dynamic_partitions",   # "true" => dynamic partitions / super
    "ro.boot.vbmeta.device_state",
    "ro.boot.verifiedbootstate",
    "ro.treble.enabled",
    "ro.product.first_api_level",
    "ro.build.ab_update",
)


@dataclass
class DeviceFingerprint:
    """Everything we know about the connected device after fingerprinting."""

    serial: str
    codename: str
    manufacturer: str
    brand: str
    model: str
    platform: str          # e.g. "mt6765", "sdm660"
    arch: str              # e.g. "arm64-v8a"
    android_release: str   # e.g. "8.1.0"
    android_sdk: str       # e.g. "27"
    is_ab: bool
    has_dynamic_partitions: bool
    is_treble: bool
    bootloader: str
    kernel_version: str
    selected_props: dict[str, str] = field(default_factory=dict)
    all_props: dict[str, str] = field(default_factory=dict)
    partitions: list[PartitionEntry] = field(default_factory=list)
    fstab_raw: str = ""
    recovery_fstab_raw: str = ""
    rooted: bool = False
    in_recovery: bool = False

    # --------- (de)serialization ---------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["partitions"] = [p.to_dict() for p in self.partitions]
        return d

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))

    @classmethod
    def load_json(cls, path: Path) -> "DeviceFingerprint":
        raw = json.loads(path.read_text())
        raw["partitions"] = [PartitionEntry(**p) for p in raw.get("partitions", [])]
        return cls(**raw)


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #

_GETPROP_LINE = re.compile(r"^\[(?P<k>[^\]]+)\]:\s*\[(?P<v>.*)\]\s*$")


def _parse_getprop(dump: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in dump.splitlines():
        m = _GETPROP_LINE.match(line.strip())
        if m:
            out[m.group("k")] = m.group("v")
    return out


def _first_nonempty(props: dict[str, str], *keys: str) -> str:
    for k in keys:
        v = props.get(k)
        if v:
            return v
    return ""


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# main entrypoint
# --------------------------------------------------------------------------- #

def fingerprint_device(adb: ADB) -> DeviceFingerprint:
    """Collect a full fingerprint from a connected device.

    The device should be in 'device' state (normal boot) for best results.
    Recovery mode also works for most fields but partition info and props
    will be sparser.
    """
    raw = adb.getprop()
    all_props = _parse_getprop(raw)
    # Empty getprop means the device isn't actually responsive (offline,
    # unauthorized, or stuck in fastboot which doesn't expose a shell).
    # Refusing here beats silently writing a `unknown/unknown` fingerprint.
    if not all_props:
        raise RuntimeError(
            "getprop returned no recognisable lines. Check `adb devices` — the "
            "device may be unauthorized, offline, or in fastboot. "
            "(Raw output was: " + repr(raw[:120]) + (")" if len(raw) <= 120 else "…)")
        )
    selected = {k: all_props.get(k, "") for k in INTERESTING_PROPS}

    codename = _first_nonempty(
        all_props, "ro.product.device", "ro.product.vendor.device", "ro.boot.hardware.sku"
    ) or "unknown"
    manufacturer = _first_nonempty(
        all_props, "ro.product.manufacturer", "ro.product.vendor.manufacturer"
    ).lower() or "unknown"
    brand = _first_nonempty(all_props, "ro.product.brand", "ro.product.vendor.brand") or manufacturer
    model = _first_nonempty(all_props, "ro.product.model", "ro.product.vendor.model") or codename
    platform = _first_nonempty(
        all_props, "ro.board.platform", "ro.hardware", "ro.boot.hardware.platform"
    ) or "unknown"
    arch = all_props.get("ro.product.cpu.abi") or "unknown"
    android_release = all_props.get("ro.build.version.release", "")
    android_sdk = all_props.get("ro.build.version.sdk", "")
    bootloader = _first_nonempty(all_props, "ro.bootloader", "ro.boot.bootloader")

    is_ab = bool(all_props.get("ro.boot.slot_suffix")) or _truthy(all_props.get("ro.build.ab_update"))
    has_dyn = _truthy(all_props.get("ro.boot.dynamic_partitions"))
    is_treble = _truthy(all_props.get("ro.treble.enabled"))

    # kernel
    try:
        kernel_version = adb.shell("uname -a", check=False).strip()
    except Exception:
        kernel_version = ""

    # fstabs (best effort — paths vary)
    fstab_raw = _try_read_first(
        adb,
        "/vendor/etc/fstab.*",
        "/odm/etc/fstab.*",
        "/etc/fstab.*",
        "/fstab.*",
    )
    recovery_fstab_raw = _try_read_first(adb, "/etc/recovery.fstab", "/system/etc/recovery.fstab")

    partitions = read_partitions(adb)

    return DeviceFingerprint(
        serial=adb.serial or "(default)",
        codename=codename,
        manufacturer=manufacturer,
        brand=brand,
        model=model,
        platform=platform,
        arch=arch,
        android_release=android_release,
        android_sdk=android_sdk,
        is_ab=is_ab,
        has_dynamic_partitions=has_dyn,
        is_treble=is_treble,
        bootloader=bootloader,
        kernel_version=kernel_version,
        selected_props=selected,
        all_props=all_props,
        partitions=partitions,
        fstab_raw=fstab_raw,
        recovery_fstab_raw=recovery_fstab_raw,
        rooted=adb.is_rooted(),
        in_recovery=adb.in_recovery(),
    )


def _try_read_first(adb: ADB, *globs: str) -> str:
    """Try to read the first matching path on the device, returning '' if none."""
    for glob in globs:
        out = adb.shell(f"sh -c 'for f in {glob}; do [ -f \"$f\" ] && cat \"$f\" && exit 0; done'", check=False)
        if out and out.strip():
            return out
    return ""
