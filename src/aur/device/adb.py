"""Minimal ADB wrapper.

We shell out to the `adb` binary rather than reimplementing the protocol.
Every method here returns plain text (stdout) or raises ``ADBError``. Callers
in higher layers parse the text into typed structures.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ADBError(RuntimeError):
    """Raised when an ``adb`` invocation fails."""


class NoDeviceError(ADBError):
    """Raised when no authorized device is connected."""


@dataclass(frozen=True)
class DeviceHandle:
    """Identifies a single connected device for multi-device hosts."""

    serial: str
    state: str  # "device", "recovery", "unauthorized", "offline", ...


class ADB:
    """Thin wrapper around the ``adb`` CLI.

    The wrapper is intentionally low-level: it does not interpret output.
    It does enforce a single target device (``serial``) so multi-device
    hosts work predictably.
    """

    def __init__(
        self,
        serial: str | None = None,
        adb_path: str | None = None,
        *,
        _allow_ambiguous: bool = False,
    ):
        self._adb = adb_path or shutil.which("adb")
        if not self._adb:
            raise ADBError(
                "adb not found on PATH. Install Android Platform Tools and ensure "
                "`adb` is on your PATH."
            )
        self.serial = serial
        # If no serial was passed and more than one usable device exists, the
        # caller almost certainly didn't mean "pick one for me randomly" —
        # adb itself would refuse with "more than one device". Surface that
        # early as a clear ADBError instead of silently misbehaving later.
        # ``_allow_ambiguous`` is the escape hatch used internally by
        # :meth:`list_devices` so it can construct a probe handle without
        # re-entering this check.
        if serial is None and not _allow_ambiguous:
            try:
                online = [
                    d for d in self._raw_list_devices()
                    if d.state in ("device", "recovery")
                ]
            except ADBError:
                online = []
            if len(online) > 1:
                listing = ", ".join(f"{d.serial}({d.state})" for d in online)
                raise ADBError(
                    f"multiple devices connected ({listing}); pass --serial / "
                    f"ADB(serial=...) to choose one."
                )

    def _raw_list_devices(self) -> list[DeviceHandle]:
        """Internal: list devices without re-running the ambiguity check."""
        out = self.run("devices", check=False)
        devices: list[DeviceHandle] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append(DeviceHandle(serial=parts[0], state=parts[1]))
        return devices

    def _args(self, *extra: str) -> list[str]:
        cmd = [self._adb]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(extra)
        return cmd

    def run(self, *args: str, timeout: float = 30.0, check: bool = True) -> str:
        """Run an arbitrary adb command and return stdout (decoded)."""
        try:
            result = subprocess.run(
                self._args(*args),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as e:
            raise ADBError(f"adb binary disappeared: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise ADBError(f"adb {' '.join(args)} timed out after {timeout}s") from e

        if check and result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "no devices" in stderr.lower() or "not found" in stderr.lower():
                raise NoDeviceError(stderr or "no devices/emulators found")
            raise ADBError(
                f"adb {' '.join(args)} failed (rc={result.returncode}): {stderr}"
            )
        return result.stdout

    # ------------- high-level helpers -------------

    @classmethod
    def list_devices(cls, adb_path: str | None = None) -> list[DeviceHandle]:
        """Return every device adb knows about, in any state."""
        tmp = cls(adb_path=adb_path, _allow_ambiguous=True)
        return tmp._raw_list_devices()

    def wait_for_device(self, timeout: float = 60.0) -> None:
        """Block until the target device reaches the 'device' state."""
        self.run("wait-for-device", timeout=timeout)

    def shell(self, command: str, timeout: float = 30.0, check: bool = True) -> str:
        """Run a shell command on the device."""
        return self.run("shell", command, timeout=timeout, check=check)

    def getprop(self, key: str | None = None) -> str:
        """Return ``getprop`` output. With no key, returns the full dump."""
        return self.shell("getprop" + (f" {key}" if key else ""))

    def pull(self, remote: str, local: Path, timeout: float = 300.0) -> Path:
        """Pull a file from the device to ``local`` and return the local path."""
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run("pull", remote, str(local), timeout=timeout)
        if not local.exists():
            raise ADBError(f"adb pull reported success but {local} is missing")
        return local

    def is_rooted(self) -> bool:
        """Heuristic: device is 'rooted' if `su -c id` returns uid=0."""
        try:
            out = self.shell("su -c 'id -u' 2>/dev/null", check=False).strip()
            return out == "0"
        except ADBError:
            return False

    def in_recovery(self) -> bool:
        """True if the device is currently booted into a recovery (incl. TWRP)."""
        out = self.run("get-state", check=False).strip()
        return out == "recovery"
