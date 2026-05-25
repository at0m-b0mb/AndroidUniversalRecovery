"""TWRP device tree generator.

We delegate the hard work to ``twrpdtgen`` (which already knows how to read
header v0..v4 boot images and emit a working device tree), then post-process
the result with fingerprint data we collected from the live device — this
fills in gaps twrpdtgen leaves when only the image is available (e.g.
realistic partition sizes, A/B detection, vendor-specific props).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from aur.device.fingerprint import DeviceFingerprint


def generate_twrp_tree(*, fp: DeviceFingerprint, image: Path, out_root: Path) -> Path:
    """Generate a TWRP device tree under ``out_root/<vendor>/<codename>``.

    Returns the path to the generated tree directory.
    """
    try:
        from twrpdtgen.device_tree import DeviceTree  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "twrpdtgen is not installed. Run `pip install twrpdtgen`."
        ) from e

    output_path = out_root / "trees" / "twrp"
    output_path.mkdir(parents=True, exist_ok=True)

    # twrpdtgen >= 3.0 API: construct with the image only, then dump.
    # The constructor unpacks the image with AIKManager under the hood and
    # populates dt.device_info (codename / manufacturer / etc.).
    dt = DeviceTree(image)
    try:
        tree_dir = dt.dump_to_folder(output_path)
    finally:
        cleanup = getattr(dt, "cleanup", None)
        if callable(cleanup):
            cleanup()

    if not tree_dir.exists():
        # Some twrpdtgen builds return a relative path or place the tree under
        # a slightly different layout. Best-effort fall back.
        tree_dir = _find_tree_dir(output_path) or tree_dir

    _augment_tree(tree_dir, fp)
    return tree_dir


def _find_tree_dir(root: Path) -> Path | None:
    """Locate the first directory that looks like a device tree under root."""
    for path in root.rglob("BoardConfig.mk"):
        return path.parent
    return None


# --------------------------------------------------------------------------- #
# post-processing
# --------------------------------------------------------------------------- #

def _augment_tree(tree_dir: Path, fp: DeviceFingerprint) -> None:
    """Add fingerprint-derived hints alongside the twrpdtgen output."""
    notes = tree_dir / "AUR_NOTES.md"
    notes.write_text(_render_notes(fp))

    # Also drop the raw fingerprint for traceability.
    fp.save_json(tree_dir / "aur_fingerprint.json")

    # If the tree has a recovery.fstab and we have a richer one from the
    # device, save it side-by-side for the user to compare/merge.
    if fp.recovery_fstab_raw:
        (tree_dir / "device.recovery.fstab").write_text(fp.recovery_fstab_raw)
    if fp.fstab_raw:
        (tree_dir / "device.fstab").write_text(fp.fstab_raw)


def _render_notes(fp: DeviceFingerprint) -> str:
    parts: list[str] = []
    parts.append(f"# AUR generation notes for {fp.manufacturer}/{fp.codename}\n")
    parts.append(
        "This tree was produced by `twrpdtgen` and post-processed by AUR. "
        "Review the items below before building — generators cannot detect "
        "everything from a boot image alone.\n"
    )
    parts.append("## Device summary\n")
    parts.append(f"- Brand / model: **{fp.brand} / {fp.model}**")
    parts.append(f"- Platform: `{fp.platform}` (arch: `{fp.arch}`)")
    parts.append(f"- Android: {fp.android_release} (SDK {fp.android_sdk})")
    parts.append(f"- A/B device: {'**yes**' if fp.is_ab else 'no'}")
    parts.append(f"- Dynamic partitions / super: {'**yes**' if fp.has_dynamic_partitions else 'no'}")
    parts.append(f"- Treble: {'yes' if fp.is_treble else 'no'}")
    parts.append(f"- Bootloader: `{fp.bootloader}`")
    parts.append(f"- Kernel: `{fp.kernel_version}`\n")

    parts.append("## Things to verify before building\n")
    parts.append("- [ ] `BoardConfig.mk` flags match this device's SoC and partition scheme")
    parts.append("- [ ] `recovery.fstab` mount points match `device.recovery.fstab` / `device.fstab` (this dir)")
    parts.append("- [ ] Touch driver (init.recovery.<platform>.rc) loads for your panel")
    parts.append("- [ ] Display resolution / pixel format in BoardConfig.mk matches device")
    if fp.is_ab:
        parts.append("- [ ] A/B build flags present: `AB_OTA_UPDATER`, `BOARD_USES_RECOVERY_AS_BOOT` if applicable")
    if fp.has_dynamic_partitions:
        parts.append("- [ ] Dynamic partition / super flags: `BOARD_USES_RECOVERY_AS_BOOT` may be required; "
                     "consider `PRODUCT_USE_DYNAMIC_PARTITIONS := true`")
    if fp.platform.startswith("mt"):
        parts.append("- [ ] MediaTek device: check `BOARD_BOOTIMAGE_PARTITION_SIZE` and DA/auth requirements")
    parts.append("")
    parts.append("## Partition map seen on device\n")
    if not fp.partitions:
        parts.append("_(no partition information available — device was likely not rooted)_")
    else:
        parts.append("| Logical name | Block device | Size |")
        parts.append("|---|---|---|")
        for p in fp.partitions:
            size = _human_size(p.size_bytes)
            parts.append(f"| `{p.name}` | `{p.block_device}` | {size} |")
    parts.append("")
    return "\n".join(parts) + "\n"


def _human_size(n: int) -> str:
    if n <= 0:
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024 if unit == "B" else 1024
    return f"{n} TiB"
