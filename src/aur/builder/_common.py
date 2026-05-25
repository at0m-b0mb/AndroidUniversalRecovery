"""Shared helpers for the build-plan renderers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TreeInfo:
    """Things every renderer needs to know about the generated tree."""

    base: str               # "twrp" | "orangefox"
    tree_dir: Path
    vendor: str             # e.g. "xiaomi"
    codename: str           # e.g. "vayu"
    is_ab: bool
    has_dynamic_partitions: bool
    platform: str
    android_sdk: int        # source-of-truth for branch selection (29..34+)

    # AOSP source manifest the build will sync.
    @property
    def manifest_url(self) -> str:
        return {
            "twrp": "https://github.com/minimal-manifest-twrp/platform_manifest_twrp_aosp.git",
            "orangefox": "https://gitlab.com/OrangeFox/sync.git",
        }[self.base]

    @property
    def manifest_branch(self) -> str:
        """Pick the right manifest branch based on the device's Android level.

        Both TWRP and OrangeFox currently ship a `12.1` branch (Android 12L
        and earlier sources) and a `14.1` branch (Android 14 sources).
        Devices on SDK 33 (Android 13) and above build best from `14.1`;
        anything older uses `12.1`.
        """
        use_14 = self.android_sdk >= 33
        return {
            "twrp":      "twrp-14.1" if use_14 else "twrp-12.1",
            "orangefox": "14.1"       if use_14 else "12.1",
        }[self.base]

    @property
    def lunch_combo(self) -> str:
        return {
            "twrp": f"twrp_{self.codename}-eng",
            "orangefox": f"omni_{self.codename}-eng",
        }[self.base]

    @property
    def build_target(self) -> str:
        # vendor_boot for newer A/B+VAB, otherwise recoveryimage.
        if self.has_dynamic_partitions and self.is_ab:
            return "bootimage"
        return "recoveryimage"

    @property
    def device_tree_subpath(self) -> str:
        return f"device/{self.vendor}/{self.codename}"


def load_tree_info(tree_dir: Path, base: str) -> TreeInfo:
    """Read aur_fingerprint.json next to the tree and build TreeInfo."""
    fp_path = tree_dir / "aur_fingerprint.json"
    if not fp_path.exists():
        raise FileNotFoundError(
            f"expected {fp_path} (written by the generator). "
            f"Was this tree produced by AUR?"
        )
    raw = json.loads(fp_path.read_text())
    try:
        android_sdk = int(raw.get("android_sdk") or 0)
    except (TypeError, ValueError):
        android_sdk = 0
    return TreeInfo(
        base=base,
        tree_dir=tree_dir,
        vendor=(raw.get("manufacturer") or "unknown").lower(),
        codename=(raw.get("codename") or "unknown").lower(),
        is_ab=bool(raw.get("is_ab")),
        has_dynamic_partitions=bool(raw.get("has_dynamic_partitions")),
        platform=raw.get("platform") or "",
        android_sdk=android_sdk,
    )


def write(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(0o755)
