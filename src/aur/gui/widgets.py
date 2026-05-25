"""Shared custom widgets for the AUR GUI.

Kept in one file rather than a widgets/ package — each widget is small,
and the cross-references (e.g. StepCard holds Pill) are easier to see
together. Visual styling lives in QSS; widgets only set object names
and lay out children.

Layout helpers (ActionRow, FormRow) exist because the v1 GUI added
buttons directly to vertical layouts, which made them stretch full
card width — these helpers enforce the right layout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# --------------------------------------------------------------------------- #
# Atoms
# --------------------------------------------------------------------------- #

class Pill(QLabel):
    """Small rounded badge. ``kind`` picks the color scheme via QSS."""

    KINDS = {"neutral", "success", "warning", "danger", "info"}

    def __init__(self, text: str, kind: str = "neutral") -> None:
        super().__init__(text.upper())
        self.set_kind(kind)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_kind(self, kind: str) -> None:
        if kind not in self.KINDS:
            kind = "neutral"
        self.setObjectName(f"Pill{kind.capitalize()}")
        _restyle(self)

    def set_text_kind(self, text: str, kind: str) -> None:
        """Replace both the label and the color scheme in one call.

        Named explicitly (not ``update``) so we don't shadow
        :meth:`QWidget.update`, which Qt itself calls during repaints.
        """
        self.setText(text.upper())
        self.set_kind(kind)


class Divider(QFrame):
    """1-px horizontal rule."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)


class StepBadge(QLabel):
    """Numbered circular badge for step cards.

    States: locked (dashed gray), pending (filled gray), active (blue),
    done (green).
    """

    STATES = {"locked", "pending", "active", "done"}

    def __init__(self, number: int, state: str = "pending") -> None:
        super().__init__(str(number))
        self.setObjectName("StepBadge")
        self._number = number
        self.set_state(state)

    def set_state(self, state: str) -> None:
        if state not in self.STATES:
            state = "pending"
        # Use a Qt property + QSS attribute selector for state-based styling.
        self.setProperty("state", state)
        if state == "done":
            self.setText("✓")
        else:
            self.setText(str(self._number))
        _restyle(self)


class PageHeader(QWidget):
    """Title + subtitle block used at the top of every page."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        title_lbl = QLabel(title)
        title_lbl.setObjectName("PageTitle")
        sub_lbl = QLabel(subtitle)
        sub_lbl.setObjectName("PageSubtitle")
        sub_lbl.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)
        layout.addWidget(title_lbl)
        if subtitle:
            layout.addWidget(sub_lbl)


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #

def ActionRow(*buttons: QWidget, align: str = "right") -> QWidget:
    """Right-align (or left-align) a row of action buttons.

    Action buttons inside a vertical card body would otherwise stretch
    to fill the width — wrap them in this helper instead.
    """
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    if align == "right":
        h.addStretch(1)
    for b in buttons:
        h.addWidget(b)
    if align == "left":
        h.addStretch(1)
    return wrap


def FormRow(label: str, *controls: QWidget) -> QWidget:
    """Label on the left, one or more controls filling the rest of the row.

    All controls share the right-hand area equally. The label has a
    fixed minimum width so multiple FormRows stacked together align.
    """
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)

    lbl = QLabel(label)
    lbl.setObjectName("CardLabel")
    lbl.setFixedWidth(150)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    h.addWidget(lbl, 0)

    if len(controls) == 1:
        c = controls[0]
        c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        c.setMinimumHeight(36)
        h.addWidget(c, 1)
    else:
        inner = QHBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        for c in controls:
            c.setMinimumHeight(36)
            inner.addWidget(c, 1 if isinstance(c, QLineEdit) else 0)
        h.addLayout(inner, 1)

    return wrap


# --------------------------------------------------------------------------- #
# Card — the workhorse container
# --------------------------------------------------------------------------- #

class Card(QFrame):
    """Rounded surface with optional title, caption, and trailing widget.

    Use ``add(widget)`` or ``add_layout(layout)`` to stack content
    inside; the title/caption row sits at top. Set ``state`` to
    "active" / "done" / "locked" to drive QSS attribute selectors.
    """

    def __init__(
        self,
        title: str = "",
        caption: str = "",
        trailing: QWidget | None = None,
        leading: QWidget | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._title_label: QLabel | None = None
        self._caption_label: QLabel | None = None
        self._leading_slot = leading

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        if title or trailing or leading:
            header = QHBoxLayout()
            header.setSpacing(12)
            if leading is not None:
                header.addWidget(leading, 0, Qt.AlignmentFlag.AlignTop)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            text_col.setContentsMargins(0, 2, 0, 0)
            if title:
                self._title_label = QLabel(title)
                self._title_label.setObjectName("CardTitle")
                text_col.addWidget(self._title_label)
            if caption:
                self._caption_label = QLabel(caption)
                self._caption_label.setObjectName("CardCaption")
                self._caption_label.setWordWrap(True)
                text_col.addWidget(self._caption_label)
            header.addLayout(text_col, 1)

            if trailing is not None:
                header.addWidget(trailing, 0, Qt.AlignmentFlag.AlignTop)
            outer.addLayout(header)

        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        outer.addLayout(self._body)

    def add(self, widget: QWidget) -> None:
        self._body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._body.addLayout(layout)

    def set_state(self, state: str | None) -> None:
        """state in {"active", "done", "locked", None}."""
        for key in ("active", "done", "locked"):
            self.setProperty(key, "true" if state == key else None)
        _restyle(self)

    def set_title(self, text: str) -> None:
        if self._title_label is not None:
            self._title_label.setText(text)

    def set_caption(self, text: str) -> None:
        if self._caption_label is not None:
            self._caption_label.setText(text)


class StepCard(Card):
    """Card with a numbered StepBadge as leading widget.

    Convenience for the generator's 3-step flow. ``state`` is reflected
    on both the badge and the card border via QSS attribute selectors.
    """

    def __init__(
        self,
        step: int,
        title: str,
        caption: str = "",
        state: str = "pending",
        trailing: QWidget | None = None,
    ) -> None:
        self.badge = StepBadge(step, state=state)
        super().__init__(title=title, caption=caption, trailing=trailing, leading=self.badge)
        self._step_state = state
        # Drive the card border the same way as the badge.
        if state in ("active", "done", "locked"):
            self.set_state(state)

    def set_step_state(self, state: str) -> None:
        self._step_state = state
        self.badge.set_state(state)
        self.set_state(state if state in ("active", "done", "locked") else None)


# --------------------------------------------------------------------------- #
# LogPane
# --------------------------------------------------------------------------- #

class LogPane(QPlainTextEdit):
    """Monospace log with capped scrollback and level-prefixed lines.

    Optionally mirrors every logged line to a file (append mode, line-buffered)
    so users have a persistent record of every op they ran. Mirroring is a
    soft feature — failures to write are swallowed, never crash the UI.
    """

    _GLYPH = {
        "info":  "·",
        "ok":    "✓",
        "warn":  "!",
        "error": "✗",
        "step":  "▸",
    }

    def __init__(
        self,
        max_lines: int = 2000,
        placeholder: str = "",
        mirror_path: "Path | None" = None,
    ) -> None:
        super().__init__()
        self.setObjectName("LogPane")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setMinimumHeight(120)
        f = QFont("JetBrains Mono")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(f)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self._mirror_path = mirror_path
        if mirror_path is not None:
            try:
                mirror_path.parent.mkdir(parents=True, exist_ok=True)
                with mirror_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n--- session opened ---\n")
            except OSError:
                # Disk full / read-only fs / permission — fail silent, keep UI.
                self._mirror_path = None

    def set_mirror_path(self, path: "Path | None") -> None:
        """Switch mirror destination at runtime. ``None`` disables mirroring."""
        self._mirror_path = path

    def log(self, line: str, level: str = "info") -> None:
        glyph = self._GLYPH.get(level, "·")
        formatted = f"  {glyph}  {line}"
        self.appendPlainText(formatted)
        if self._mirror_path is not None:
            try:
                with self._mirror_path.open("a", encoding="utf-8") as f:
                    import datetime
                    stamp = datetime.datetime.now().strftime("%H:%M:%S")
                    f.write(f"{stamp}  {glyph}  {line}\n")
            except OSError:
                # Best-effort; don't kill the UI over a log write.
                pass


# --------------------------------------------------------------------------- #
# Read-only data grid
# --------------------------------------------------------------------------- #

class KeyValueGrid(QWidget):
    """Two-column read-only data grid."""

    def __init__(self) -> None:
        super().__init__()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 4, 0, 0)
        self._grid.setHorizontalSpacing(20)
        self._grid.setVerticalSpacing(8)
        self._row = 0

    def add(self, key: str, value: str | QWidget) -> None:
        k = QLabel(key)
        k.setObjectName("CardCaption")
        k.setMinimumWidth(140)
        self._grid.addWidget(k, self._row, 0, Qt.AlignmentFlag.AlignTop)
        if isinstance(value, QWidget):
            self._grid.addWidget(value, self._row, 1, Qt.AlignmentFlag.AlignLeft)
        else:
            v = QLabel(value)
            # Without an object name the label picks up the global QWidget
            # background (page bg, not card surface) and renders a dark strip
            # over the card. CardLabel is already styled transparent in QSS.
            v.setObjectName("CardLabel")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(v, self._row, 1)
        self._row += 1

    def clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._row = 0


# --------------------------------------------------------------------------- #
# Empty state
# --------------------------------------------------------------------------- #

class EmptyState(QFrame):
    """Dashed-border empty state with glyph, title, optional hint."""

    def __init__(self, glyph: str, title: str, hint: str = "") -> None:
        super().__init__()
        self.setObjectName("EmptyState")
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(6)
        layout.addStretch(1)

        g = QLabel(glyph)
        g.setObjectName("EmptyGlyph")
        g.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(g)

        t = QLabel(title)
        t.setObjectName("EmptyTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(t)

        if hint:
            h = QLabel(hint)
            h.setObjectName("EmptyHint")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.setWordWrap(True)
            layout.addWidget(h)

        layout.addStretch(1)


# --------------------------------------------------------------------------- #
# DeviceCard — at-a-glance summary of the active fingerprint
# --------------------------------------------------------------------------- #

class DeviceCard(Card):
    """Compact card summarising the currently fingerprinted device.

    Empty state shows a hint to fingerprint a device; populated state
    shows brand/model + capability pills + kernel summary.
    """

    def __init__(self) -> None:
        super().__init__()
        self._populated_widget: QWidget | None = None
        self._empty_widget: QWidget | None = None
        self._title_label = QLabel("Connected device")
        self._title_label.setObjectName("CardTitle")
        self._subtitle_label = QLabel("No device fingerprinted")
        self._subtitle_label.setObjectName("CardCaption")
        self._subtitle_label.setWordWrap(True)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(self._title_label)
        head.addWidget(self._subtitle_label)
        self.add_layout(head)

        self._status_pill = Pill("OFFLINE", "neutral")
        self._pills_row = QHBoxLayout()
        self._pills_row.setSpacing(6)
        self._pills_row.addWidget(self._status_pill)
        self._pills_row.addStretch(1)
        self.add_layout(self._pills_row)

        self._kv_holder = QWidget()
        self._kv_layout = QVBoxLayout(self._kv_holder)
        self._kv_layout.setContentsMargins(0, 0, 0, 0)
        self._kv_layout.setSpacing(0)
        self._kv: KeyValueGrid | None = None
        self.add(self._kv_holder)

        self.show_empty()

    def show_empty(self) -> None:
        self._title_label.setText("Connected device")
        self._subtitle_label.setText(
            "Plug in a phone, hit Refresh on the Connect page, then fingerprint it."
        )
        self._status_pill.set_text_kind("OFFLINE", "neutral")
        # Drop any extra pills.
        _clear_after(self._pills_row, keep_first=1)
        self._pills_row.addStretch(1)
        # Clear KV grid.
        if self._kv is not None:
            self._kv.clear()
            self._kv.setParent(None)
            self._kv = None
        # Disable card highlight.
        self.set_state(None)

    def show_fingerprint(self, fp) -> None:
        self._title_label.setText(f"{fp.brand}  {fp.model}".strip())
        self._subtitle_label.setText(
            f"{fp.manufacturer} / {fp.codename}  ·  "
            f"Android {fp.android_release} (SDK {fp.android_sdk})  ·  {fp.platform}"
        )
        self._status_pill.set_text_kind("ONLINE" if not fp.in_recovery else "RECOVERY", "success")

        # Pills row: status + capabilities.
        _clear_after(self._pills_row, keep_first=1)
        for label, ok in (
            ("A/B", fp.is_ab),
            ("Dynamic", fp.has_dynamic_partitions),
            ("Treble", fp.is_treble),
            ("Rooted", fp.rooted),
        ):
            self._pills_row.addWidget(Pill(label, "info" if ok else "neutral"))
        self._pills_row.addStretch(1)

        # KV details.
        if self._kv is not None:
            self._kv.clear()
            self._kv.setParent(None)
        self._kv = KeyValueGrid()
        self._kv.add("Arch", fp.arch or "?")
        self._kv.add("Bootloader", fp.bootloader or "?")
        self._kv.add("Partitions", str(len(fp.partitions)))
        kernel = (fp.kernel_version or "?").split("\n")[0]
        if len(kernel) > 70:
            kernel = kernel[:67] + "…"
        self._kv.add("Kernel", kernel)
        self._kv_layout.addWidget(self._kv)
        self.set_state("done")


# --------------------------------------------------------------------------- #
# Button constructors (so callers don't have to know the QSS names)
# --------------------------------------------------------------------------- #

def primary(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    return _build_button(text, "Primary", on_click)


def ghost(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    return _build_button(text, "Ghost", on_click)


def danger(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    return _build_button(text, "Danger", on_click)


def icon_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    return _build_button(text, "IconButton", on_click)


def _build_button(text: str, object_name: str, on_click) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName(object_name)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _restyle(widget: QWidget) -> None:
    """Force Qt to re-evaluate the widget's stylesheet after object name /
    property changes. Without this the state-based selectors don't update.
    """
    s = widget.style()
    if s is not None:
        s.unpolish(widget)
        s.polish(widget)
    widget.update()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            break
        w = item.widget()
        if w is not None:
            w.deleteLater()


def _clear_after(layout, *, keep_first: int) -> None:
    """Remove all but the first ``keep_first`` items from ``layout``."""
    # Walk from the end to preserve indexes.
    while layout.count() > keep_first:
        item = layout.takeAt(layout.count() - 1)
        if item is None:
            break
        w = item.widget()
        if w is not None:
            w.deleteLater()
