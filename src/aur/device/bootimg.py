"""Pull and unpack boot.img / recovery.img from a connected device.

We try, in order:
  1. ``adb pull`` from a known stock path on a rooted device.
  2. ``dd if=<partition> of=/sdcard/...`` then pull (rooted).
  3. Give up and tell the caller to provide the image manually.

Unpacking is delegated to twrpdtgen's internal helpers when present;
otherwise we fall back to ``unpackbootimg`` on PATH. We don't reimplement
the boot image format — both upstream tools track header v0..v4 variants.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aur.device.adb import ADB, ADBError
from aur.device.fingerprint import DeviceFingerprint


@dataclass
class PulledImage:
    """Result of acquiring a boot-class image from a device."""

    kind: str           # "boot" | "recovery" | "vendor_boot" | "init_boot"
    local_path: Path
    source_path: str    # where on the device it came from
    method: str         # "pull" | "dd" | "manual"


def _find_partition(fp: DeviceFingerprint, kind: str) -> str | None:
    """Return the device block path for a logical partition (handles A/B slot).

    Picks the active slot when the device is A/B; falls back to legacy
    unslotted name otherwise.
    """
    slot_suffix = fp.all_props.get("ro.boot.slot_suffix", "") if fp.is_ab else ""
    candidates = [f"{kind}{slot_suffix}", kind] if slot_suffix else [kind]
    for cand in candidates:
        for part in fp.partitions:
            if part.name == cand:
                return part.block_device
    return None


def pull_image(adb: ADB, fp: DeviceFingerprint, kind: str, out_dir: Path) -> PulledImage:
    """Pull a boot-class image off the device.

    ``kind`` is one of: "boot", "recovery", "vendor_boot", "init_boot".
    Raises ``ADBError`` if no method works.
    """
    if kind not in {"boot", "recovery", "vendor_boot", "init_boot"}:
        raise ValueError(f"unsupported image kind: {kind}")

    out_dir.mkdir(parents=True, exist_ok=True)
    local_path = out_dir / f"{kind}.img"

    block = _find_partition(fp, kind)
    if not block:
        raise ADBError(
            f"could not find {kind!r} partition on device. "
            f"Known partitions: {[p.name for p in fp.partitions]}. "
            f"Provide the image manually via --image."
        )

    if not fp.rooted:
        raise ADBError(
            f"pulling {kind}.img requires root (su) or a custom recovery already on the "
            f"device. Found block device {block} but cannot read it as shell user. "
            f"Either root the device, boot a temporary recovery, or supply the image "
            f"file manually."
        )

    # dd to /data/local/tmp (always present, writable by the shell user, and
    # mounted in both normal boot and TWRP/OrangeFox). /sdcard would be more
    # obvious but is scoped storage on Android 11+ and can be unmounted in
    # recovery mode — too fragile for a tool that needs to work everywhere.
    remote_tmp = f"/data/local/tmp/aur-{kind}.img"
    cmd = f"su -c 'dd if={block} of={remote_tmp} bs=4M' 2>&1"
    out = adb.shell(cmd, timeout=600)
    # toybox/busybox dd prints "<n> records in / <n> records out" on success.
    # An unrelated "error:" without that signature means real failure.
    if "error" in out.lower() and "records" not in out.lower():
        raise ADBError(f"dd failed reading {block}: {out.strip()}")

    # Make sure the temp file is readable by the shell user before pulling.
    adb.shell(f"su -c 'chmod 0644 {remote_tmp}'", check=False)
    try:
        adb.pull(remote_tmp, local_path, timeout=900)
    finally:
        adb.shell(f"su -c 'rm -f {remote_tmp}'", check=False)
    return PulledImage(kind=kind, local_path=local_path, source_path=block, method="dd")


# --------------------------------------------------------------------------- #
# unpacking
# --------------------------------------------------------------------------- #


@dataclass
class UnpackedImage:
    """Result of unpacking a boot-class image into its components."""

    image_path: Path
    out_dir: Path
    header_version: int | None
    kernel: Path | None
    ramdisk: Path | None
    dtb: Path | None
    extras: dict[str, Path]


def unpack_image(image: Path, out_dir: Path) -> UnpackedImage:
    """Unpack a boot/recovery image into its components.

    Tries ``unpackbootimg`` (from AOSP / mkbootimg repo) first; if not on PATH,
    falls back to twrpdtgen's bundled extractor.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if shutil.which("unpackbootimg"):
        return _unpack_with_unpackbootimg(image, out_dir)
    return _unpack_with_twrpdtgen(image, out_dir)


def _unpack_with_unpackbootimg(image: Path, out_dir: Path) -> UnpackedImage:
    """Use AOSP's `unpackbootimg` binary."""
    res = subprocess.run(
        ["unpackbootimg", "-i", str(image), "-o", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"unpackbootimg failed: {res.stderr.strip() or res.stdout.strip()}")

    base = image.name
    kernel = _exists(out_dir / f"{base}-kernel")
    ramdisk = _exists(out_dir / f"{base}-ramdisk.gz") or _exists(out_dir / f"{base}-ramdisk")
    dtb = _exists(out_dir / f"{base}-dtb") or _exists(out_dir / f"{base}-dt")

    header_version = _read_header_version(out_dir / f"{base}-header_version")

    extras: dict[str, Path] = {}
    for f in out_dir.iterdir():
        if f.is_file() and f.name.startswith(base + "-"):
            extras[f.name[len(base) + 1:]] = f

    return UnpackedImage(
        image_path=image,
        out_dir=out_dir,
        header_version=header_version,
        kernel=kernel,
        ramdisk=ramdisk,
        dtb=dtb,
        extras=extras,
    )


def _unpack_with_twrpdtgen(image: Path, out_dir: Path) -> UnpackedImage:
    """Fallback path using AIKManager — the same extractor twrpdtgen 3.x uses.

    Earlier we tried ``twrpdtgen.utils.bootimage.BootImageInfo``; that module
    was removed in twrpdtgen 3.0. The current upstream calls
    ``sebaubuntu_libs.libaik.AIKManager`` (an Android Image Kitchen wrapper),
    which is what we use here too. AIK requires a few standard Unix tools
    (cpio, etc.) — on macOS those are present by default.
    """
    try:
        from sebaubuntu_libs.libaik import AIKManager  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Neither `unpackbootimg` is on PATH nor is the AIKManager fallback "
            "importable. Install one: `pip install twrpdtgen` (pulls in AIK), "
            "or put unpackbootimg on PATH (e.g. via Android Build Tools)."
        ) from e

    mgr = AIKManager()
    try:
        info = mgr.unpackimg(image, ignore_ramdisk_errors=True)
    except Exception as e:
        mgr.cleanup()
        raise RuntimeError(f"AIK extraction failed for {image.name}: {e}") from e

    # AIKManager extracts into its own working directory; copy the bits we
    # care about into our out_dir so the result survives ``mgr.cleanup()``.
    out_dir.mkdir(parents=True, exist_ok=True)
    extras: dict[str, Path] = {}
    try:
        kernel = _copy_if_present(info.kernel, out_dir / "kernel")
        dtb_src = getattr(info, "dtb", None) or getattr(info, "dt", None)
        dtb = _copy_if_present(dtb_src, out_dir / "dtb")
        dtbo = _copy_if_present(getattr(info, "dtbo", None), out_dir / "dtbo")
        if dtbo is not None:
            extras["dtbo"] = dtbo

        ramdisk_dir = None
        if info.ramdisk and info.ramdisk.is_dir():
            ramdisk_dir = out_dir / "ramdisk"
            if ramdisk_dir.exists():
                shutil.rmtree(ramdisk_dir)
            shutil.copytree(info.ramdisk, ramdisk_dir)

        header_version = _safe_int(getattr(info, "header_version", None))
    finally:
        mgr.cleanup()

    return UnpackedImage(
        image_path=image,
        out_dir=out_dir,
        header_version=header_version,
        kernel=kernel,
        ramdisk=ramdisk_dir,
        dtb=dtb,
        extras=extras,
    )


def _copy_if_present(src: Path | None, dest: Path) -> Path | None:
    """Copy ``src`` to ``dest`` if src exists, else return None."""
    if src is None:
        return None
    src_path = Path(src) if not isinstance(src, Path) else src
    if not src_path.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, dest)
    return dest


def _safe_int(value) -> int | None:
    """Coerce AIK's string fields to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _exists(p: Path) -> Path | None:
    return p if p.exists() else None


def _read_header_version(p: Path) -> int | None:
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None
