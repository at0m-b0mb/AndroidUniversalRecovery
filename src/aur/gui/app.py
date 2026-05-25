"""GUI entrypoint — sidebar-driven main window.

Replaces the old QWizard. Pages live in :mod:`aur.gui.pages` and share
:class:`aur.gui.state.AppState`. The sidebar swaps the central stacked
widget; the status bar surfaces ADB / fingerprint state at all times.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from aur.gui.pages import (
    ConnectPage,
    DashboardPage,
    GeneratePage,
    RecoveryOpsPage,
    SettingsPage,
)
from aur.gui.sidebar import NavItem, NavSection, Sidebar
from aur.gui.state import AppState
from aur.gui.theme import PALETTE, qss
from aur.gui.widgets import Pill


_NAV = (
    NavSection("Device", (
        NavItem("dashboard", "Dashboard"),
        NavItem("connect",   "Connect"),
    )),
    NavSection("Build", (
        NavItem("generate",  "Generate recovery"),
    )),
    NavSection("Recovery", (
        NavItem("ops",       "Backup / Restore / Flash"),
    )),
    NavSection("Other", (
        NavItem("settings",  "Settings"),
    )),
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AUR — Android Universal Recovery")
        self.resize(1180, 780)
        self.setMinimumSize(960, 640)

        self.state = AppState()
        self._connect_auto_tried = False  # gate for one-shot auto-fingerprint

        # --- shell ---
        central = QWidget()
        self.setCentralWidget(central)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.sidebar = Sidebar(_NAV)
        row.addWidget(self.sidebar)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.NoFrame)
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {PALETTE.border};")
        row.addWidget(divider)

        self.stack = QStackedWidget()
        row.addWidget(self.stack, 1)

        # --- pages ---
        self.pages: dict[str, QWidget] = {}
        self._register("dashboard", DashboardPage(self.state, self._goto))
        self._register("connect",   ConnectPage(self.state))
        self._register("generate",  GeneratePage(self.state, self._goto))
        self._register("ops",       RecoveryOpsPage(self.state))
        self._register("settings",  SettingsPage(self.state))

        self.sidebar.page_chosen.connect(self._goto)

        # --- status bar ---
        self.setStatusBar(QStatusBar())
        self._adb_pill = Pill("ADB ?", "neutral")
        self._fp_pill = Pill("NO DEVICE", "neutral")
        self._out_label = QLabel(f"out: {self.state.out_root}")
        self.statusBar().addPermanentWidget(self._adb_pill)
        self.statusBar().addPermanentWidget(self._fp_pill)
        self.statusBar().addPermanentWidget(self._out_label)

        self.state.fingerprint_changed.connect(self._sync_fp_pill)
        self.state.out_root_changed.connect(
            lambda p: self._out_label.setText(f"out: {p}")
        )
        self._refresh_adb_pill()

        # Poll ADB every 3s so the status pill reflects plug/unplug events
        # without forcing the user onto the Connect page. 3s is fast enough
        # to feel live but cheap enough not to spam adb.
        self._adb_timer = QTimer(self)
        self._adb_timer.setInterval(3000)
        self._adb_timer.timeout.connect(self._refresh_adb_pill)
        self._adb_timer.start()

        # Keyboard shortcuts: ⌘1..⌘5 (Ctrl+1..5 on Linux/Windows) switch pages,
        # ⌘O reveals the output folder in Finder/Files.
        self._wire_shortcuts()

        # default page
        self.sidebar.select("dashboard")

    def _register(self, key: str, widget: QWidget) -> None:
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def _goto(self, key: str) -> None:
        widget = self.pages.get(key)
        if widget is not None:
            self.stack.setCurrentWidget(widget)
        # Bounce sidebar selection if a card triggered navigation.
        for k, btn in self.sidebar._buttons.items():
            btn.setChecked(k == key)
        # On first visit to the Connect page, try a one-shot auto-fingerprint
        # if exactly one device is present. Saves the user a click in the
        # common single-device workflow.
        if key == "connect" and not self._connect_auto_tried:
            self._connect_auto_tried = True
            page = self.pages.get("connect")
            if page is not None and hasattr(page, "maybe_auto_fingerprint"):
                page.maybe_auto_fingerprint()

    # ---- status bar ----

    def _refresh_adb_pill(self) -> None:
        from aur.device.adb import ADB, ADBError
        try:
            devs = ADB.list_devices()
        except ADBError:
            self._adb_pill.set_text_kind("ADB MISSING", "danger")
            return
        if not devs:
            self._adb_pill.set_text_kind("NO DEVICES", "warning")
            return
        online = [d for d in devs if d.state == "device"]
        if online:
            self._adb_pill.set_text_kind(f"{len(online)} ONLINE", "success")
        else:
            self._adb_pill.set_text_kind(f"{len(devs)} UNAUTHORIZED", "warning")

    def _sync_fp_pill(self, fp) -> None:
        if fp is None:
            self._fp_pill.set_text_kind("NO DEVICE", "neutral")
        else:
            self._fp_pill.set_text_kind(f"{fp.codename}", "success")

    # ---- keyboard / global shortcuts ----

    def _wire_shortcuts(self) -> None:
        """Bind ⌘1..5 to pages and ⌘O to reveal the output folder."""
        page_keys = ["dashboard", "connect", "generate", "ops", "settings"]
        for i, key in enumerate(page_keys, start=1):
            act = QAction(self)
            act.setShortcut(QKeySequence(f"Ctrl+{i}"))
            act.triggered.connect(lambda _checked=False, k=key: self._goto(k))
            self.addAction(act)

        reveal = QAction(self)
        reveal.setShortcut(QKeySequence("Ctrl+O"))
        reveal.triggered.connect(self.reveal_output_dir)
        self.addAction(reveal)

    def reveal_output_dir(self) -> None:
        """Open the current ``out_root`` in the host's file manager.

        Public so DashboardPage's "Open output folder" button can call it
        without reaching into private state.
        """
        path = self.state.out_root
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_about(self) -> None:
        """Show an About dialog with versions, paths, and links."""
        from aur.gui.about import AboutDialog
        AboutDialog(self).exec()


def _apply_theme(app: QApplication) -> None:
    app.setStyleSheet(qss())
    app.setStyle("Fusion")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AUR")
    _apply_theme(app)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
