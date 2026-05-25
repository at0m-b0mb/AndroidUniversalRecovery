"""Application-wide state shared between pages.

Pages don't talk to each other directly — they read/write ``AppState`` and
listen for its ``Qt`` signals. Keeping mutable state in one place makes
the page wiring simple and the data flow easy to follow.

User preferences (output dir) persist across launches via :class:`QSettings`
under the ``at0m_b0mb / AUR`` organization/application keys. Volatile
state — current fingerprint, last image, generated trees — does NOT
persist; pulling a phone in a fresh session always starts from a clean
fingerprint.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from aur.device.fingerprint import DeviceFingerprint


def default_out_root() -> Path:
    return Path.home() / "AUR_out"


def _settings() -> QSettings:
    return QSettings("at0m_b0mb", "AUR")


class AppState(QObject):
    serial_changed = pyqtSignal(object)        # str | None
    fingerprint_changed = pyqtSignal(object)   # DeviceFingerprint | None
    image_changed = pyqtSignal(object)         # Path | None
    trees_changed = pyqtSignal(dict)           # {base: Path}
    out_root_changed = pyqtSignal(object)      # Path

    def __init__(self) -> None:
        super().__init__()
        self._serial: str | None = None
        self._fingerprint: DeviceFingerprint | None = None
        self._image_path: Path | None = None
        self._trees: dict[str, Path] = {}
        # Restore persisted output dir if present; else fall back to default.
        stored = _settings().value("out_root", "", type=str)
        self._out_root: Path = Path(stored) if stored else default_out_root()

    # ----- serial -----
    @property
    def serial(self) -> str | None:
        return self._serial

    def set_serial(self, value: str | None) -> None:
        if value == self._serial:
            return
        self._serial = value
        self.serial_changed.emit(value)

    # ----- fingerprint -----
    @property
    def fingerprint(self) -> DeviceFingerprint | None:
        return self._fingerprint

    def set_fingerprint(self, fp: DeviceFingerprint | None) -> None:
        self._fingerprint = fp
        self.fingerprint_changed.emit(fp)

    # ----- last extracted image -----
    @property
    def image_path(self) -> Path | None:
        return self._image_path

    def set_image_path(self, path: Path | None) -> None:
        self._image_path = path
        self.image_changed.emit(path)

    # ----- generated trees -----
    @property
    def trees(self) -> dict[str, Path]:
        return dict(self._trees)

    def set_trees(self, trees: dict[str, Path]) -> None:
        self._trees = dict(trees)
        self.trees_changed.emit(self._trees)

    # ----- output root -----
    @property
    def out_root(self) -> Path:
        return self._out_root

    def set_out_root(self, path: Path) -> None:
        if path == self._out_root:
            return
        self._out_root = path
        _settings().setValue("out_root", str(path))
        self.out_root_changed.emit(path)

    # ----- list fingerprints saved under out_root -----
    def saved_fingerprints(self) -> list[Path]:
        """Return paths to every fingerprint.json found under out_root.

        Used by the Dashboard to show "Recent fingerprints" so a user can
        skip re-running fingerprinting when re-opening AUR for an existing
        device.
        """
        if not self._out_root.exists():
            return []
        found: list[Path] = []
        for child in self._out_root.iterdir():
            if not child.is_dir():
                continue
            fp = child / "fingerprint.json"
            if fp.is_file():
                found.append(fp)
        # Most-recent first by mtime — that's what users want at the top.
        return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

    def saved_fingerprints_by_serial(self) -> dict[str, str]:
        """Map ``adb serial`` → ``codename`` for every saved fingerprint.

        Used by the Connect page to mark rows that already have an
        on-disk fingerprint, so the user doesn't refingerprint the same
        device by accident. Cheap to call (a few small JSON reads).
        """
        import json
        out: dict[str, str] = {}
        for fp_path in self.saved_fingerprints():
            try:
                data = json.loads(fp_path.read_text())
            except (OSError, ValueError):
                continue
            serial = data.get("serial")
            codename = data.get("codename")
            if serial and codename and serial != "(default)":
                out[serial] = codename
        return out
