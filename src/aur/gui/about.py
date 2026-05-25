"""About dialog — versions, install paths, and project links.

Pulled out of app.py because it needs to query the environment lazily
(import twrpdtgen, ask adb its version) and the dialog QSS is fiddly
enough that bundling it next to its data keeps app.py readable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import aur
from aur.gui.widgets import Card, Divider, KeyValueGrid, ghost, primary


def _adb_version() -> str:
    """Best-effort `adb version` first line, or '(not installed)'."""
    path = shutil.which("adb")
    if not path:
        return "(not installed)"
    try:
        out = subprocess.run(
            [path, "version"], capture_output=True, text=True, timeout=3,
        ).stdout
        return out.splitlines()[0] if out else "(no version output)"
    except Exception:
        return "(call failed)"


def _twrpdtgen_version() -> str:
    """Importlib-metadata version of twrpdtgen, or '(not installed)'."""
    try:
        from importlib.metadata import version
        return version("twrpdtgen")
    except Exception:
        return "(not installed)"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About AUR")
        self.setMinimumWidth(520)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # Header band: app name + tagline.
        title = QLabel("AUR — Android Universal Recovery")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Generate per-device TWRP / OrangeFox device trees and build plans "
            "from a connected phone, then run host-side recovery ops with "
            "SHA-256 protection."
        )
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(sub)
        outer.addWidget(Divider())

        # Versions / paths.
        version_card = Card("Build info")
        kv = KeyValueGrid()
        kv.add("AUR version", aur.__version__)
        kv.add("Python", f"{sys.version_info.major}.{sys.version_info.minor}."
                         f"{sys.version_info.micro}")
        kv.add("twrpdtgen", _twrpdtgen_version())
        kv.add("adb", _adb_version())
        kv.add("Platform", sys.platform)
        kv.add("Install path", str(Path(aur.__file__).parent))
        version_card.add(kv)
        outer.addWidget(version_card)

        # Links + close button row.
        actions = QHBoxLayout()
        actions.addWidget(ghost(
            "Open install folder",
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(aur.__file__).parent))
            ),
        ))
        actions.addStretch(1)
        actions.addWidget(primary("Close", self.accept))
        outer.addLayout(actions)
