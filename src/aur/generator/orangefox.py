"""OrangeFox device tree overlay.

OrangeFox uses the same device-tree contract as TWRP plus a small set of
additional flags and an ``OF_*`` block in ``BoardConfig.mk``. Rather than
fork twrpdtgen, we copy the TWRP tree to a new path and apply the overlay
in place.

References:
  https://wiki.orangefox.tech/en/dev/building-howto
  https://wiki.orangefox.tech/en/dev/device-tree-flags
"""

from __future__ import annotations

import shutil
from pathlib import Path

from aur.device.fingerprint import DeviceFingerprint


# Sensible defaults for OrangeFox 12.1 (R12.1). Users can tune later.
DEFAULT_OF_FLAGS: dict[str, str] = {
    "FOX_VERSION": "R12.1",
    "OF_MAINTAINER": "AUR-generated",
    "OF_USE_GREEN_LED": "0",
    "OF_SCREEN_H": "1920",     # placeholder — overwritten if we detect height
    "OF_STATUS_H": "100",
    "OF_STATUS_INDENT_LEFT": "48",
    "OF_STATUS_INDENT_RIGHT": "48",
    "OF_ALLOW_DISABLE_NAVBAR": "0",
    "OF_USE_LOCKSCREEN_BUTTON": "1",
    "OF_FLASHLIGHT_ENABLE": "0",
    "OF_ENABLE_LPTOOLS": "1",
    "OF_QUICK_BACKUP_LIST": "/boot;/data;/system;/vendor;",
    "OF_PATCH_AVB20": "1",
    "OF_NO_TREBLE_COMPATIBILITY_CHECK": "1",
}


def orangefox_overlay(*, fp: DeviceFingerprint, twrp_tree: Path, out_root: Path) -> Path:
    """Copy the TWRP tree to an OrangeFox path and apply the overlay."""
    of_root = out_root / "trees" / "orangefox" / fp.manufacturer / fp.codename
    if of_root.exists():
        shutil.rmtree(of_root)
    of_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(twrp_tree, of_root)

    _patch_board_config(of_root / "BoardConfig.mk", fp)
    _write_vendorsetup(of_root / "vendorsetup.sh", fp)
    _write_recovery_collection(of_root / "recovery", fp)
    _drop_overlay_notes(of_root / "AUR_NOTES.md", fp)
    return of_root


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _patch_board_config(board_config: Path, fp: DeviceFingerprint) -> None:
    """Append an OrangeFox flag block to BoardConfig.mk, idempotently."""
    if not board_config.exists():
        # twrpdtgen failed to produce a BoardConfig — create a stub so the
        # overlay block still has a home.
        board_config.write_text(
            f"# AUR stub BoardConfig.mk for {fp.manufacturer}/{fp.codename}\n"
            "# twrpdtgen did not produce BoardConfig.mk; you must hand-write the\n"
            "# device flags before building (see ./AUR_NOTES.md).\n\n"
        )

    existing = board_config.read_text()
    if "# === OrangeFox (added by AUR)" in existing:
        return  # already overlaid

    flags = dict(DEFAULT_OF_FLAGS)
    if fp.has_dynamic_partitions:
        flags["OF_DYNAMIC_PARTITIONS"] = "1"
    if fp.is_ab:
        flags["OF_AB_DEVICE"] = "1"
        flags["OF_VIRTUAL_AB_DEVICE"] = "1" if _looks_vab(fp) else "0"
    if fp.platform.startswith("mt"):
        flags["OF_NO_RELOAD_AFTER_DECRYPTION"] = "1"

    block = ["", "# === OrangeFox (added by AUR) ==="]
    for k, v in flags.items():
        block.append(f"{k} := {v}")
    block.append("# === end OrangeFox ===", )
    block.append("")
    board_config.write_text(existing.rstrip() + "\n" + "\n".join(block))


def _write_vendorsetup(path: Path, fp: DeviceFingerprint) -> None:
    """Minimal vendorsetup.sh — OrangeFox sources it during lunch."""
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"# AUR-generated vendorsetup.sh for {fp.manufacturer}/{fp.codename}\n"
        "# OrangeFox reads OF_* exports from here at lunch time.\n"
        "\n"
        "export ALLOW_MISSING_DEPENDENCIES=true\n"
        "export FOX_BUILD_DEVICE=" + fp.codename + "\n"
        "export LC_ALL=\"C\"\n"
    )
    path.chmod(0o755)


def _write_recovery_collection(recovery_dir: Path, fp: DeviceFingerprint) -> None:
    """Write a placeholder ``recovery.fstab`` collection if missing.

    Real recovery.fstab generation is best-effort and depends on
    ``fp.recovery_fstab_raw`` or ``fp.fstab_raw`` — both of which may be
    empty when the device isn't rooted.
    """
    recovery_dir.mkdir(parents=True, exist_ok=True)
    fstab_target = recovery_dir / "recovery.fstab"
    if fstab_target.exists():
        return

    if fp.recovery_fstab_raw:
        fstab_target.write_text(fp.recovery_fstab_raw)
    elif fp.fstab_raw:
        fstab_target.write_text(
            "# AUR: this is the live device fstab — convert it to recovery.fstab format manually.\n"
            "# See https://wiki.orangefox.tech/en/dev/recovery-fstab\n\n"
            + fp.fstab_raw
        )
    else:
        fstab_target.write_text(
            "# AUR placeholder — no fstab could be read from the device.\n"
            "# Hand-write this file. Reference: https://wiki.orangefox.tech/en/dev/recovery-fstab\n"
        )


def _drop_overlay_notes(notes_path: Path, fp: DeviceFingerprint) -> None:
    extra = (
        "\n## OrangeFox overlay applied\n"
        "- Added OF_* block to `BoardConfig.mk` — review screen height / quick-backup list\n"
        "- Wrote `vendorsetup.sh` exporting `FOX_BUILD_DEVICE`\n"
        "- Placeholder `recovery/recovery.fstab` written (may need hand-edit)\n"
        "- Build with the OrangeFox manifest: "
        "https://gitlab.com/OrangeFox/sync\n"
    )
    if notes_path.exists():
        notes_path.write_text(notes_path.read_text() + extra)
    else:
        notes_path.write_text(extra)


def _looks_vab(fp: DeviceFingerprint) -> bool:
    """Heuristic for Virtual A/B."""
    return (
        fp.has_dynamic_partitions
        and any(p.name.startswith("super") for p in fp.partitions)
        and fp.is_ab
    )
