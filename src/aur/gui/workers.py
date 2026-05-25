"""Background workers for long-running operations.

Anything that touches ADB or the filesystem runs on a QThread so the UI
stays responsive. Each worker emits ``progress`` lines and a single
``finished`` signal carrying a payload or an error string.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from aur.builder import export_build_plan
from aur.device.adb import ADB, ADBError
from aur.device.bootimg import pull_image, unpack_image
from aur.device.fingerprint import DeviceFingerprint, fingerprint_device
from aur.generator import generate_tree
from aur.recovery_ops import RecoveryOps, RecoveryOpsError


class _BaseWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)  # payload-or-Exception
    failed = pyqtSignal(str)

    def run(self) -> None:  # override
        raise NotImplementedError


class FingerprintWorker(_BaseWorker):
    def __init__(self, serial: str | None, out_root: Path):
        super().__init__()
        self.serial = serial
        self.out_root = out_root

    def run(self) -> None:
        try:
            self.progress.emit("Connecting to device…")
            adb = ADB(serial=self.serial)
            self.progress.emit("Reading device properties (getprop)…")
            fp = fingerprint_device(adb)
            self.progress.emit(f"Found {fp.manufacturer}/{fp.codename}. Saving fingerprint…")
            target = self.out_root / fp.codename / "fingerprint.json"
            fp.save_json(target)
            self.finished.emit({"fingerprint": fp, "path": target})
        except ADBError as e:
            self.failed.emit(f"ADB error: {e}")
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


@dataclass
class ExtractRequest:
    serial: str | None
    fp: DeviceFingerprint
    out_root: Path
    kind: str  # "boot" or "recovery"
    manual_image: Path | None = None  # bypass pull


class ExtractWorker(_BaseWorker):
    def __init__(self, req: ExtractRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            if self.req.manual_image is not None:
                image_path = self.req.manual_image
                self.progress.emit(f"Using user-provided image: {image_path}")
            else:
                self.progress.emit(f"Pulling {self.req.kind}.img from device…")
                adb = ADB(serial=self.req.serial)
                pulled = pull_image(
                    adb, self.req.fp, self.req.kind,
                    self.req.out_root / self.req.fp.codename,
                )
                image_path = pulled.local_path
                self.progress.emit(f"Pulled to {image_path}")

            self.progress.emit("Unpacking image…")
            target = self.req.out_root / self.req.fp.codename / f"{self.req.kind}-extracted"
            unpacked = unpack_image(image_path, target)
            self.finished.emit({"image": image_path, "unpacked": unpacked})
        except ADBError as e:
            self.failed.emit(f"ADB error: {e}")
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


@dataclass
class GenerateRequest:
    fp: DeviceFingerprint
    image: Path
    base: str  # "twrp" | "orangefox" | "both"
    out_root: Path


class GenerateWorker(_BaseWorker):
    def __init__(self, req: GenerateRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            self.progress.emit(f"Generating {self.req.base} device tree from {self.req.image.name}…")
            results = generate_tree(
                fp=self.req.fp, image=self.req.image,
                base=self.req.base, out_root=self.req.out_root,
            )
            self.progress.emit("Generation complete.")
            self.finished.emit(results)
        except Exception as e:
            self.failed.emit(f"Generator error: {e}")


@dataclass
class ExportRequest:
    tree_dir: Path
    base: str
    mode: str  # "docker" | "plain" | "cloud-vm"
    out_dir: Path


class ExportWorker(_BaseWorker):
    def __init__(self, req: ExportRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            self.progress.emit(f"Rendering {self.req.mode} build plan…")
            target = export_build_plan(
                tree_dir=self.req.tree_dir, base=self.req.base,
                mode=self.req.mode, out_dir=self.req.out_dir,
            )
            self.finished.emit(target)
        except Exception as e:
            self.failed.emit(f"Export error: {e}")


@dataclass
class RecoveryOpRequest:
    """Generic envelope for backup/restore/flash/verify ops."""
    serial: str | None
    fp: DeviceFingerprint
    op: str           # "backup" | "restore" | "flash" | "verify"
    partition: str
    image: Path | None = None      # for restore/flash
    sha256: str | None = None      # for verify
    dest_dir: Path | None = None   # for backup
    allow_dangerous: bool = False


class RecoveryOpWorker(_BaseWorker):
    def __init__(self, req: RecoveryOpRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            adb = ADB(serial=self.req.serial)
            ops = RecoveryOps(adb, self.req.fp)

            op = self.req.op
            if op == "backup":
                if self.req.dest_dir is None:
                    raise ValueError("dest_dir is required for backup")
                self.progress.emit(f"Backing up {self.req.partition}…")
                result = ops.backup_partition(self.req.partition, self.req.dest_dir)
            elif op == "restore":
                if self.req.image is None:
                    raise ValueError("image is required for restore")
                self.progress.emit(f"Restoring {self.req.image.name} → {self.req.partition}…")
                result = ops.restore_partition(
                    self.req.partition, self.req.image,
                    confirm=True, allow_dangerous=self.req.allow_dangerous,
                )
            elif op == "flash":
                if self.req.image is None:
                    raise ValueError("image is required for flash")
                self.progress.emit(f"Flashing {self.req.image.name} → {self.req.partition}…")
                result = ops.flash_image(self.req.partition, self.req.image, confirm=True)
            elif op == "verify":
                if not self.req.sha256:
                    raise ValueError("sha256 is required for verify")
                self.progress.emit(f"Verifying {self.req.partition} against expected hash…")
                result = ops.verify_partition(self.req.partition, self.req.sha256)
            else:
                raise ValueError(f"unknown op: {op!r}")

            self.finished.emit(result)
        except RecoveryOpsError as e:
            self.failed.emit(str(e))
        except ADBError as e:
            self.failed.emit(f"ADB error: {e}")
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


@dataclass
class RebootRequest:
    serial: str | None
    target: str  # "system" | "recovery" | "bootloader" | "fastboot"


class RebootWorker(_BaseWorker):
    """Reboot the connected device.

    `adb reboot` is fast (< 1s to issue), but it can hang on misbehaving
    USB stacks, so we still run it off the UI thread. We treat connection
    drops as success since rebooting *is* what just dropped the connection.
    """

    def __init__(self, req: RebootRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            adb = ADB(serial=self.req.serial)
            self.progress.emit(f"Sending reboot → {self.req.target}…")
            arg = "" if self.req.target == "system" else self.req.target
            try:
                adb.run("reboot", *([arg] if arg else []), timeout=20)
            except ADBError as e:
                msg = str(e).lower()
                if "closed" in msg or "connection" in msg or "no devices" in msg:
                    # Device dropped — that's success for a reboot.
                    pass
                else:
                    raise
            self.finished.emit({"target": self.req.target})
        except ADBError as e:
            self.failed.emit(f"ADB error: {e}")
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


def run_worker(parent: QObject, worker: _BaseWorker) -> QThread:
    """Move ``worker`` to a fresh QThread and start it. Returns the thread.

    Caller is responsible for connecting ``worker.finished`` / ``worker.failed``
    and disposing of the thread when done.
    """
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
