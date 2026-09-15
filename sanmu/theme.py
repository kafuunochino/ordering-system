"""Qt 应用级主题：所有页面、下拉列表和弹窗使用同一组颜色。"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_window_theme(window):
    """让 Windows 标题栏跟随本程序主题，只影响这个窗口。"""
    import sys
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return
    import ctypes
    try:
        dark = ctypes.c_int(QApplication.palette().color(QPalette.Window).lightness() < 128)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), 20,
                                                 ctypes.byref(dark), ctypes.sizeof(dark))
    except (AttributeError, OSError):
        pass

PALETTES = {
    "light": dict(bg="#F2F4F7", surface="#FFFFFF", raised="#F7F8FA", line="#E5E8ED",
                  text="#202631", muted="#7C8594", faint="#A5ACB7", hover="#EDF0F4",
                  accent="#FFC938", soft="#FFF6D7", accent_text="#806000",
                  success="#248766", success_bg="#E7F5ED", danger="#D95858", danger_bg="#FFF0F0",
                  busy_bg="#CEE9DE", busy_hover="#B9DDCD", busy_selected="#BFE2D3", busy_line="#5A9F82",
                  busy_text="#164D39", busy_badge="#236348", busy_badge_text="#FFFFFF"),
    "dark": dict(bg="#14171D", surface="#1F232B", raised="#272C35", line="#343B47",
                 text="#F1F3F7", muted="#A0A9B8", faint="#788292", hover="#313844",
                 accent="#FFD04A", soft="#3A3423", accent_text="#FFD76C",
                 success="#63CBA3", success_bg="#223D34", danger="#FF8E8E", danger_bg="#402C31",
                 busy_bg="#224A3C", busy_hover="#2C5C4B", busy_selected="#2B5847", busy_line="#4F9A7B",
                 busy_text="#DAF9E9", busy_badge="#A9E7C9", busy_badge_text="#143F2C"),
}


def apply_theme(application: QApplication, mode: str):
    p = PALETTES[mode]
    application.setProperty("sanmuTheme", mode)
    palette = QPalette()
    for role, value in {
        QPalette.Window: p["bg"], QPalette.WindowText: p["text"], QPalette.Base: p["surface"],
        QPalette.AlternateBase: p["raised"], QPalette.Text: p["text"], QPalette.Button: p["raised"],
        QPalette.ButtonText: p["text"], QPalette.Highlight: p["accent"], QPalette.HighlightedText: "#252015",
        QPalette.ToolTipBase: p["surface"], QPalette.ToolTipText: p["text"], QPalette.PlaceholderText: p["muted"],
        QPalette.Light: p["raised"], QPalette.Mid: p["line"], QPalette.Dark: p["line"],
    }.items():
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(p["faint"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["faint"]))
    application.setPalette(palette)
    application.setStyleSheet(f"""
        * {{ font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: 13px; }}
        QWidget {{ color: {p['text']}; }}
        QMainWindow, QWidget#Root, QWidget#Page {{ background: {p['bg']}; }}
        QDialog, QMessageBox {{ background: {p['surface']}; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel[role='muted'] {{ color: {p['muted']}; }}
        QLabel[role='small'] {{ font-size: 11px; color: {p['muted']}; }}
        QLabel[role='heading'] {{ font-size: 19px; font-weight: 700; }}
        QLabel[role='title'] {{ font-size: 24px; font-weight: 700; }}
        QLabel[role='amount'] {{ font-size: 34px; font-weight: 700; }}
        QLabel[role='price'] {{ font-size: 21px; font-weight: 700; }}
        QLabel[role='metric'] {{ font-size: 26px; font-weight: 700; }}
        QLabel[role='error'] {{ color: {p['danger']}; }}
        QLabel[role='success'] {{ color: {p['success']}; }}
        QFrame#Panel {{ background: {p['surface']}; border: 1px solid {p['line']}; border-radius: 14px; }}
        QFrame#SubPanel {{ background: {p['raised']}; border: none; border-radius: 10px; }}
        QFrame#RevenuePrimary {{ background: {p['soft']}; border: 1px solid {p['accent']}; border-radius: 14px; }}
        QFrame#RevenuePrimary QLabel[role='metric'] {{ color: {p['accent_text']}; }}
        QFrame#Header {{ background: {p['surface']}; border-bottom: 1px solid {p['line']}; }}
        QFrame#Rail {{ background: #191D25; border: none; }}
        QLabel#Logo {{ background: {p['accent']}; color: #282219; font-size: 20px; font-weight: 900; border-radius: 11px; }}
        QLabel#RailBrand {{ color: #F6F7F9; font-size: 16px; font-weight: 700; }}
        QLabel#RailNote {{ color: #8B95A7; font-size: 11px; }}
        QFrame#Divider {{ background: {p['line']}; border: none; max-height: 1px; }}
        QPushButton {{ background: {p['raised']}; color: {p['text']}; border: 1px solid {p['line']};
            border-radius: 8px; padding: 9px 15px; font-weight: 500; }}
        QPushButton:hover {{ background: {p['hover']}; }}
        QPushButton:pressed {{ background: {p['soft']}; border-color: {p['accent']}; }}
        QPushButton:focus {{ border-color: {p['accent']}; }}
        QPushButton:disabled {{ color: {p['faint']}; background: {p['raised']}; border-color: {p['line']}; }}
        QPushButton[variant='primary'] {{ background: {p['accent']}; color: #292213; border: none; font-weight: 700; }}
        QPushButton[variant='primary']:hover {{ background: #FFD964; }}
        QPushButton[variant='primary']:pressed {{ background: #ECB321; }}
        QPushButton[variant='primary']:disabled {{ background: {p['raised']}; color: {p['faint']}; border: 1px solid {p['line']}; }}
        QPushButton[variant='danger'] {{ background: {p['danger_bg']}; color: {p['danger']}; border: none; }}
        QPushButton[variant='danger']:hover {{ border: 1px solid {p['danger']}; }}
        QPushButton[variant='danger']:disabled {{ background: {p['raised']}; color: {p['faint']}; border: 1px solid {p['line']}; }}
        QPushButton[variant='quiet'] {{ background: transparent; border: none; color: {p['muted']}; }}
        QPushButton[variant='quiet']:hover {{ background: {p['hover']}; color: {p['text']}; }}
        QPushButton[variant='nav'] {{ background: transparent; border: none; color: #AAB3C2;
            text-align: left; padding: 13px 14px; border-radius: 9px; }}
        QPushButton[variant='nav']:hover {{ background: #2B303A; color: #FFFFFF; }}
        QPushButton[variant='nav']:checked {{ background: {p['accent']}; color: #292213; font-weight: 700; }}
        QPushButton[variant='chip'] {{ border: 1px solid {p['line']}; background: {p['surface']}; padding: 7px 13px; border-radius: 16px; }}
        QPushButton[variant='chip']:checked {{ border-color: {p['accent']}; background: {p['soft']}; color: {p['accent_text']}; font-weight: 700; }}
        QPushButton[variant='tile'] {{ border: 1px solid {p['line']}; background: {p['surface']}; border-radius: 11px; padding: 0; }}
        QPushButton[variant='tile']:hover {{ border-color: {p['accent']}; background: {p['raised']}; }}
        QPushButton[variant='tile']:checked {{ border: 2px solid {p['accent']}; background: {p['soft']}; }}
        QPushButton[variant='tile'][occupied='true'] {{ background: {p['busy_bg']}; border-color: {p['busy_line']}; }}
        QPushButton[variant='tile'][occupied='true']:hover {{ background: {p['busy_hover']}; border-color: {p['success']}; }}
        QPushButton[variant='tile'][occupied='true']:checked {{ background: {p['busy_selected']}; border: 2px solid {p['accent']}; }}
        QPushButton[occupied='true'] QLabel#TileTitle, QPushButton[occupied='true'] QLabel#TableAmount {{ color: {p['busy_text']}; }}
        QLabel#TableAmount {{ font-size: 13px; font-weight: 600; }}
        QLabel#TableState {{ background: {p['raised']}; color: {p['muted']}; border-radius: 5px; padding: 3px 6px; font-size: 11px; }}
        QLabel#TableState[occupied='true'] {{ background: {p['busy_badge']}; color: {p['busy_badge_text']}; font-weight: 700; }}
        QLabel#TileTitle {{ font-size: 15px; font-weight: 700; }}
        QLabel#CategoryTag {{ color: {p['muted']}; font-size: 11px; }}
        QLabel#AddDot {{ background: {p['accent']}; color: #292213; border-radius: 14px; font-size: 22px; }}
        QLabel#Badge {{ background: {p['success_bg']}; color: {p['success']}; border-radius: 5px; padding: 4px 8px; font-size: 11px; }}
        QLabel#Badge[occupied='false'] {{ background: {p['raised']}; color: {p['muted']}; }}
        QSplitter#CashierSplitter {{ background: transparent; }}
        QFrame#CartLine {{ background: transparent; border-bottom: 1px solid {p['line']}; }}
        QLineEdit, QComboBox, QSpinBox, QDateEdit {{ background: {p['raised']}; border: 1px solid {p['line']};
            border-radius: 8px; padding: 8px 11px; min-height: 21px; selection-background-color: {p['accent']}; selection-color: #252015; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border: 1px solid {p['accent']}; }}
        QDateEdit:disabled {{ color: {p['faint']}; }}
        QDateEdit::drop-down {{ border: none; width: 34px; }}
        QDateEdit::down-arrow {{ image: none; }}
        QDateEdit {{ padding-right: 30px; }}
        QCalendarWidget {{ background: {p['surface']}; border: 1px solid {p['line']}; }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p['raised']}; }}
        QCalendarWidget QAbstractItemView {{ background: {p['surface']}; color: {p['text']};
            alternate-background-color: {p['raised']}; selection-background-color: {p['accent']}; selection-color: #252015; outline: 0; }}
        QCalendarWidget QToolButton {{ background: transparent; color: {p['text']}; border: none;
            border-radius: 5px; padding: 8px; }}
        QCalendarWidget QToolButton:hover {{ background: {p['hover']}; }}
        QCalendarWidget QSpinBox {{ padding: 3px; min-width: 70px; }}
        QComboBox::drop-down {{ border: none; width: 26px; }}
        QComboBox::down-arrow {{ image: none; }}
        QComboBox {{ padding-right: 28px; }}
        QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['line']};
            selection-background-color: {p['soft']}; selection-color: {p['text']}; padding: 5px; outline: 0; }}
        QCheckBox {{ spacing: 9px; padding: 5px 0; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
        QTableWidget {{ background: {p['surface']}; alternate-background-color: {p['raised']};
            border: none; selection-background-color: {p['soft']}; selection-color: {p['text']}; gridline-color: {p['line']}; outline: none; }}
        QTableWidget::item {{ border: none; padding: 10px; }}
        QTableWidget::item:selected {{ background: {p['soft']}; color: {p['text']}; }}
        QHeaderView::section {{ background: {p['raised']}; border: none; border-bottom: 1px solid {p['line']};
            padding: 12px; color: {p['muted']}; font-size: 12px; font-weight: 500; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px 0; }}
        QScrollBar::handle:vertical {{ background: {p['line']}; min-height: 32px; border-radius: 3px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QScrollBar:horizontal {{ height: 7px; background: transparent; }}
        QScrollBar::handle:horizontal {{ background: {p['line']}; min-width: 32px; border-radius: 3px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QPlainTextEdit {{ background: {p['raised']}; color: {p['text']}; border: 1px solid {p['line']}; border-radius: 8px; padding: 14px; }}
        QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 8px; }}
        QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 6px; }}
        QMenu::item {{ padding: 10px 22px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {p['soft']}; }}
    """)
    return p
