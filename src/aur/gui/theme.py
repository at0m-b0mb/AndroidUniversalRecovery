"""Dark theme for the AUR GUI.

A single opinionated dark palette — quiet background, vivid accents,
elevated cards, and deliberately high contrast on form controls so
inputs read as "wells" recessed into the surface (and never blend
into the card behind them, which was the v1 problem).

Exposed as both a :class:`Palette` dataclass (mixing colors in code) and
a precompiled QSS stylesheet (applied to the QApplication at startup).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    # Layered backgrounds: bg < surface < surface_hi, well goes below bg.
    bg: str          = "#15151f"
    bg_alt: str      = "#0f0f18"
    well: str        = "#0c0c14"
    surface: str     = "#1f1f2e"
    surface_hi: str  = "#2a2a3e"
    surface_glow: str = "#34344e"

    # Borders. border_strong is for inputs (visible against any surface).
    border: str        = "#34344a"
    border_strong: str = "#4a4a68"
    border_focus: str  = "#7aa0ff"

    # Text. text is primary, text_dim is secondary, text_mute is labels/hints.
    text: str       = "#e6e9f5"
    text_dim: str   = "#b8bcd0"
    text_mute: str  = "#7a7e95"
    text_faint: str = "#52556b"

    # Accents.
    primary: str    = "#82a4ff"
    primary_hi: str = "#a4c0ff"
    primary_dim: str = "#3d4a7a"
    success: str    = "#8ed99b"
    warning: str    = "#f0c878"
    danger: str     = "#ec7a92"
    info: str       = "#7adbcc"


PALETTE = Palette()


def qss(p: Palette = PALETTE) -> str:
    """Return the application QSS string for ``p``."""
    return f"""
    /* === Global === */
    * {{
        outline: 0;
    }}
    QWidget {{
        background: {p.bg};
        color: {p.text};
        font-family: -apple-system, 'SF Pro Text', 'Inter', 'Segoe UI', sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog {{
        background: {p.bg};
    }}
    QToolTip {{
        background: {p.surface_hi};
        color: {p.text};
        border: 1px solid {p.border_strong};
        padding: 5px 9px;
        border-radius: 5px;
        font-size: 12px;
    }}

    /* === Sidebar === */
    #Sidebar {{
        background: {p.bg_alt};
        border-right: 1px solid {p.border};
    }}
    #SidebarTitle {{
        color: {p.text};
        font-size: 17px;
        font-weight: 700;
        padding: 22px 20px 4px 20px;
        background: transparent;
        letter-spacing: 0.5px;
    }}
    #SidebarSubtitle {{
        color: {p.text_mute};
        font-size: 10px;
        padding: 0 20px 20px 20px;
        background: transparent;
        letter-spacing: 1.4px;
        text-transform: uppercase;
    }}
    #SidebarSection {{
        color: {p.text_faint};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.6px;
        padding: 16px 20px 6px 20px;
        background: transparent;
    }}
    QPushButton#NavButton {{
        background: transparent;
        color: {p.text_dim};
        border: none;
        text-align: left;
        padding: 10px 20px 10px 28px;
        font-size: 13px;
        border-left: 2px solid transparent;
    }}
    QPushButton#NavButton:hover {{
        background: {p.surface};
        color: {p.text};
    }}
    QPushButton#NavButton:checked {{
        background: {p.surface};
        color: {p.primary};
        border-left: 2px solid {p.primary};
        font-weight: 600;
    }}
    #SidebarFooter {{
        color: {p.text_faint};
        background: transparent;
        font-size: 10px;
        padding: 14px 20px;
        letter-spacing: 1.2px;
    }}

    /* === Page === */
    #PageScroll {{
        background: {p.bg};
        border: none;
    }}
    #PageTitle {{
        font-size: 24px;
        font-weight: 700;
        color: {p.text};
        background: transparent;
        padding: 0;
    }}
    #PageSubtitle {{
        font-size: 13px;
        color: {p.text_mute};
        background: transparent;
        padding: 4px 0 0 0;
    }}

    /* === Card === */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    /* Bare QWidget containers used as layout helpers inside cards must not
       paint their own background — otherwise a faint horizontal strip appears
       behind ActionRow / FormRow on top of the card surface. */
    #Card > QWidget {{
        background: transparent;
    }}
    #Card[active="true"] {{
        border: 1px solid {p.primary_dim};
    }}
    #Card[done="true"] {{
        border: 1px solid rgba(142,217,155,0.4);
    }}
    #Card[locked="true"] {{
        background: {p.bg_alt};
        border: 1px dashed {p.border};
    }}
    #CardTitle {{
        font-size: 14px;
        font-weight: 600;
        color: {p.text};
        background: transparent;
    }}
    #CardCaption {{
        font-size: 12px;
        color: {p.text_mute};
        background: transparent;
    }}
    #CardLabel {{
        font-size: 12px;
        color: {p.text_dim};
        background: transparent;
        font-weight: 500;
    }}

    /* === Step badges === */
    QLabel#StepBadge {{
        background: {p.surface_hi};
        color: {p.text_mute};
        border-radius: 14px;
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
        font-weight: 700;
        font-size: 13px;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#StepBadge[state="active"] {{
        background: {p.primary};
        color: {p.bg};
    }}
    QLabel#StepBadge[state="done"] {{
        background: {p.success};
        color: {p.bg};
    }}
    QLabel#StepBadge[state="locked"] {{
        background: {p.bg_alt};
        color: {p.text_faint};
        border: 1px dashed {p.border_strong};
    }}

    /* === Buttons === */
    QPushButton {{
        background: {p.surface_hi};
        color: {p.text};
        border: 1px solid {p.border_strong};
        border-radius: 7px;
        padding: 8px 16px;
        min-height: 18px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {p.surface_glow};
        border-color: {p.text_mute};
    }}
    QPushButton:pressed {{
        background: {p.bg_alt};
    }}
    QPushButton:disabled {{
        background: transparent;
        color: {p.text_faint};
        border: 1px dashed {p.border};
    }}
    QPushButton#Primary {{
        background: {p.primary};
        color: {p.bg};
        border: 1px solid {p.primary};
        font-weight: 600;
        padding: 9px 22px;
    }}
    QPushButton#Primary:hover {{
        background: {p.primary_hi};
        border-color: {p.primary_hi};
    }}
    QPushButton#Primary:pressed {{
        background: {p.primary_dim};
    }}
    QPushButton#Primary:disabled {{
        background: transparent;
        color: {p.text_faint};
        border: 1px dashed {p.border_strong};
    }}
    QPushButton#Danger {{
        background: {p.danger};
        color: {p.bg};
        border: 1px solid {p.danger};
        font-weight: 600;
        padding: 9px 22px;
    }}
    QPushButton#Danger:hover {{
        background: #f594aa;
    }}
    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid {p.border_strong};
        color: {p.text_dim};
        padding: 7px 14px;
    }}
    QPushButton#Ghost:hover {{
        color: {p.text};
        border-color: {p.text_mute};
        background: {p.surface};
    }}
    QPushButton#IconButton {{
        background: {p.surface_hi};
        border: 1px solid {p.border_strong};
        color: {p.text_dim};
        padding: 7px 10px;
        min-width: 20px;
    }}
    QPushButton#IconButton:hover {{
        color: {p.text};
        background: {p.surface_glow};
    }}

    /* === Inputs === */
    QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QSpinBox {{
        background: {p.well};
        color: {p.text};
        border: 1px solid {p.border_strong};
        border-radius: 7px;
        padding: 7px 11px;
        min-height: 20px;
        selection-background-color: {p.primary};
        selection-color: {p.bg};
    }}
    QLineEdit:hover, QComboBox:hover {{
        border-color: {p.text_mute};
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
        border-color: {p.border_focus};
    }}
    QLineEdit::placeholder {{
        color: {p.text_faint};
    }}
    QComboBox {{
        padding-right: 28px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {p.text_dim};
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border_strong};
        border-radius: 6px;
        selection-background-color: {p.surface_hi};
        outline: 0;
        padding: 4px;
    }}

    /* === Tables === */
    QTableWidget {{
        background: {p.well};
        border: 1px solid {p.border};
        border-radius: 8px;
        gridline-color: {p.border};
        selection-background-color: {p.surface_hi};
        selection-color: {p.text};
        alternate-background-color: {p.bg_alt};
    }}
    QHeaderView::section {{
        background: {p.surface};
        color: {p.text_mute};
        border: none;
        border-bottom: 1px solid {p.border_strong};
        padding: 8px 12px;
        font-weight: 600;
        font-size: 10px;
        letter-spacing: 1.2px;
        text-transform: uppercase;
    }}
    QTableWidget::item {{
        padding: 8px 10px;
        color: {p.text_dim};
    }}
    QTableWidget::item:selected {{
        color: {p.text};
    }}

    /* === Log pane === */
    QPlainTextEdit#LogPane {{
        font-family: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
        font-size: 12px;
        background: {p.well};
        border: 1px solid {p.border};
        color: {p.text_dim};
        padding: 10px 12px;
        line-height: 1.5;
    }}

    /* === Pills === */
    QLabel#PillNeutral, QLabel#PillSuccess, QLabel#PillWarning, QLabel#PillDanger, QLabel#PillInfo {{
        padding: 3px 9px;
        border-radius: 9px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.8px;
    }}
    QLabel#PillNeutral  {{ background: {p.surface_hi}; color: {p.text_mute};  }}
    QLabel#PillSuccess  {{ background: rgba(142,217,155,0.16); color: {p.success}; }}
    QLabel#PillWarning  {{ background: rgba(240,200,120,0.16); color: {p.warning}; }}
    QLabel#PillDanger   {{ background: rgba(236,122,146,0.16); color: {p.danger};  }}
    QLabel#PillInfo     {{ background: rgba(130,164,255,0.16); color: {p.primary}; }}

    /* === Progress / dividers === */
    QProgressBar {{
        background: {p.well};
        border: 1px solid {p.border};
        border-radius: 7px;
        text-align: center;
        color: {p.text_dim};
        height: 14px;
    }}
    QProgressBar::chunk {{
        background: {p.primary};
        border-radius: 6px;
    }}
    QFrame#Divider {{
        background: {p.border};
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}
    QFrame#SidebarDivider {{
        background: {p.border};
        max-width: 1px;
        min-width: 1px;
        border: none;
    }}

    /* === Scrollbars === */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.surface_hi};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.border_strong};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.surface_hi};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* === Status bar === */
    QStatusBar {{
        background: {p.bg_alt};
        color: {p.text_mute};
        border-top: 1px solid {p.border};
        padding: 4px 8px;
    }}
    QStatusBar::item {{
        border: none;
    }}
    QStatusBar QLabel {{
        background: transparent;
        color: {p.text_mute};
        padding: 0 6px;
    }}
    QLabel#StatusKey {{
        color: {p.text_faint};
        font-size: 10px;
        letter-spacing: 1px;
        text-transform: uppercase;
        background: transparent;
    }}
    QLabel#StatusValue {{
        color: {p.text_dim};
        font-size: 12px;
        background: transparent;
    }}

    /* === Checkboxes === */
    QCheckBox {{
        spacing: 8px;
        color: {p.text_dim};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.border_strong};
        border-radius: 4px;
        background: {p.well};
    }}
    QCheckBox::indicator:hover {{
        border-color: {p.text_mute};
    }}
    QCheckBox::indicator:checked {{
        background: {p.primary};
        border-color: {p.primary};
    }}

    /* === Empty state === */
    QFrame#EmptyState {{
        background: {p.bg_alt};
        border: 1px dashed {p.border_strong};
        border-radius: 10px;
    }}
    QLabel#EmptyGlyph {{
        font-size: 28px;
        color: {p.text_faint};
        background: transparent;
    }}
    QLabel#EmptyTitle {{
        font-size: 13px;
        font-weight: 600;
        color: {p.text_dim};
        background: transparent;
    }}
    QLabel#EmptyHint {{
        font-size: 12px;
        color: {p.text_mute};
        background: transparent;
    }}

    /* === Message boxes (Qt dialogs use these widget names) === */
    QMessageBox {{
        background: {p.surface};
    }}
    QMessageBox QLabel {{
        background: transparent;
        color: {p.text};
    }}
    """
