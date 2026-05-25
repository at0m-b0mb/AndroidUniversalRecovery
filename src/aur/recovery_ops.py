"""Host-side recovery operations.

Once a custom recovery (TWRP / OrangeFox) is on the device — or the device
is rooted — these helpers run common workflows from the host:

  - backup_partition       dd a partition to a local file, with SHA256
  - restore_partition      verify a local file, then dd it back
  - flash_image            convenience wrapper around restore_partition
  - verify_partition       compute on-device SHA256 and compare
  - wipe_partition         zero out a partition (DANGEROUS)
  - reboot_to              system / recovery / bootloader

Every write operation is opt-in via an explicit ``confirm=True`` argument
because the failure mode (bricked device, lost userdata) is severe and
hard to undo. The CLI exposes these behind an interactive prompt.

This module is recovery-agnostic: it talks to whatever shell is on the
other end of ``adb shell`` and uses ``su`` only if the device isn't
already a recovery (which runs everything as root).
"""

from __future__ import annotations

import hashlib
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from aur.device.adb import ADB, ADBError
from aur.device.fingerprint import DeviceFingerprint
from aur.device.partitions import PartitionEntry


# Partitions where a wrong write is catastrophic. Operations targeting
# these refuse unless ``allow_dangerous=True``.
DANGEROUS_PARTITIONS = frozenset({
    "userdata", "data",
    "system", "system_a", "system_b",
    "vendor", "vendor_a", "vendor_b",
    "super", "metadata",
    "persist", "modemst1", "modemst2", "fsg", "fsc",
    "nvram", "nvdata", "protect_f", "protect_s",
})


class RecoveryOpsError(RuntimeError):
    """Raised when an operation refuses to proceed or fails mid-flight."""


@dataclass
class OpResult:
    """Outcome of a single op — used by the CLI to render a summary."""

    op: str                  # "backup" | "restore" | "flash" | ...
    partition: str
    local_path: Path | None
    sha256: str | None
    bytes_transferred: int


class RecoveryOps:
    """Stateful helper bound to one ADB connection + one fingerprint."""

    def __init__(self, adb: ADB, fp: DeviceFingerprint):
        if not (fp.rooted or fp.in_recovery):
            raise RecoveryOpsError(
                "recovery operations need root on a booted system OR a custom "
                "recovery on the device. Neither was detected on this fingerprint. "
                "Re-fingerprint after booting into TWRP/OrangeFox, or root the device."
            )
        self.adb = adb
        self.fp = fp

    # ------------- partition resolution -------------

    def _resolve(self, name: str) -> PartitionEntry:
        # Handle A/B aware lookup: 'boot' on an A/B device resolves to boot_<active slot>.
        slot = self.fp.all_props.get("ro.boot.slot_suffix", "") if self.fp.is_ab else ""
        candidates: list[str] = []
        if slot and not name.endswith(("_a", "_b")):
            candidates.append(f"{name}{slot}")
        candidates.append(name)

        for cand in candidates:
            for p in self.fp.partitions:
                if p.name == cand:
                    return p
        known = ", ".join(p.name for p in self.fp.partitions[:20]) or "(none known)"
        raise RecoveryOpsError(f"partition {name!r} not found. Known: {known}")

    def _prefix(self) -> str:
        """Shell prefix to gain root, if needed. Recoveries already run as root."""
        return "" if self.fp.in_recovery else "su -c "

    def _shell_run(self, cmd: str, timeout: float = 300.0) -> str:
        prefix = self._prefix()
        if prefix:
            cmd = f"{prefix}{shlex.quote(cmd)}"
        return self.adb.shell(cmd, timeout=timeout)

    # ------------- read helpers -------------

    def sha256_partition(self, name: str) -> tuple[str, int]:
        """Return (sha256_hex, size_bytes) for an on-device partition."""
        part = self._resolve(name)
        # `sha256sum` is available on TWRP and most rooted systems.
        out = self._shell_run(f"sha256sum {part.block_device}").strip()
        if not out:
            raise RecoveryOpsError(f"sha256sum returned empty for {part.block_device}")
        digest = out.split()[0].lower()
        if len(digest) != 64:
            raise RecoveryOpsError(f"unexpected sha256sum output: {out!r}")
        return digest, part.size_bytes

    def backup_partition(self, name: str, dest_dir: Path) -> OpResult:
        """Backup a partition to ``dest_dir/<name>.img`` and verify SHA256."""
        part = self._resolve(name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        local = dest_dir / f"{part.name}.img"

        # Stage to /sdcard first so we can pull as the regular shell user.
        remote = f"/sdcard/aur-backup-{part.name}.img"
        self._shell_run(f"dd if={part.block_device} of={remote} bs=4M", timeout=1800)
        try:
            self.adb.pull(remote, local, timeout=1800)
        finally:
            self._shell_run(f"rm -f {remote}", timeout=30)

        # Verify: compute local hash, compare against on-device hash.
        local_hash = _sha256_of(local)
        device_hash, _ = self.sha256_partition(name)
        if local_hash != device_hash:
            raise RecoveryOpsError(
                f"sha256 mismatch on backup of {part.name}: "
                f"device={device_hash} local={local_hash}. "
                f"Local file kept at {local} for inspection."
            )

        return OpResult(
            op="backup",
            partition=part.name,
            local_path=local,
            sha256=local_hash,
            bytes_transferred=local.stat().st_size,
        )

    # ------------- write helpers (gated) -------------

    def restore_partition(
        self,
        name: str,
        source: Path,
        *,
        confirm: bool = False,
        allow_dangerous: bool = False,
        verify: bool = True,
    ) -> OpResult:
        """Push a local image and dd it back to the partition.

        Requires ``confirm=True`` (caller has explicitly opted in).
        Refuses :data:`DANGEROUS_PARTITIONS` unless ``allow_dangerous=True``.
        """
        if not confirm:
            raise RecoveryOpsError(
                "restore_partition refused: pass confirm=True after the user has "
                "explicitly confirmed. Writing to a partition with no opt-in is a bug."
            )
        if not source.exists():
            raise RecoveryOpsError(f"source image {source} does not exist")

        part = self._resolve(name)
        if part.name in DANGEROUS_PARTITIONS and not allow_dangerous:
            raise RecoveryOpsError(
                f"refusing to write to {part.name!r}: it's in DANGEROUS_PARTITIONS. "
                f"If you really mean it, pass allow_dangerous=True."
            )

        size_local = source.stat().st_size
        if part.size_bytes and size_local > part.size_bytes:
            raise RecoveryOpsError(
                f"image is larger than partition: {size_local} > {part.size_bytes} bytes"
            )

        remote = f"/sdcard/aur-restore-{part.name}.img"
        self.adb.run("push", str(source), remote, timeout=1800)
        try:
            # `dd` with conv=fsync ensures the write hits the device before return.
            self._shell_run(
                f"dd if={remote} of={part.block_device} bs=4M conv=fsync",
                timeout=1800,
            )
        finally:
            self._shell_run(f"rm -f {remote}", timeout=30)

        sha = _sha256_of(source)
        if verify:
            # We only need the head hash: if the partition is larger than the
            # image, the trailing bytes still hold whatever was there before
            # the write, so a full-partition sha would never match. (The v1
            # code computed both — gigabytes of needless USB transfer.)
            head_hash = self._sha256_partition_head(part, size_local)
            if head_hash != sha:
                raise RecoveryOpsError(
                    f"write-verify failed on {part.name}: "
                    f"local={sha} device-head={head_hash}"
                )

        return OpResult(
            op="restore",
            partition=part.name,
            local_path=source,
            sha256=sha,
            bytes_transferred=size_local,
        )

    def _sha256_partition_head(self, part: PartitionEntry, n_bytes: int) -> str:
        """Hash only the first ``n_bytes`` of a block device.

        Modern toybox/busybox `dd` supports `iflag=count_bytes` which lets
        us pass a byte count directly. Older toybox (some pre-Android 11
        OEM ROMs) doesn't, so we fall back to whole-block reads tail-trimmed
        with `head -c`.
        """
        BLOCK = 4 * 1024 * 1024  # 4 MiB
        # Preferred path: count_bytes (single dd, no shell pipe size limits).
        primary = (
            f"dd if={part.block_device} bs={BLOCK} count={n_bytes} iflag=count_bytes "
            f"2>/dev/null | sha256sum"
        )
        # Fallback path: read whole 4 MiB blocks plus a trailing partial block.
        whole_blocks, tail = divmod(n_bytes, BLOCK)
        if tail:
            fallback = (
                f"( dd if={part.block_device} bs={BLOCK} count={whole_blocks} 2>/dev/null; "
                f"  dd if={part.block_device} bs=1 count={tail} "
                f"     skip={whole_blocks * BLOCK} 2>/dev/null ) "
                f"| sha256sum"
            )
        else:
            fallback = (
                f"dd if={part.block_device} bs={BLOCK} count={whole_blocks} 2>/dev/null "
                f"| sha256sum"
            )
        # `sh -c '<primary> || <fallback>'` — but sha256sum's exit code is
        # also part of the pipeline. Just chain the dd return checks instead.
        cmd = (
            f"sh -c '{primary} 2>/tmp/aur-dd-err.$$ "
            f"|| {{ rm -f /tmp/aur-dd-err.$$; {fallback}; }}'"
        )
        out = self._shell_run(cmd).strip()
        digest = out.split()[0].lower() if out else ""
        if len(digest) != 64:
            raise RecoveryOpsError(f"partial sha256 read failed: {out!r}")
        return digest

    def flash_image(
        self,
        kind: str,
        source: Path,
        *,
        confirm: bool = False,
        skip_format_check: bool = False,
    ) -> OpResult:
        """Flash a boot-class image — convenience wrapper around restore.

        Refuses if the file doesn't look like an Android boot image (wrong
        magic bytes / too small / too large for the partition). Set
        ``skip_format_check=True`` to override when flashing something
        legitimately unusual (raw DTBO, custom partition contents).
        """
        if kind not in {"boot", "recovery", "vendor_boot", "init_boot", "dtbo"}:
            raise ValueError(f"flash_image kind must be a boot-class partition, got {kind!r}")
        if not skip_format_check:
            kind_for_check = "dtbo" if kind == "dtbo" else "boot"
            ok, why = inspect_image(source, expect=kind_for_check)
            if not ok:
                raise RecoveryOpsError(
                    f"refusing to flash {source.name} to {kind}: {why}. "
                    f"If you're sure, call flash_image(..., skip_format_check=True)."
                )
        return self.restore_partition(kind, source, confirm=confirm, verify=True)

    def verify_partition(self, name: str, expected_sha256: str) -> OpResult:
        """Compute on-device SHA256 and compare. Read-only."""
        digest, size = self.sha256_partition(name)
        if digest.lower() != expected_sha256.lower():
            raise RecoveryOpsError(
                f"verify failed on {name}: device={digest} expected={expected_sha256}"
            )
        return OpResult(
            op="verify", partition=name, local_path=None, sha256=digest, bytes_transferred=size,
        )

    def wipe_partition(self, name: str, *, confirm: bool = False) -> OpResult:
        """Zero out a partition.

        Refuses without confirm. Refuses :data:`DANGEROUS_PARTITIONS` outright
        — wiping ``userdata`` requires the explicit ``format-userdata`` op
        instead, which makes the destructiveness obvious in the call site.
        """
        if not confirm:
            raise RecoveryOpsError("wipe_partition needs confirm=True")
        part = self._resolve(name)
        if part.name in DANGEROUS_PARTITIONS:
            raise RecoveryOpsError(
                f"wipe_partition refuses {part.name!r}. Use format_userdata() "
                f"for userdata, or write a fresh image with restore_partition()."
            )
        self._shell_run(f"dd if=/dev/zero of={part.block_device} bs=4M", timeout=600)
        return OpResult(
            op="wipe", partition=part.name, local_path=None, sha256=None,
            bytes_transferred=part.size_bytes,
        )

    def format_userdata(self, *, confirm_phrase: str) -> OpResult:
        """Format /data. Requires the literal confirmation phrase as a guard."""
        if confirm_phrase != "ERASE USERDATA":
            raise RecoveryOpsError(
                "format_userdata requires confirm_phrase='ERASE USERDATA' verbatim. "
                "This op destroys all user data."
            )
        # TWRP recovery has `recovery --wipe_data`. On a rooted normal boot we
        # fall back to mkfs.ext4 on the partition.
        if self.fp.in_recovery:
            self._shell_run("twrp wipe data", timeout=600)
        else:
            part = self._resolve("userdata")
            self._shell_run(f"mke2fs -t ext4 -F {part.block_device}", timeout=600)
        return OpResult(
            op="format-userdata", partition="userdata",
            local_path=None, sha256=None, bytes_transferred=0,
        )

    # ------------- reboots -------------

    def reboot_to(self, target: str) -> None:
        """Reboot the device. ``target`` in {system, recovery, bootloader, fastboot}."""
        if target not in {"system", "recovery", "bootloader", "fastboot"}:
            raise ValueError(f"unknown reboot target: {target!r}")
        arg = "" if target == "system" else target
        try:
            self.adb.run("reboot", *([arg] if arg else []), timeout=20)
        except ADBError as e:
            # `adb reboot` exits non-zero when the device drops the connection
            # — that's success, not failure.
            if "closed" in str(e).lower() or "connection" in str(e).lower():
                return
            raise


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# Magic numbers for the file formats we know how to recognise.
# Sources: AOSP system/tools/mkbootimg, Linux Device Tree spec.
_BOOT_MAGIC      = b"ANDROID!"          # boot.img / recovery.img / vendor_boot.img headers v0..v4
_VENDOR_BOOT_MAG = b"VNDRBOOT"          # newer vendor_boot header magic (Android 11+)
_DTB_MAGIC       = b"\xd0\x0d\xfe\xed"  # device tree blob (also dtbo container)
_DTBO_TABLE_MAG  = b"\xd7\xb7\xab\x1e"  # DTBO table header magic


def inspect_image(path: Path, *, expect: str = "boot") -> tuple[bool, str]:
    """Validate a local image looks like the kind of image we expect.

    ``expect`` is "boot" (Android boot/recovery/vendor_boot) or "dtbo".
    Returns ``(ok, reason)``. ``ok=True`` means the file passes a basic
    sanity check — not a guarantee it's flashable, but a clear signal it
    isn't an obvious mistake (e.g. a zip, a text file, a corrupted image).
    """
    if not path.is_file():
        return False, f"{path} is not a file"
    size = path.stat().st_size
    if size < 4096:
        return False, f"too small for a real image ({size} bytes)"
    if size > 256 * 1024 * 1024:
        return False, f"suspiciously large ({size:,} bytes — boot images are usually < 256 MiB)"

    with path.open("rb") as f:
        head = f.read(64)

    if expect == "boot":
        if head.startswith(_BOOT_MAGIC):
            return True, "ANDROID! boot/recovery header"
        if head.startswith(_VENDOR_BOOT_MAG):
            return True, "VNDRBOOT vendor_boot header"
        # Some MediaTek images wrap an ANDROID! header inside a 512-byte
        # vendor preamble — accept if magic appears at offset 0x200.
        with path.open("rb") as f:
            f.seek(0x200)
            mtk = f.read(8)
        if mtk == _BOOT_MAGIC:
            return True, "ANDROID! header behind MediaTek 0x200 preamble"
        return False, f"missing Android boot magic (head bytes: {head[:8]!r})"

    if expect == "dtbo":
        if head.startswith(_DTBO_TABLE_MAG):
            return True, "DTBO table header"
        if head.startswith(_DTB_MAGIC):
            return True, "raw DTB / DTBO"
        return False, f"missing DTBO magic (head bytes: {head[:4]!r})"

    return False, f"unknown expect kind: {expect!r}"


def batch_backup(
    ops: RecoveryOps,
    partitions: Iterable[str],
    dest_dir: Path,
) -> list[OpResult]:
    """Backup several partitions in sequence, returning each result.

    On failure, partial results so far are returned via the raised
    ``RecoveryOpsError.results`` attribute so the user can see what succeeded.
    """
    results: list[OpResult] = []
    for name in partitions:
        try:
            results.append(ops.backup_partition(name, dest_dir))
        except RecoveryOpsError as e:
            e.add_note(f"completed before failure: {[r.partition for r in results]}")
            raise
    return results
