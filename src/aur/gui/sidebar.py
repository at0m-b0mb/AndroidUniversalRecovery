"""Sidebar navigation.

A vertical column of grouped buttons. Selecting one emits ``page_chosen``
with the page key, and the main window swaps the stacked widget to match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str


@dataclass(frozen=True)
class NavSection:
    title: str
    items: Sequence[NavItem]


class Sidebar(QWidget):
    """Sidebar with title, sectioned nav buttons, and a single-select group."""

    page_chosen = pyqtSignal(str)  # key

    def __init__(self, sections: Sequence[NavSection], app_title: str = "AUR") -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel(app_title)
        title.setObjectName("SidebarTitle")
        subtitle = QLabel("Android Universal\nRecovery")
        subtitle.setObjectName("SidebarSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for sec in sections:
            header = QLabel(sec.title.upper())
            header.setObjectName("SidebarSection")
            layout.addWidget(header)
            for item in sec.items:
                btn = QPushButton(item.label)
                btn.setObjectName("NavButton")
                btn.setCheckable(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, k=item.key: self._on_click(k))
                self._buttons[item.key] = btn
                self._group.addButton(btn)
                layout.addWidget(btn)

        layout.addStretch(1)

        footer = QLabel("v0.1.0")
        footer.setObjectName("SidebarSubtitle")
        footer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(footer)

    def _on_click(self, key: str) -> None:
        self.page_chosen.emit(key)

    def select(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setChecked(True)
            self.page_chosen.emit(key)
