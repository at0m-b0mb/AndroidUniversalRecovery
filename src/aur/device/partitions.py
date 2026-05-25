"""Partition map extraction.

Android partition layouts come from three places that disagree more often
than you'd expect:

1. ``/proc/partitions`` — kernel's view, no names.
2. ``ls -l /dev/block/by-name/`` — symlinks from logical name → block device.
3. ``/dev/block/bootdevice/by-name/`` — same idea, vendor-specific path.

We read all three and merge. Sizes (when readable) come from
``cat /sys/block/<dev>/size`` × 512.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from aur.device.adb import ADB


@dataclass(frozen=True)
class PartitionEntry:
    name: str               # logical name e.g. "boot", "recovery", "userdata"
    block_device: str       # resolved block device e.g. "/dev/block/mmcblk0p23"
    size_bytes: int = 0
    source: str = ""        # which lookup path we found this on

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


# Logical names a recovery generator cares about. Everything else gets
# collected but is informational.
RECOVERY_RELEVANT = frozenset({
    "boot", "boot_a", "boot_b",
    "recovery", "recovery_a", "recovery_b",
    "vendor_boot", "vendor_boot_a", "vendor_boot_b",
    "init_boot", "init_boot_a", "init_boot_b",
    "system", "system_a", "system_b",
    "vendor", "vendor_a", "vendor_b",
    "userdata", "data", "metadata", "misc",
    "dtbo", "dtbo_a", "dtbo_b",
    "vbmeta", "vbmeta_a", "vbmeta_b", "vbmeta_system", "vbmeta_vendor",
    "super",
    "cache", "persist", "modem", "nvram", "nvdata", "protect_f", "protect_s",
    "logo", "logo_a", "logo_b",
})


def _ls_dir(adb: ADB, path: str) -> list[tuple[str, str]]:
    """Return (name, resolved_target) pairs from ``ls -l <path>``.

    Android ships several different ``ls`` implementations (toybox, busybox,
    AOSP) with different field counts. Instead of matching the whole line,
    we look for the ``->`` symlink arrow and take the names on either side.

    Returns [] if the directory doesn't exist or isn't readable.
    """
    out = adb.shell(f"ls -l {path} 2>/dev/null", check=False)
    pairs: list[tuple[str, str]] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or " -> " not in line:
            continue
        left, _, target = line.partition(" -> ")
        target = target.strip()
        name = left.rsplit(None, 1)[-1]  # last whitespace-separated token
        if name in ("", ".", ".."):
            continue
        if target.startswith("/"):
            resolved = target
        else:
            resolved = f"{path.rstrip('/')}/{target}"
            # normalise ../ segments
            while "/../" in resolved:
                resolved = re.sub(r"/[^/]+/\.\./", "/", resolved)
            resolved = resolved.replace("/./", "/")
        pairs.append((name, resolved))
    return pairs


def _read_size_bytes(adb: ADB, block_device: str) -> int:
    """`/sys/block/<basename>/size` is in 512-byte sectors. 0 on failure."""
    base = block_device.rsplit("/", 1)[-1]
    out = adb.shell(
        f"sh -c 'for p in /sys/block/{base}/size /sys/class/block/{base}/size; "
        f"do [ -f \"$p\" ] && cat \"$p\" && exit 0; done' 2>/dev/null",
        check=False,
    ).strip()
    try:
        return int(out) * 512
    except (TypeError, ValueError):
        return 0


def read_partitions(adb: ADB) -> list[PartitionEntry]:
    """Best-effort partition map. Returns [] if nothing readable was found."""
    candidates: dict[str, PartitionEntry] = {}

    for path in ("/dev/block/by-name", "/dev/block/bootdevice/by-name", "/dev/block/platform"):
        for name, target in _ls_dir(adb, path):
            if name in candidates:
                continue
            size = _read_size_bytes(adb, target)
            candidates[name] = PartitionEntry(
                name=name, block_device=target, size_bytes=size, source=path
            )

    # Sort: recovery-relevant first (alphabetical), then everything else.
    def sort_key(p: PartitionEntry) -> tuple[int, str]:
        return (0 if p.name in RECOVERY_RELEVANT else 1, p.name)

    return sorted(candidates.values(), key=sort_key)
