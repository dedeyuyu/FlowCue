# -*- coding: utf-8 -*-
"""
全局亮色 / 暗色主题管理器 (ThemeManager)
======================================
解决 Windows 11 系统深色模式下 Qt6 原生 Palette 将文字设为纯白色 (#FFFFFF)，
而局部 QSS 将表格/下拉框/输入框背景设为白色 (white)，导致「白底白字完全看不见」及
部分容器背景变纯黑的问题；同时提供完整的「☀️ 亮色模式」与「🌙 暗色模式」一键切换。
"""
import re
from PyQt6.QtCore import QObject, QEvent, Qt
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication, QWidget, QComboBox


class _ThemeEventFilter(QObject):
    """监听任意新建、显示或动态修改样式的 QWidget / QDialog / QMenu，自动适配其局部 QSS。"""

    def eventFilter(self, obj, event):
        try:
            etype = event.type()
            if etype in (QEvent.Type.Show, QEvent.Type.Polish, QEvent.Type.StyleChange):
                if isinstance(obj, QWidget):
                    ThemeManager.refresh_widget_style(
                        obj,
                        recursive=(etype == QEvent.Type.Show and obj.isWindow()),
                    )
        except Exception:
            pass
        return False


class ThemeManager:
    LIGHT = "light"
    DARK = "dark"

    _current_mode: str = "light"
    _event_filter: _ThemeEventFilter = None
    _refreshing_ids: set = set()

    # ── 暗色模式下的颜色映射表 ──
    _BG_MAP_DARK = {
        "white": "#242429",
        "#ffffff": "#242429",
        "#fff": "#242429",
        "#fffdf9": "#242429",
        "#fafafa": "#202025",
        "#f8fafc": "#202025",
        "#f5f5f5": "#202025",
        "#f5ebe6": "#18181b",
        "#faf6f0": "#18181b",
        "#ede0d4": "#27272a",
        "#efebe9": "#27272a",
        "#f3f4f6": "#27272a",
        "#d7ccc8": "#3f3f46",
        "#e0d7d3": "#3f3f46",
        "#b0bec5": "#3f3f46",
        "#cbd5e1": "#3f3f46",
        "#e2e8f0": "#3f3f46",
        "#e5e7eb": "#3f3f46",
        "#bcaaa4": "#52525b",
        "#90a4ae": "#52525b",
        "#ffe0b2": "#3f3222",
        "#fff8e1": "#3f3222",
        "#fff3e0": "#3f3222",
        "#fef3c7": "#3f3222",
        "#ecfdf5": "#143326",
        "#f0fdf4": "#143326",
        "#dcfce7": "#143326",
        "#d4edda": "#143326",
        "#fee2e2": "#3b1818",
        "#fef2f2": "#3b1818",
        "#e0e7ff": "#1e2540",
    }

    _BORDER_MAP_DARK = {
        "#d7ccc8": "#3f3f46",
        "#e0d7d3": "#3f3f46",
        "#efebe9": "#323238",
        "#cfd8dc": "#3f3f46",
        "#cbd5e1": "#3f3f46",
        "#e2e8f0": "#3f3f46",
        "#e5e7eb": "#3f3f46",
        "#d1d5db": "#3f3f46",
        "#f3f4f6": "#323238",
        "#f5f5f5": "#323238",
        "#bcaaa4": "#52525b",
        "#a7f3d0": "#059669",
        "#fcd34d": "#d97706",
    }

    _FG_MAP_DARK = {
        "#5d4037": "#f4f4f5",
        "#3e2723": "#f4f4f5",
        "#1f2937": "#f4f4f5",
        "#37474f": "#f4f4f5",
        "#111827": "#f4f4f5",
        "#333333": "#f4f4f5",
        "#333": "#f4f4f5",
        "#000000": "#f4f4f5",
        "black": "#f4f4f5",
        "#795548": "#a1a1aa",
        "#8d6e63": "#a1a1aa",
        "#4b5563": "#a1a1aa",
        "#6b7280": "#a1a1aa",
        "#64748b": "#a1a1aa",
        "#a1887f": "#a1a1aa",
        "#9ca3af": "#a1a1aa",
        "#155724": "#6ee7b7",
        "#059669": "#34d399",
        "#2e7d32": "#4ade80",
        "#0284c7": "#38bdf8",
        "#2563eb": "#60a5fa",
        "#d97706": "#fbbf24",
        "#f57f17": "#fbbf24",
        "#e65100": "#fb923c",
        "#dc2626": "#f87171",
        "#c62828": "#f87171",
        "#4338ca": "#818cf8",
    }

    @classmethod
    def get_mode(cls) -> str:
        return cls._current_mode

    @classmethod
    def is_dark(cls) -> bool:
        return cls._current_mode == cls.DARK

    @classmethod
    def build_palette(cls, mode: str) -> QPalette:
        """构建完整 QPalette，彻底阻止 Windows 11 深色系统主题篡改文字颜色。"""
        palette = QPalette()
        if mode == cls.DARK:
            c_window = QColor("#18181B")
            c_window_text = QColor("#F4F4F5")
            c_base = QColor("#242429")
            c_alt_base = QColor("#1E1E24")
            c_text = QColor("#F4F4F5")
            c_button = QColor("#2E2E36")
            c_button_text = QColor("#F4F4F5")
            c_bright_text = QColor("#FFFFFF")
            c_highlight = QColor("#3F3222")
            c_highlight_text = QColor("#FDE68A")
            c_tooltip_base = QColor("#27272A")
            c_tooltip_text = QColor("#F4F4F5")
            c_placeholder = QColor("#71717A")
            c_disabled_text = QColor("#71717A")
            c_disabled_btn = QColor("#27272A")
            c_link = QColor("#38BDF8")
        else:
            c_window = QColor("#F5EBE6")
            c_window_text = QColor("#3E2723")
            c_base = QColor("#FFFFFF")
            c_alt_base = QColor("#FAF6F0")
            c_text = QColor("#3E2723")
            c_button = QColor("#EFEBE9")
            c_button_text = QColor("#3E2723")
            c_bright_text = QColor("#FFFFFF")
            c_highlight = QColor("#FFE0B2")
            c_highlight_text = QColor("#3E2723")
            c_tooltip_base = QColor("#FFF8E1")
            c_tooltip_text = QColor("#3E2723")
            c_placeholder = QColor("#9E9E9E")
            c_disabled_text = QColor("#A1887F")
            c_disabled_btn = QColor("#D7CCC8")
            c_link = QColor("#0284C7")

        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, QPalette.ColorRole.Window, c_window)
            palette.setColor(group, QPalette.ColorRole.WindowText, c_window_text)
            palette.setColor(group, QPalette.ColorRole.Base, c_base)
            palette.setColor(group, QPalette.ColorRole.AlternateBase, c_alt_base)
            palette.setColor(group, QPalette.ColorRole.ToolTipBase, c_tooltip_base)
            palette.setColor(group, QPalette.ColorRole.ToolTipText, c_tooltip_text)
            palette.setColor(group, QPalette.ColorRole.PlaceholderText, c_placeholder)
            palette.setColor(group, QPalette.ColorRole.Text, c_text)
            palette.setColor(group, QPalette.ColorRole.Button, c_button)
            palette.setColor(group, QPalette.ColorRole.ButtonText, c_button_text)
            palette.setColor(group, QPalette.ColorRole.BrightText, c_bright_text)
            palette.setColor(group, QPalette.ColorRole.Highlight, c_highlight)
            palette.setColor(group, QPalette.ColorRole.HighlightedText, c_highlight_text)
            palette.setColor(group, QPalette.ColorRole.Link, c_link)

        # Disabled group
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, c_window)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, c_disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, c_alt_base)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.AlternateBase, c_alt_base)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, c_disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, c_disabled_btn)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, c_disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, c_highlight)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, c_disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.PlaceholderText, c_disabled_text)
        return palette

    @classmethod
    def get_global_stylesheet(cls, mode: str) -> str:
        """返回全局兜底 QSS，显式声明所有控件的背景色与文字色。"""
        if mode == cls.DARK:
            return """
                QMainWindow, QDialog {
                    background-color: #18181B;
                    color: #F4F4F5;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                }
                QWidget {
                    color: #F4F4F5;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                }
                QScrollArea, QScrollArea > QWidget > QWidget {
                    background-color: #18181B;
                    color: #F4F4F5;
                }
                QGroupBox {
                    background-color: #202025;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 14px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 6px;
                    color: #F4F4F5;
                }
                QLabel {
                    color: #F4F4F5;
                    background-color: transparent;
                }
                QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
                    background-color: #242429;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    border-radius: 4px;
                    padding: 4px 8px;
                    selection-background-color: #3F3222;
                    selection-color: #FDE68A;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                    border: 1px solid #E0A96D;
                }
                QComboBox {
                    combobox-popup: 0;
                    background-color: #242429;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    border-radius: 4px;
                    padding: 4px 8px;
                }
                QComboBox:hover {
                    border: 1px solid #E0A96D;
                }
                QComboBox:disabled {
                    background-color: #1E1E24;
                    color: #71717A;
                }
                QComboBox QAbstractItemView {
                    background-color: #242429;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    selection-background-color: #3F3222;
                    selection-color: #FDE68A;
                    outline: none;
                }
                QComboBox QAbstractItemView::item {
                    color: #F4F4F5;
                    background-color: #242429;
                    padding: 4px 8px;
                }
                QComboBox QAbstractItemView::item:selected,
                QComboBox QAbstractItemView::item:hover {
                    background-color: #3F3222;
                    color: #FDE68A;
                }
                QTableWidget, QTableView {
                    background-color: #242429;
                    alternate-background-color: #1E1E24;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    gridline-color: #323238;
                    selection-background-color: #3F3222;
                    selection-color: #FDE68A;
                    border-radius: 4px;
                }
                QTableWidget::item, QTableView::item {
                    color: #F4F4F5;
                }
                QTableWidget::item:selected, QTableView::item:selected {
                    background-color: #3F3222;
                    color: #FDE68A;
                }
                QTableWidget QLineEdit, QTableView QLineEdit {
                    background-color: #18181B;
                    color: #F4F4F5;
                    border: 1px solid #E0A96D;
                }
                QHeaderView::section {
                    background-color: #27272A;
                    color: #F4F4F5;
                    padding: 5px;
                    font-weight: bold;
                    border: 1px solid #3F3F46;
                }
                QTableCornerButton::section {
                    background-color: #27272A;
                    border: 1px solid #3F3F46;
                }
                QListWidget, QListView {
                    background-color: #242429;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    border-radius: 4px;
                }
                QListWidget::item {
                    color: #F4F4F5;
                }
                QListWidget::item:hover {
                    background-color: #2E2E36;
                    color: #F4F4F5;
                }
                QListWidget::item:selected {
                    background-color: #3F3222;
                    color: #FDE68A;
                    font-weight: bold;
                }
                QTabWidget::pane {
                    border: 1px solid #3F3F46;
                    background-color: #18181B;
                    border-radius: 4px;
                }
                QTabBar::tab {
                    background-color: #27272A;
                    color: #A1A1AA;
                    padding: 8px 16px;
                    font-weight: bold;
                    border: 1px solid #3F3F46;
                    border-bottom: none;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    margin-right: 2px;
                }
                QTabBar::tab:selected {
                    background-color: #18181B;
                    color: #F4F4F5;
                    border-bottom: 2px solid #E0A96D;
                }
                QTabBar::tab:hover {
                    background-color: #3F3222;
                    color: #FDE68A;
                }
                QCheckBox {
                    color: #F4F4F5;
                    spacing: 6px;
                }
                QMenu {
                    background-color: #242429;
                    color: #F4F4F5;
                    border: 1px solid #3F3F46;
                    border-radius: 4px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 20px 6px 10px;
                    color: #F4F4F5;
                }
                QMenu::item:selected {
                    background-color: #3F3222;
                    color: #FDE68A;
                    border-radius: 3px;
                }
                QToolTip {
                    background-color: #27272A;
                    color: #F4F4F5;
                    border: 1px solid #E0A96D;
                    padding: 4px 6px;
                }
                QMessageBox, QInputDialog {
                    background-color: #18181B;
                    color: #F4F4F5;
                }
                QMessageBox QLabel, QInputDialog QLabel {
                    color: #F4F4F5;
                }
                QPushButton {
                    background-color: #E0A96D;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #D2904C;
                }
                QPushButton:pressed {
                    background-color: #B87635;
                }
                QPushButton:disabled {
                    background-color: #2E2E36;
                    color: #71717A;
                }
            """
        else:
            return """
                QMainWindow, QDialog {
                    background-color: #F5EBE6;
                    color: #3E2723;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                }
                QWidget {
                    color: #3E2723;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                }
                QScrollArea, QScrollArea > QWidget > QWidget {
                    background-color: #FAF6F0;
                    color: #3E2723;
                }
                QGroupBox {
                    background-color: #FFFFFF;
                    color: #5D4037;
                    border: 1px solid #D7CCC8;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 14px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 6px;
                    color: #5D4037;
                }
                QLabel {
                    color: #5D4037;
                    background-color: transparent;
                }
                QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    border-radius: 4px;
                    padding: 4px 8px;
                    selection-background-color: #FFE0B2;
                    selection-color: #3E2723;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                    border: 1px solid #E0A96D;
                }
                QComboBox {
                    combobox-popup: 0;
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    border-radius: 4px;
                    padding: 4px 8px;
                }
                QComboBox:hover {
                    border: 1px solid #E0A96D;
                }
                QComboBox:disabled {
                    background-color: #F5F5F5;
                    color: #A1887F;
                }
                QComboBox QAbstractItemView {
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    selection-background-color: #FFE0B2;
                    selection-color: #3E2723;
                    outline: none;
                }
                QComboBox QAbstractItemView::item {
                    color: #3E2723;
                    background-color: #FFFFFF;
                    padding: 4px 8px;
                }
                QComboBox QAbstractItemView::item:selected,
                QComboBox QAbstractItemView::item:hover {
                    background-color: #FFE0B2;
                    color: #3E2723;
                }
                QTableWidget, QTableView {
                    background-color: #FFFFFF;
                    alternate-background-color: #FAF6F0;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    gridline-color: #EFEBE9;
                    selection-background-color: #FFE0B2;
                    selection-color: #3E2723;
                    border-radius: 4px;
                }
                QTableWidget::item, QTableView::item {
                    color: #3E2723;
                }
                QTableWidget::item:selected, QTableView::item:selected {
                    background-color: #FFE0B2;
                    color: #3E2723;
                }
                QTableWidget QLineEdit, QTableView QLineEdit {
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #E0A96D;
                }
                QHeaderView::section {
                    background-color: #D7CCC8;
                    color: #5D4037;
                    padding: 5px;
                    font-weight: bold;
                    border: 1px solid #EFEBE9;
                }
                QTableCornerButton::section {
                    background-color: #D7CCC8;
                    border: 1px solid #EFEBE9;
                }
                QListWidget, QListView {
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    border-radius: 4px;
                }
                QListWidget::item {
                    color: #3E2723;
                }
                QListWidget::item:hover {
                    background-color: #F5F5F5;
                    color: #3E2723;
                }
                QListWidget::item:selected {
                    background-color: #FFE0B2;
                    color: #3E2723;
                    font-weight: bold;
                }
                QCheckBox {
                    color: #5D4037;
                    spacing: 6px;
                }
                QMenu {
                    background-color: #FFFFFF;
                    color: #3E2723;
                    border: 1px solid #D7CCC8;
                    border-radius: 4px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 20px 6px 10px;
                    color: #3E2723;
                }
                QMenu::item:selected {
                    background-color: #FFE0B2;
                    color: #3E2723;
                    border-radius: 3px;
                }
                QToolTip {
                    background-color: #FFF8E1;
                    color: #3E2723;
                    border: 1px solid #E0A96D;
                    padding: 4px 6px;
                }
                QMessageBox, QInputDialog {
                    background-color: #FAF6F0;
                    color: #3E2723;
                }
                QMessageBox QLabel, QInputDialog QLabel {
                    color: #3E2723;
                }
            """

    @classmethod
    def adapt_qss(cls, orig_qss: str, mode: str) -> str:
        """
        将组件原本针对亮色模式编写的局部 QSS 转换为目标模式（亮色或暗色）的安全 QSS。
        - 亮色模式：补齐缺失的文字颜色声明，确保在任何系统主题下绝不出现白底白字。
        - 暗色模式：智能映射背景色、边框色、文字色、选中高亮色，同时保留彩色功能按钮。
        """
        if not orig_qss:
            return orig_qss

        if mode == cls.LIGHT:
            prefix_light = []
            suffix_light = []
            if "QTableWidget" in orig_qss:
                prefix_light.append("QTableWidget, QTableWidget::item { color: #3E2723; }\n")
                suffix_light.append(
                    "\nQTableWidget QLineEdit { background-color: #FFFFFF; color: #3E2723; }"
                )
            if "QComboBox" in orig_qss:
                prefix_light.append("QComboBox { combobox-popup: 0; color: #3E2723; }\n")
                suffix_light.append(
                    "\nQComboBox { combobox-popup: 0; }"
                    "\nQComboBox QAbstractItemView, QComboBox QAbstractItemView::item { color: #3E2723; background-color: #FFFFFF; }"
                    "\nQComboBox QAbstractItemView::item:selected { background-color: #FFE0B2; color: #3E2723; }"
                )
            if "QSpinBox" in orig_qss:
                prefix_light.append("QSpinBox { color: #3E2723; }\n")
            if "QScrollArea" in orig_qss:
                suffix_light.append("\nQScrollArea > QWidget > QWidget { background-color: #FAF6F0; color: #3E2723; }")
            return "".join(prefix_light) + orig_qss + "".join(suffix_light)

        # ── Dark Mode 转换 ──
        qss = orig_qss

        # 1. 替换 background-color / background / border-bottom-color / alternate-background-color
        def _replace_bg(match):
            prop = match.group(1)
            val = match.group(2).strip()
            low = val.lower()
            mapped = cls._BG_MAP_DARK.get(low, val)
            return f"{prop}: {mapped}"

        qss = re.sub(
            r"((?:alternate-)?background(?:-color)?|border-bottom-color)\s*:\s*(#[0-9a-fA-F]{3,6}|white)\b",
            _replace_bg,
            qss,
            flags=re.IGNORECASE,
        )

        # 2. 替换 selection-background-color
        def _replace_sel_bg(match):
            val = match.group(1).strip().lower()
            return "selection-background-color: #3F3222" if val in cls._BG_MAP_DARK else match.group(0)

        qss = re.sub(
            r"selection-background-color\s*:\s*(#[0-9a-fA-F]{3,6}|white)\b",
            _replace_sel_bg,
            qss,
            flags=re.IGNORECASE,
        )

        # 3. 替换 selection-color
        qss = re.sub(
            r"selection-color\s*:\s*(#[0-9a-fA-F]{3,6}|black)\b",
            "selection-color: #FDE68A",
            qss,
            flags=re.IGNORECASE,
        )

        # 4. 替换 border / gridline-color 中的浅色边框
        def _replace_border_color(match):
            prefix = match.group(1)
            color_val = match.group(2).strip()
            low = color_val.lower()
            mapped = cls._BORDER_MAP_DARK.get(low, color_val)
            return f"{prefix}{mapped}"

        qss = re.sub(
            r"((?:border(?:-(?:top|bottom|left|right))?(?:-color)?|gridline-color)\s*:\s*(?:\d+px\s+\w+\s+)?)(#[0-9a-fA-F]{3,6})\b",
            _replace_border_color,
            qss,
            flags=re.IGNORECASE,
        )

        # 5. 替换前景文字 color (排除 background-color, border-color, selection-color, gridline-color)
        def _replace_fg(match):
            val = match.group(1).strip()
            low = val.lower()
            mapped = cls._FG_MAP_DARK.get(low, val)
            return f"color: {mapped}"

        qss = re.sub(
            r"(?<![-\w])color\s*:\s*(#[0-9a-fA-F]{3,6}|black)\b",
            _replace_fg,
            qss,
            flags=re.IGNORECASE,
        )

        # 6. 为常见复合组件追加暗色兜底规则（基础色前置，子视图后置，保留特定组件高亮色）
        prefix_dark = []
        suffix_dark = []
        if "QTableWidget" in orig_qss:
            prefix_dark.append("QTableWidget, QTableWidget::item { color: #F4F4F5; }\n")
            suffix_dark.append(
                "\nQTableWidget::item:selected { background-color: #3F3222; color: #FDE68A; }"
                "\nQTableWidget QLineEdit { background-color: #18181B; color: #F4F4F5; border: 1px solid #E0A96D; }"
            )
        if "QComboBox" in orig_qss:
            prefix_dark.append("QComboBox { combobox-popup: 0; color: #F4F4F5; background-color: #242429; }\n")
            suffix_dark.append(
                "\nQComboBox { combobox-popup: 0; }"
                "\nQComboBox QAbstractItemView, QComboBox QAbstractItemView::item { color: #F4F4F5; background-color: #242429; }"
                "\nQComboBox QAbstractItemView::item:selected { background-color: #3F3222; color: #FDE68A; }"
            )
        if "QSpinBox" in orig_qss:
            prefix_dark.append("QSpinBox { color: #F4F4F5; background-color: #242429; }\n")
        if "QScrollArea" in orig_qss:
            suffix_dark.append("\nQScrollArea > QWidget > QWidget { background-color: #18181B; color: #F4F4F5; }")

        return "".join(prefix_dark) + qss + "".join(suffix_dark)

    @classmethod
    def refresh_widget_style(cls, widget: QWidget, recursive: bool = True):
        """刷新指定控件（及其子控件）的局部 QSS，使其匹配当前亮色/暗色主题。"""
        if widget is None:
            return
        wid = id(widget)
        if wid in cls._refreshing_ids:
            return
        cls._refreshing_ids.add(wid)
        try:
            if isinstance(widget, QComboBox):
                if widget.maxVisibleItems() > 12 or widget.maxVisibleItems() == 10:
                    widget.setMaxVisibleItems(12)
                view = widget.view()
                if view is not None:
                    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

            cur_qss = widget.styleSheet()
            if cur_qss:
                last_applied = widget.property("_last_applied_theme_qss")
                orig_qss = widget.property("_orig_light_qss")
                # 若业务代码刚刚设置了新的 QSS，更新原始 QSS 记录
                if orig_qss is None or (last_applied is not None and cur_qss != last_applied):
                    orig_qss = cur_qss
                    widget.setProperty("_orig_light_qss", orig_qss)

                adapted = cls.adapt_qss(orig_qss, cls._current_mode)
                widget.setProperty("_last_applied_theme_qss", adapted)
                if cur_qss != adapted:
                    widget.setStyleSheet(adapted)
        except Exception:
            pass
        finally:
            cls._refreshing_ids.discard(wid)

        if recursive:
            try:
                for child in widget.findChildren(QWidget):
                    cls.refresh_widget_style(child, recursive=False)
            except Exception:
                pass

    @classmethod
    def apply_theme(cls, mode: str = "light", app: QApplication = None):
        """在 QApplication 上应用亮色或暗色主题，并实时刷新所有已打开的窗口与控件。"""
        mode = cls.DARK if str(mode).lower() == cls.DARK else cls.LIGHT
        cls._current_mode = mode

        if app is None:
            app = QApplication.instance()
        if app is None:
            return

        # 1. 使用跨平台一致的 Fusion 引擎，彻底隔离 Windows 11 原生深色主题对文字颜色的强制覆盖
        try:
            app.setStyle("Fusion")
        except Exception:
            pass

        # 2. 同步 Qt 6.5+ ColorScheme 提示
        try:
            hints = app.styleHints()
            if hasattr(hints, "setColorScheme") and hasattr(Qt, "ColorScheme"):
                scheme = Qt.ColorScheme.Dark if mode == cls.DARK else Qt.ColorScheme.Light
                hints.setColorScheme(scheme)
        except Exception:
            pass

        # 3. 设置全局 Palette 与全局兜底 QSS
        app.setPalette(cls.build_palette(mode))
        app.setStyleSheet(cls.get_global_stylesheet(mode))

        # 4. 安装全局事件过滤器（拦截后续打开的弹窗、下拉菜单等）
        if cls._event_filter is None:
            cls._event_filter = _ThemeEventFilter(app)
            app.installEventFilter(cls._event_filter)

        # 5. 遍历当前所有顶层窗口与子控件，实时转换局部 QSS
        for top_widget in app.topLevelWidgets():
            cls.refresh_widget_style(top_widget, recursive=True)

    # ── 提供给业务代码的动态颜色辅助函数 ──
    @classmethod
    def get_default_item_fg(cls) -> QColor:
        """获取列表/表格默认文字颜色"""
        return QColor("#F4F4F5") if cls.is_dark() else QColor("#5D4037")

    @classmethod
    def get_copied_row_colors(cls) -> tuple[QColor, QColor]:
        """获取已完成/已复制行的 (背景色, 文字色)"""
        if cls.is_dark():
            return QColor("#143A29"), QColor("#6EE7B7")
        return QColor("#D4EDDA"), QColor("#155724")
