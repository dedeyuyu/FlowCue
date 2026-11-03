# -*- coding: utf-8 -*-
"""
轻量表格委托（Delegate）。

以前表格的每一行都要 setCellWidget 放一个真正的 QPushButton / QWidget，
行数一多（几十上百行）创建、布局、重绘都非常慢，切换项目、刷新表格时明显卡顿。
这里改为「画出来的按钮」：只在可见行绘制，点击时发出信号，几百行也几乎零开销。
"""
from contextlib import contextmanager

from PyQt6.QtCore import Qt, QRect, QRectF, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QFont, QPainterPath
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem, QHeaderView


@contextmanager
def bulk_table_update(table):
    """
    批量写入表格时使用：
    「按内容自适应列宽 (ResizeToContents)」的列在每次 setItem 时都会重新扫描整列计算宽度，
    行数多时整体变成 O(n²)，是表格刷新卡顿的主要原因。这里在批量写入期间临时改成固定宽度，
    并暂停重绘，写完后再恢复，只计算一次。
    """
    hdr = table.horizontalHeader()
    saved = []
    for c in range(table.columnCount()):
        mode = hdr.sectionResizeMode(c)
        if mode == QHeaderView.ResizeMode.ResizeToContents:
            saved.append(c)
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
    was_sorting = table.isSortingEnabled()
    if was_sorting:
        table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    try:
        yield
    finally:
        for c in saved:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        if was_sorting:
            table.setSortingEnabled(True)
        table.setUpdatesEnabled(True)


class TableButtonDelegate(QStyledItemDelegate):
    """在单元格中绘制一个（或多个）按钮，点击时发出 clicked(row, button_index)。"""
    clicked = pyqtSignal(int, int)

    def __init__(self, labels, parent=None, colors=None, hover_colors=None, text_color="#FFFFFF",
                 font_px=11, padding=4, bold=True):
        super().__init__(parent)
        self.labels = list(labels) if isinstance(labels, (list, tuple)) else [labels]
        n = len(self.labels)
        self.colors = list(colors or ["#E0A96D"] * n)
        self.hover_colors = list(hover_colors or self.colors)
        self.text_color = QColor(text_color)
        self.font_px = font_px
        self.padding = padding
        self.bold = bold
        self._hover = (-1, -1)
        self._pressed = (-1, -1)

    # ── 几何
    def _button_rects(self, rect):
        n = len(self.labels)
        r = rect.adjusted(self.padding, self.padding, -self.padding, -self.padding)
        gap = 4
        w = max(10, (r.width() - gap * (n - 1)) // n)
        h = min(r.height(), 26)
        top = r.top() + (r.height() - h) // 2
        return [QRect(r.left() + i * (w + gap), top, w, h) for i in range(n)]

    def _hit(self, rect, pos):
        for i, br in enumerate(self._button_rects(rect)):
            if br.contains(pos):
                return i
        return -1

    # ── 绘制
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(option.font)
        f.setPixelSize(self.font_px)
        f.setBold(self.bold)
        painter.setFont(f)
        for i, br in enumerate(self._button_rects(option.rect)):
            hot = self._hover == (index.row(), i)
            down = self._pressed == (index.row(), i)
            col = QColor(self.hover_colors[i] if hot else self.colors[i])
            if down:
                col = col.darker(115)
            path = QPainterPath()
            path.addRoundedRect(QRectF(br), 4, 4)
            painter.fillPath(path, col)
            painter.setPen(self.text_color)
            painter.drawText(br, Qt.AlignmentFlag.AlignCenter, self.labels[i])
        painter.restore()

    # ── 交互
    def editorEvent(self, event, model, option, index):
        et = event.type()
        if et in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                  QEvent.Type.MouseButtonDblClick):
            pos = event.position().toPoint()
            hit = self._hit(option.rect, pos)
            view = option.widget
            if et == QEvent.Type.MouseMove:
                new_hover = (index.row(), hit) if hit >= 0 else (-1, -1)
                if new_hover != self._hover:
                    old_row = self._hover[0]
                    self._hover = new_hover
                    if view is not None:
                        vp = view.viewport()
                        vp.update(option.rect)
                        if old_row >= 0 and old_row != index.row():
                            try:
                                vp.update(view.visualRect(model.index(old_row, index.column())))
                            except Exception:
                                vp.update()
                return False
            if hit < 0:
                return False
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._pressed = (index.row(), hit)
                if view is not None:
                    view.viewport().update(option.rect)
                return True
            if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                was = self._pressed
                self._pressed = (-1, -1)
                if view is not None:
                    view.viewport().update(option.rect)
                if was == (index.row(), hit):
                    self.clicked.emit(index.row(), hit)
                return True
            if et == QEvent.Type.MouseButtonDblClick:
                return True  # 吞掉双击，避免触发单元格编辑
        return super().editorEvent(event, model, option, index)

    def createEditor(self, parent, option, index):
        return None


class ThumbnailDelegate(QStyledItemDelegate):
    """
    按需绘制缩略图：只有滚动到可见区域的行才会去加载 / 解码图片（通过 loader(path) 获取并由调用方缓存），
    不再在刷新表格时为每一行创建 QLabel 并一次性解码全部图片。
    图片路径存放在单元格的 Qt.ItemDataRole.UserRole 中。
    """

    def __init__(self, loader, parent=None, box_w=106, box_h=68):
        super().__init__(parent)
        self.loader = loader
        self.box_w, self.box_h = box_w, box_h

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        path = index.data(Qt.ItemDataRole.UserRole) or ""
        r = option.rect
        box = QRect(r.left() + (r.width() - self.box_w) // 2, r.top() + (r.height() - self.box_h) // 2,
                    self.box_w, self.box_h)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pix = self.loader(path) if path else None
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(box), 4, 4)
        if pix is not None and not pix.isNull():
            painter.fillPath(bg, QColor("#FFFDF9"))
            px = box.left() + (box.width() - pix.width()) // 2
            py = box.top() + (box.height() - pix.height()) // 2
            painter.drawPixmap(px, py, pix)
            painter.setPen(QColor("#D7CCC8"))
            painter.drawPath(bg)
        else:
            painter.fillPath(bg, QColor("#EFEBE9"))
            painter.setPen(QColor("#8D6E63"))
            f = QFont(option.font)
            f.setPixelSize(11)
            painter.setFont(f)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "文件缺失" if path else "无预览")
        painter.restore()

    def createEditor(self, parent, option, index):
        return None


class ComboDelegate(QStyledItemDelegate):
    """
    单元格平时只显示文字；点击时才临时创建下拉框（编辑结束即销毁）。
    items_provider() -> [(显示文字, 数据), ...]；on_commit(row, data) 在选择变化后回调。
    当前选中的数据存放在 Qt.ItemDataRole.UserRole 中。
    """

    def __init__(self, items_provider, on_commit, parent=None, combo_factory=None):
        super().__init__(parent)
        self.items_provider = items_provider
        self.on_commit = on_commit
        self.combo_factory = combo_factory

    def createEditor(self, parent, option, index):
        from PyQt6.QtWidgets import QComboBox
        from PyQt6.QtCore import QTimer
        cb = self.combo_factory(parent) if self.combo_factory else QComboBox(parent)
        cb.setMaxVisibleItems(14)
        for label, data in self.items_provider():
            cb.addItem(label, data)
        # 选择后立即提交并关闭编辑器
        cb.activated.connect(lambda _i, c=cb: (self.commitData.emit(c), self.closeEditor.emit(c)))
        QTimer.singleShot(0, cb.showPopup)
        return cb

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.UserRole) or ""
        i = editor.findData(val)
        editor.setCurrentIndex(i if i >= 0 else 0)

    def setModelData(self, editor, model, index):
        new_val = editor.currentData() or ""
        old_val = index.data(Qt.ItemDataRole.UserRole) or ""
        if new_val != old_val:
            self.on_commit(index.row(), new_val)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(3, 3, -3, -3))
